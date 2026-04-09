#!/usr/bin/env python3
"""
settings_dataclass decorator, SettingsMixin and CachableSettings mixin.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import warnings
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from pydantic import ConfigDict, TypeAdapter
from pydantic.dataclasses import dataclass as pydantic_dataclass

from .cachable import Cachable, _LazyRLock
from .fingerprint import _serialize, fingerprint

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = ConfigDict(frozen=True, validate_default=True, kw_only=True)


def settings_dataclass(
    cls: type | None = None,
    *,
    config: ConfigDict | None = None,
    **kwargs: Any,
) -> type | Callable[[type], type]:
    """
    Decorator for settings dataclasses.

    Combines:
    - Pydantic dataclass validation
    - Frozen (immutable) instances by default
    - Warning on extra fields (instead of silent ignore)
    - kw_only=True by default for better error messages and immutability

    Args:
        cls: Class to decorate (auto-filled when used without parentheses)
        config: Custom Pydantic ConfigDict (default: frozen=True)
        **kwargs: Additional arguments passed to pydantic_dataclass

    Example::

        @settings_dataclass
        class MySettings:
            param: int = 10

        @settings_dataclass(config=ConfigDict(frozen=True, extra="forbid"))
        class StrictSettings:
            value: str
    """
    if config is None:
        config = DEFAULT_CONFIG

    def decorator(cls):
        is_kw_only = kwargs.get("kw_only", config.get("kw_only", True))
        decorated = pydantic_dataclass(config=config, **kwargs, kw_only=is_kw_only)(cls)

        # Cache the TypeAdapter for performance
        _adapter = TypeAdapter(decorated)

        original_init = decorated.__init__
        field_names = set(decorated.__pydantic_fields__.keys())

        def new_init(self, **kwargs):  # pylint: disable=unused-argument
            extra = set(kwargs.keys()) - field_names
            if extra:
                warnings.warn(
                    f"{cls.__name__}: Unknown fields ignored: {extra}",
                    UserWarning,
                    stacklevel=2,
                )
            filtered = {k: v for k, v in kwargs.items() if k in field_names}
            original_init(self, **filtered)

        def model_dump(self, *, mode="python", **dump_kwargs):
            """Dump settings to a dict via Pydantic serialization."""
            return _adapter.dump_python(self, mode=mode, **dump_kwargs)

        decorated.__init__ = new_init
        decorated.model_dump = model_dump
        return decorated

    # Handle @settings_dataclass without parentheses
    if cls is not None:
        return decorator(cls)

    return decorator


# -------------------------------------------------------------------------
# SettingsMixin
# -------------------------------------------------------------------------


class SettingsMixin:
    """
    Settings management mixin.

    Provides settings storage, fingerprinting, shadow views, and serialisation.
    Can be used standalone (no cache) or combined with :class:`Cachable` via
    :class:`CachableSettings`.

    Example::

        @settings_dataclass
        class MySettings:
            alpha: float = 0.5

        class MyProcessor(SettingsMixin):
            SETTINGS_CLASS = MySettings

            def __init__(self, alpha=0.5):
                super().__init__(settings=MySettings(alpha=alpha))

            def __call__(self, x, **kwargs):
                target = self._get_or_create_shadow(kwargs) if kwargs else self
                return x * target.settings.alpha
    """

    SETTINGS_CLASS = None
    SHADOW_CACHE_SIZE = 8

    def __init__(self, settings: Any = None) -> None:
        self._settings = self._validate_settings(settings)
        self._fingerprint = (
            fingerprint(self._settings) if self._settings is not None else None
        )
        self._shadow_cache: OrderedDict = OrderedDict()

    def _validate_settings(self, settings: Any) -> Any:
        """Validate and normalize settings input."""
        if self.SETTINGS_CLASS is None:
            if settings is not None:
                LOGGER.warning(
                    "%s: SETTINGS_CLASS is None, ignoring provided settings",
                    self.__class__.__name__,
                )
            return None

        if settings is None:
            return self.SETTINGS_CLASS()  # pylint: disable=not-callable

        if isinstance(settings, dict):
            return self.SETTINGS_CLASS(**settings)  # pylint: disable=not-callable

        if not isinstance(settings, self.SETTINGS_CLASS):  # pylint: disable=W1116
            raise TypeError(
                f"settings must be an instance of {self.SETTINGS_CLASS.__name__}, "
                f"got {type(settings).__name__}"
            )

        return settings

    @property
    def settings(self) -> Any:
        """Current settings (immutable)."""
        return self._settings

    @property
    def cache_fingerprint(self) -> str | None:
        """Current fingerprint for cache keying."""
        return self._fingerprint

    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------

    def update_settings(self, settings: Any = None, **kwargs: Any) -> SettingsMixin:
        """
        Replace settings and clear shadow cache.

        Accepts either a settings dataclass instance, a dict of field values,
        or keyword arguments for field values.

        Args:
            settings: Settings instance or dict (optional)
            **kwargs: Field values to update

        Returns:
            self (for method chaining)

        Example::

            processor.update_settings(param=10)
            processor.update_settings({"param": 10})
            processor.update_settings(MySettings(param=10))
        """
        if self.SETTINGS_CLASS is None:
            raise ValueError("Cannot update settings: SETTINGS_CLASS is None")

        if settings is not None:
            if isinstance(settings, dict):
                kwargs = {**settings, **kwargs}
            # pylint: disable=isinstance-second-argument-not-valid-type
            elif isinstance(settings, self.SETTINGS_CLASS):
                if not kwargs:
                    self._settings = settings
                    self._fingerprint = fingerprint(self._settings)
                    self._shadow_cache.clear()
                    return self
                kwargs = {**dataclasses.asdict(settings), **kwargs}
            else:
                raise TypeError(
                    f"settings must be {self.SETTINGS_CLASS.__name__} or dict, "
                    f"got {type(settings).__name__}"
                )

        self._settings = dataclasses.replace(self._settings, **kwargs)
        self._fingerprint = fingerprint(self._settings)
        self._shadow_cache.clear()
        return self

    # -------------------------------------------------------------------------
    # Shadow Views
    # -------------------------------------------------------------------------

    def _get_or_create_shadow(self, overrides: dict[str, Any]) -> SettingsMixin:
        """
        Get or create a shadow view with overridden settings.

        Keys in *overrides* that do not match a settings field are silently
        ignored.  Returns ``self`` when no valid override remains.
        Uses an LRU cache (keyed by fingerprint) to reuse shadows.

        Args:
            overrides: Mapping of field names to override values.
                Non-settings keys are filtered out automatically.
        """
        if not overrides:
            return self

        # Filter to known settings fields
        settings_fields = set(self._settings.__dataclass_fields__.keys())
        valid = {k: v for k, v in overrides.items() if k in settings_fields}
        if not valid:
            return self

        new_settings = dataclasses.replace(self._settings, **valid)
        new_fp = fingerprint(new_settings)

        # LRU lookup
        if new_fp in self._shadow_cache:
            self._shadow_cache.move_to_end(new_fp)
            return self._shadow_cache[new_fp]

        # Create new shadow
        shadow = object.__new__(self.__class__)
        shadow.__dict__.update(self.__dict__)
        # pylint: disable=protected-access
        shadow._settings = new_settings
        shadow._fingerprint = new_fp
        shadow._shadow_cache = OrderedDict()

        # LRU insert + eviction
        self._shadow_cache[new_fp] = shadow
        if len(self._shadow_cache) > self.SHADOW_CACHE_SIZE:
            self._shadow_cache.popitem(last=False)

        return shadow

    @staticmethod
    def shadow_dispatch(*args: str | Callable) -> Callable:
        """
        Decorator that transparently handles shadow dispatch from ``**kwargs``.

        Settings-matching kwargs are consumed to create (or reuse) a shadow
        view; the method body receives only the remaining kwargs, with ``self``
        already pointing to the correct target (shadow or original).

        By default all settings fields are dispatched. Pass field names to
        restrict which kwargs trigger a shadow::

            @SettingsMixin.shadow_dispatch
            @Cachable.cached_method()
            def compute(self, x, **kwargs):
                return x * self.settings.alpha

            @SettingsMixin.shadow_dispatch("alpha")
            @Cachable.cached_method()
            def compute(self, x, **kwargs):
                # only 'alpha' triggers a shadow; other settings kwargs
                # pass through to the method body unchanged.
                return x * self.settings.alpha
        """

        def _build(
            method: Callable, dispatch_fields: frozenset[str] | None
        ) -> Callable:
            @functools.wraps(method)
            def wrapper(self, *w_args, **kwargs):
                if kwargs and self._settings is not None:
                    settings_fields = set(self._settings.__dataclass_fields__.keys())
                    consumed = (
                        dispatch_fields & settings_fields
                        if dispatch_fields is not None
                        else settings_fields
                    )
                    target = self._get_or_create_shadow(
                        {k: v for k, v in kwargs.items() if k in consumed}
                    )
                    remaining = {k: v for k, v in kwargs.items() if k not in consumed}
                    return method(target, *w_args, **remaining)
                return method(self, *w_args, **kwargs)

            return wrapper

        # @shadow_dispatch  (no parentheses)
        if len(args) == 1 and callable(args[0]):
            return _build(args[0], dispatch_fields=None)

        # @shadow_dispatch("alpha", "beta")  or  @shadow_dispatch()
        dispatch_fields = frozenset(args) if args else None
        return lambda method: _build(method, dispatch_fields)

    # -------------------------------------------------------------------------
    # Config Serialization
    # -------------------------------------------------------------------------

    def to_config(self) -> dict[str, Any]:
        """
        Export as reconstructable config dict.

        Returns:
            ``{"type": "name", "settings": {...}}`` if Registrable,
            ``{"settings": {...}}`` otherwise.
        """
        config = {}
        if hasattr(self, "_REGISTER_NAME"):
            config["type"] = self.get_registration_name()
        if self._settings is not None:
            config["settings"] = self._settings.model_dump(mode="json")
        return config

    @classmethod
    def from_config(cls, config: dict[str, Any], **kwargs: Any) -> SettingsMixin:
        """
        Reconstruct from config dict.

        Args:
            config: ``{"type": "name", "settings": {...}}``
            **kwargs: Additional arguments passed to the constructor.
        """
        config = config.copy()
        type_name = config.pop("type", None)
        settings_dict = config.pop("settings", {})

        target_cls = cls
        if type_name is not None:
            if not hasattr(cls, "_REGISTER_NAME"):
                raise ValueError(f"{cls.__name__} is not Registrable")
            target_cls = cls.get_registered(type_name)  # pylint: disable=no-member

        return (
            target_cls(settings=settings_dict, **kwargs)
            if settings_dict
            else target_cls(**kwargs)
        )

    def save_config(self, path: str | Path) -> dict[str, Any]:
        """Persist the current configuration to disk."""
        config = self.to_config()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return config

    # -------------------------------------------------------------------------
    # Fingerprint / repr
    # -------------------------------------------------------------------------

    def __fingerprint__(self) -> str:
        """Return serialized settings for fingerprinting."""
        return _serialize(self._settings)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(settings={self._settings!r})"


# -------------------------------------------------------------------------
# CachableSettings: SettingsMixin + Cachable
# -------------------------------------------------------------------------


class CachableSettings(SettingsMixin, Cachable):
    """
    Settings management + LRU caching mixin.

    Combines :class:`SettingsMixin` (settings, shadow views, serialisation)
    with :class:`Cachable` (LRU cache, :meth:`~Cachable.cached_method`,
    :attr:`~Cachable.cached_property`).

    Example::

        @settings_dataclass
        class MySettings:
            param: int = 10

        class MyClass(CachableSettings):
            SETTINGS_CLASS = MySettings

            @Cachable.cached_property
            def result(self):
                return expensive_computation()
    """

    def __init__(self, settings: Any = None) -> None:
        SettingsMixin.__init__(self, settings)
        Cachable.__init__(self)  # initialises _cache and _lock

    def update_settings(self, settings: Any = None, **kwargs: Any) -> CachableSettings:
        """Update settings, clear shadow cache AND computation cache."""
        with self._lock:
            super().update_settings(settings, **kwargs)
            self.clear_cache()
        return self

    def _get_or_create_shadow(self, overrides: dict[str, Any]) -> CachableSettings:
        """Shadow view also gets its own computation cache."""
        shadow = super()._get_or_create_shadow(overrides)
        # Newly created shadows share the parent's _cache reference; give them
        # their own.  LRU-retrieved shadows already have a separate _cache.
        if (
            shadow is not self and shadow._cache is self._cache
        ):  # pylint: disable=protected-access
            shadow._cache = OrderedDict()  # pylint: disable=protected-access
            shadow._lock = _LazyRLock()  # pylint: disable=protected-access
        return shadow
