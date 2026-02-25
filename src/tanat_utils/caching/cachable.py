#!/usr/bin/env python3
"""
CachableSettings mixin - Unified settings + cache synchronization.
"""

from __future__ import annotations

import json
import logging
import dataclasses
import functools
import threading
from collections import OrderedDict
from inspect import signature
from typing import TYPE_CHECKING

from .fingerprint import fingerprint, _serialize

if TYPE_CHECKING:
    from pathlib import Path


LOGGER = logging.getLogger(__name__)


def _make_hashable(val):
    """Convert nested dicts/lists to hashable tuples."""
    if isinstance(val, dict):
        return tuple(sorted((k, _make_hashable(v)) for k, v in val.items()))
    if isinstance(val, list):
        return tuple(_make_hashable(v) for v in val)
    return val


class _LazyRLock:
    """
    Thread-safe RLock that is created lazily and pickle-safe.
    """

    __slots__ = ("_lock",)

    def __init__(self):
        self._lock = None

    def _get_lock(self):
        # Local var avoids repeated attribute lookup
        lock = self._lock
        if lock is None:
            self._lock = lock = threading.RLock()
        return lock

    def __enter__(self):
        return self._get_lock().__enter__()

    def __exit__(self, *args):
        return self._get_lock().__exit__(*args)

    def __getstate__(self):
        return {}

    def __setstate__(self, state):
        self._lock = None


class CachableSettings:
    """
    Mixin that synchronizes settings with a cache.

    Features:
    - Automatic cache invalidation on settings change (via fingerprint)
    - Shadow views for temporary settings overrides
    - Thread-safe cache operations
    - Decorators for cached properties and methods

    Usage:
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
    CACHE_SIZE = 32
    SHADOW_CACHE_SIZE = 8

    def __init__(self, settings=None):
        """
        Initialize with settings.

        Args:
            settings: Settings instance, dict, or None (uses defaults if SETTINGS_CLASS defined)
        """
        self._settings = self._validate_settings(settings)
        self._fingerprint = (
            fingerprint(self._settings) if self._settings is not None else None
        )
        self._cache = OrderedDict()  # LRU cache for computed values
        self._shadow_cache = OrderedDict()  # LRU cache for shadows
        self._lock = _LazyRLock()

    def _validate_settings(self, settings):
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
    def settings(self):
        """Current settings (immutable)."""
        return self._settings

    @property
    def cache_fingerprint(self):
        """Current fingerprint for cache keying."""
        return self._fingerprint

    # -------------------------------------------------------------------------
    # Settings Management
    # -------------------------------------------------------------------------

    def update_settings(self, settings=None, **kwargs):
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
    # Cache Management
    # -------------------------------------------------------------------------

    def clear_cache(self):
        """Clear all cached values."""
        with self._lock:
            self._cache.clear()

    # -------------------------------------------------------------------------
    # Config Serialization
    # -------------------------------------------------------------------------

    def to_config(self):
        """
        Export as reconstructable config dict.

        Returns:
            {"type": "name", "settings": {...}} if Registrable
            {"settings": {...}} otherwise
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
    def from_config(cls, config, **kwargs):
        """
        Reconstruct from config dict.

        Args:
            config: {"type": "name", "settings": {...}}
            **kwargs: Additional arguments passed to the constructor
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

    def save_config(self, path: str | Path) -> dict:
        """Persists the current configuration to disk."""
        config = self.to_config()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
        return config

    # -------------------------------------------------------------------------
    # Shadow Views (Internal)
    # -------------------------------------------------------------------------

    def _get_or_create_shadow(self, overrides):
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
    def cached_property(method):
        """
        Decorator for cached properties with double-check locking.

        The result is cached per fingerprint (settings state).
        Thread-safe: only one thread computes, others wait and get cached result.

        Example:
            @CachableSettings.cached_property
            def expensive(self):
                return heavy_computation()
        """
        key = f"__prop__{method.__name__}"

        @property
        @functools.wraps(method)
        def wrapper(self):
            with self._lock:
                # Check cache (with LRU update)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]

                # Compute and cache (with LRU eviction)
                value = method(self)
                self._cache[key] = value
                while len(self._cache) > self.CACHE_SIZE:
                    self._cache.popitem(last=False)
                return value

        return wrapper

    @staticmethod
    def cached_method(*, ignore=None, shadow_on=None):
        """
        Decorator for cached methods.

        Args:
            ignore: Iterable of argument names to exclude from cache key (e.g., "verbose").
            shadow_on: Iterable of argument names that trigger shadow views.
                       Use "**kwargs" to auto-shadow any kwarg matching a settings field.
                       Args in shadow_on are automatically excluded from cache key.

        Example:
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

    # -------------------------------------------------------------------------
    # Serialization Support
    # -------------------------------------------------------------------------

    def __getstate__(self):
        """Pickle support - exclude lock."""
        state = self.__dict__.copy()
        state["_lock"] = None
        return state

    def __setstate__(self, state):
        """Unpickle support - recreate lock."""
        self.__dict__.update(state)
        self._lock = _LazyRLock()

    def __fingerprint__(self):
        """Return serialized settings for fingerprinting."""
        return _serialize(self._settings)

    def __repr__(self):
        return f"{self.__class__.__name__}(settings={self._settings!r})"
