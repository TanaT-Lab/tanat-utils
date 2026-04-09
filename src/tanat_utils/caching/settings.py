#!/usr/bin/env python3
"""
settings_dataclass decorator and CachableSettings mixin.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import warnings
from collections import OrderedDict
from inspect import signature
from pathlib import Path
from typing import Any, Callable, Iterable

from pydantic import ConfigDict, TypeAdapter
from pydantic.dataclasses import dataclass as pydantic_dataclass

from .cachable import Cachable, _LazyRLock, _make_hashable
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
            """
            Dump the settings to a dictionary using Pydantic serialization.
            Mimics BaseModel.model_dump().

            Args:
                mode: 'python' (dict of objects) or 'json' (dict of serializable types)
                **dump_kwargs: Additional arguments passed to TypeAdapter.dump_python
            """
            return _adapter.dump_python(self, mode=mode, **dump_kwargs)

        decorated.__init__ = new_init
        decorated.model_dump = model_dump
        return decorated

    # Handle @settings_dataclass without parentheses
    if cls is not None:
        return decorator(cls)

    return decorator


# -------------------------------------------------------------------------
# CachableSettings Mixin
# -------------------------------------------------------------------------


class CachableSettings(Cachable):
    """
    Cache + settings synchronization mixin.

    Adds settings management (fingerprint-based cache invalidation,
    shadow views for temporary overrides) on top of :class:`Cachable`.

    Example::

        @settings_dataclass
        class MySettings:
            param: int = 10

        class MyClass(CachableSettings):
            SETTINGS_CLASS = MySettings

            @CachableSettings.cached_property
            def result(self):
                return expensive_computation()
    """

    SETTINGS_CLASS = None
    SHADOW_CACHE_SIZE = 8

    def __init__(self, settings: Any = None) -> None:
        """
        Initialize with settings.

        Args:
            settings: Settings instance, dict, or None (uses defaults if SETTINGS_CLASS defined)
        """
        super().__init__()  # initializes _cache and _lock
        self._settings = self._validate_settings(settings)
        self._fingerprint = (
            fingerprint(self._settings) if self._settings is not None else None
        )
        self._shadow_cache = OrderedDict()  # LRU cache for shadows

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

    def update_settings(self, settings: Any = None, **kwargs: Any) -> CachableSettings:
        """
        Update settings and clear cache.

        Accepts either:
        - A settings dataclass instance
        - A dict of field values
        - Keyword arguments for field values

        The cache is cleared because cached values may depend on old settings.

        Args:
            settings: Settings instance or dict (optional)
            **kwargs: Field values to update

        Returns:
            self (for method chaining)

        Example:
            processor.update_settings(param=10)
            processor.update_settings({"param": 10})
            processor.update_settings(MySettings(param=10))
        """
        if self.SETTINGS_CLASS is None:
            raise ValueError("Cannot update settings: SETTINGS_CLASS is None")

        with self._lock:
            if settings is not None:
                if isinstance(settings, dict):
                    # Dict: merge with kwargs
                    kwargs = {**settings, **kwargs}
                # pylint: disable=isinstance-second-argument-not-valid-type
                elif isinstance(settings, self.SETTINGS_CLASS):
                    # Dataclass instance: use directly if no kwargs
                    if not kwargs:
                        self._settings = settings
                        self._fingerprint = fingerprint(self._settings)
                        self._cache.clear()
                        self._shadow_cache.clear()
                        return self
                    # Otherwise extract fields and merge with kwargs
                    kwargs = {**dataclasses.asdict(settings), **kwargs}
                else:
                    raise TypeError(
                        f"settings must be {self.SETTINGS_CLASS.__name__} or dict, "
                        f"got {type(settings).__name__}"
                    )

            # Apply updates via dataclasses.replace
            self._settings = dataclasses.replace(self._settings, **kwargs)
            self._fingerprint = fingerprint(self._settings)
            self._cache.clear()
            self._shadow_cache.clear()

        return self

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

        # Add type if Registrable (duck-typing via _REGISTER_NAME)
        if hasattr(self, "_REGISTER_NAME"):
            config["type"] = self.get_registration_name()

        # Add settings
        if self._settings is not None:
            # Use Pydantic serialization (handles nested Registrable)
            # Try to use .model_dump() injected by @settings_dataclass
            config["settings"] = self._settings.model_dump(mode="json")

        return config

    @classmethod
    def from_config(cls, config: dict[str, Any], **kwargs: Any) -> CachableSettings:
        """
        Reconstruct from config dict.

        Args:
            config: ``{"type": "name", "settings": {...}}``
            **kwargs: Additional arguments passed to the constructor.
        """
        config = config.copy()
        type_name = config.pop("type", None)
        settings_dict = config.pop("settings", {})

        # Resolve class (duck-typing via _REGISTER_NAME)
        target_cls = cls
        if type_name is not None:
            if not hasattr(cls, "_REGISTER_NAME"):
                raise ValueError(f"{cls.__name__} is not Registrable")
            target_cls = cls.get_registered(type_name)  # pylint: disable=no-member

        # Build instance
        return (
            target_cls(settings=settings_dict, **kwargs)
            if settings_dict
            else target_cls(**kwargs)
        )

    def save_config(self, path: str | Path) -> dict[str, Any]:
        """Persists the current configuration to disk."""
        config = self.to_config()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return config

    # -------------------------------------------------------------------------
    # Shadow Views (Internal)
    # -------------------------------------------------------------------------

    def _get_or_create_shadow(self, overrides: dict[str, Any]) -> CachableSettings:
        """Get existing shadow from LRU cache or create new one."""
        new_settings = dataclasses.replace(self._settings, **overrides)
        new_fp = fingerprint(new_settings)

        # Check LRU cache
        if new_fp in self._shadow_cache:
            self._shadow_cache.move_to_end(new_fp)  # Mark as recently used
            return self._shadow_cache[new_fp]

        # Create new shadow
        shadow = object.__new__(self.__class__)
        shadow.__dict__.update(self.__dict__)
        # pylint: disable=protected-access
        shadow._settings = new_settings
        shadow._fingerprint = new_fp
        shadow._cache = OrderedDict()
        shadow._shadow_cache = OrderedDict()
        shadow._lock = _LazyRLock()

        # Add to LRU cache, evict oldest if full
        self._shadow_cache[new_fp] = shadow
        if len(self._shadow_cache) > self.SHADOW_CACHE_SIZE:
            self._shadow_cache.popitem(last=False)

        return shadow

    # -------------------------------------------------------------------------
    # Decorators
    # -------------------------------------------------------------------------

    @staticmethod
    def cached_method(
        *,
        ignore: Iterable[str] | None = None,
        shadow_on: Iterable[str] | None = None,
    ) -> Callable[..., Any]:
        """
        Decorator for cached methods.

        Args:
            ignore: Iterable of argument names to exclude from cache key.
            shadow_on: Iterable of argument names that trigger shadow views.
                       Use ``"**kwargs"`` to auto-shadow any kwarg matching a settings field.
                       Args in shadow_on are automatically excluded from the cache key.

        Example::

            @CachableSettings.cached_method(ignore=["verbose"], shadow_on=["**kwargs"])
            def compute(self, x, verbose=False, **kwargs):
                # x is in cache key, verbose is ignored, kwargs trigger shadow
                return x * self.settings.n_iterations
        """
        ignore_set = set(ignore or [])
        shadow_set = set(shadow_on or [])

        def decorator(method):
            method_sig = signature(method)

            @functools.wraps(method)
            def wrapper(self, *args, **kwargs):
                # Bind arguments (before defaults) to detect explicit args
                bound = method_sig.bind(self, *args, **kwargs)
                explicit_args = set(bound.arguments.keys()) - {"self"}

                # Also include keys from **kwargs if present
                explicit_kwargs = set()
                if "kwargs" in bound.arguments:
                    explicit_kwargs = set(bound.arguments["kwargs"].keys())

                bound.apply_defaults()

                settings_overrides = {}
                shadow_args_used = set()

                if shadow_on:
                    # pylint: disable=protected-access
                    settings_fields = set(self._settings.__dataclass_fields__.keys())

                    if "**kwargs" in shadow_set:
                        # Any explicit kwarg matching a settings field triggers shadow
                        shadow_args_used = explicit_kwargs & settings_fields
                    else:
                        # Only listed args trigger shadow (if they match settings)
                        all_explicit = explicit_args | explicit_kwargs
                        shadow_args_used = shadow_set & all_explicit & settings_fields

                    for field in shadow_args_used:
                        # Get value from kwargs dict or bound.arguments
                        if (
                            "kwargs" in bound.arguments
                            and field in bound.arguments["kwargs"]
                        ):
                            settings_overrides[field] = bound.arguments["kwargs"][field]
                        elif field in bound.arguments:
                            settings_overrides[field] = bound.arguments[field]

                target = (
                    # pylint: disable=protected-access
                    self._get_or_create_shadow(settings_overrides)
                    if settings_overrides
                    else self
                )

                # Build cache key: all args except self, ignored, and shadow args
                excluded = ignore_set | shadow_args_used | {"self", "kwargs"}
                cache_args = {}
                for k, v in bound.arguments.items():
                    if k == "kwargs":
                        # Flatten **kwargs into cache_args (excluding shadow args)
                        for kk, vv in v.items():
                            if kk not in excluded and kk not in shadow_args_used:
                                cache_args[kk] = vv
                    elif k not in excluded:
                        cache_args[k] = v

                key_values = tuple(
                    sorted((k, _make_hashable(v)) for k, v in cache_args.items())
                )
                cache_key = f"__method__{method.__name__}__{hash(key_values)}"

                # pylint: disable=protected-access
                with target._lock:
                    # Check cache (with LRU update)
                    if cache_key in target._cache:
                        target._cache.move_to_end(cache_key)
                        return target._cache[cache_key]

                    # Compute and cache (with LRU eviction)
                    value = method(target, *args, **kwargs)
                    target._cache[cache_key] = value
                    while len(target._cache) > target.CACHE_SIZE:
                        target._cache.popitem(last=False)
                    return value

            return wrapper

        return decorator

    def __fingerprint__(self) -> str:
        """Return serialized settings for fingerprinting."""
        return _serialize(self._settings)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(settings={self._settings!r})"
