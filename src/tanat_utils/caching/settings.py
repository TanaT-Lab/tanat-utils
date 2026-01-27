#!/usr/bin/env python3
"""
Settings dataclass decorator with Pydantic validation.
"""

import logging

from pydantic.dataclasses import dataclass as pydantic_dataclass
from pydantic import ConfigDict

LOGGER = logging.getLogger(__name__)

DEFAULT_CONFIG = ConfigDict(frozen=True)


def settings_dataclass(cls=None, *, config=None):
    """
    Decorator for settings dataclasses.

    Combines:
    - Pydantic dataclass validation
    - Frozen (immutable) instances by default
    - Warning on extra fields (instead of silent ignore)

    Args:
        cls: Class to decorate (auto-filled when used without parentheses)
        config: Custom Pydantic ConfigDict (default: frozen=True)

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
        decorated = pydantic_dataclass(config=config)(cls)

        original_init = decorated.__init__
        field_names = set(decorated.__pydantic_fields__.keys())

        def new_init(self, **kwargs):
            extra = set(kwargs.keys()) - field_names
            if extra:
                LOGGER.warning("%s: Unknown fields ignored: %s", cls.__name__, extra)
            filtered = {k: v for k, v in kwargs.items() if k in field_names}
            original_init(self, **filtered)

        decorated.__init__ = new_init
        return decorated

    # Handle @settings_dataclass without parentheses
    if cls is not None:
        return decorator(cls)

    return decorator
