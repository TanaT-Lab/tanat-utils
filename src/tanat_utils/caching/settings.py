#!/usr/bin/env python3
"""
Settings dataclass decorator with Pydantic validation.
"""

import logging

from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic import ConfigDict, TypeAdapter

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = ConfigDict(frozen=True, validate_default=True, kw_only=True)


def settings_dataclass(cls=None, *, config=None, **kwargs):
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

    Example:
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
        # Manage kw_only: Default to True for better error messages and immutability, but allow override
        is_kw_only = kwargs.get("kw_only", config.get("kw_only", True))
        decorated = pydantic_dataclass(config=config, **kwargs, kw_only=is_kw_only)(cls)

        # Cache the TypeAdapter for performance
        _adapter = TypeAdapter(decorated)

        original_init = decorated.__init__
        field_names = set(decorated.__pydantic_fields__.keys())

        def new_init(self, **kwargs):  # pylint: disable=unused-argument
            extra = set(kwargs.keys()) - field_names
            if extra:
                LOGGER.warning("%s: Unknown fields ignored: %s", cls.__name__, extra)
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
