#!/usr/bin/env python3
"""
Cachable mixin: cache infrastructure without settings management.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections import OrderedDict
from inspect import signature
from typing import Any, Callable, Iterable

LOGGER = logging.getLogger(__name__)


def _make_hashable(val: Any) -> Any:
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

    def __init__(self) -> None:
        self._lock: threading.RLock | None = None

    def _get_lock(self) -> threading.RLock:
        # Local var avoids repeated attribute lookup
        lock = self._lock
        if lock is None:
            self._lock = lock = threading.RLock()
        return lock

    def __enter__(self) -> Any:
        return self._get_lock().__enter__()

    def __exit__(self, *args: Any) -> bool | None:
        return self._get_lock().__exit__(*args)

    def __getstate__(self) -> dict[str, None]:
        return {}

    def __setstate__(self, state: dict[str, None]) -> None:
        self._lock = None


class Cachable:
    """
    Thread-safe LRU cache mixin.

    Provides ``cached_property`` and ``cached_method`` decorators backed by
    an :class:`~collections.OrderedDict` with configurable ``CACHE_SIZE``.
    Pickle-safe: the lock is lazily recreated after deserialization.

    Example::

        class MyClass(Cachable):

            @Cachable.cached_property
            def result(self):
                return expensive_computation()

            @Cachable.cached_method(ignore=["verbose"])
            def compute(self, x, verbose=False):
                return x * 2
    """

    CACHE_SIZE = 32

    def __init__(self) -> None:
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = _LazyRLock()

    def clear_cache(self) -> None:
        """Clear all cached values."""
        with self._lock:
            self._cache.clear()

    @staticmethod
    def cached_property(method: Callable[..., Any]) -> property:
        """
        Decorator for cached properties with double-check locking.

        Thread-safe: only one thread computes, others wait and get cached result.

        Example::

            @Cachable.cached_property
            def expensive(self):
                return heavy_computation()
        """
        key = f"__prop__{method.__name__}"

        @property
        @functools.wraps(method)
        def wrapper(self):
            # pylint: disable=protected-access
            with self._lock:
                if key in self._cache:
                    self._cache.move_to_end(key)
                    return self._cache[key]
                value = method(self)
                self._cache[key] = value
                while len(self._cache) > self.CACHE_SIZE:
                    self._cache.popitem(last=False)
                return value

        return wrapper

    @staticmethod
    def cached_method(*, ignore: Iterable[str] | None = None) -> Callable[..., Any]:
        """
        Decorator for cached methods (``ignore`` only, no shadow support).

        Args:
            ignore: Iterable of argument names to exclude from the cache key.

        Example::

            @Cachable.cached_method(ignore=["verbose"])
            def compute(self, x, verbose=False):
                return x * 2
        """
        ignore_set = set(ignore or [])

        def decorator(method):
            method_sig = signature(method)

            @functools.wraps(method)
            def wrapper(self, *args, **kwargs):
                bound = method_sig.bind(self, *args, **kwargs)
                bound.apply_defaults()
                excluded = ignore_set | {"self", "kwargs"}
                cache_args = {}
                for k, v in bound.arguments.items():
                    if k == "kwargs":
                        for kk, vv in v.items():
                            if kk not in excluded:
                                cache_args[kk] = vv
                    elif k not in excluded:
                        cache_args[k] = v

                key_values = tuple(
                    sorted((k, _make_hashable(v)) for k, v in cache_args.items())
                )
                cache_key = f"__method__{method.__name__}__{hash(key_values)}"

                # pylint: disable=protected-access
                with self._lock:
                    if cache_key in self._cache:
                        self._cache.move_to_end(cache_key)
                        return self._cache[cache_key]
                    value = method(self, *args, **kwargs)
                    self._cache[cache_key] = value
                    while len(self._cache) > self.CACHE_SIZE:
                        self._cache.popitem(last=False)
                    return value

            return wrapper

        return decorator

    def __getstate__(self) -> dict[str, Any]:
        """Pickle support - exclude lock."""
        state = self.__dict__.copy()
        state["_lock"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Unpickle support - recreate lock."""
        self.__dict__.update(state)
        self._lock = _LazyRLock()
