#!/usr/bin/env python3
"""
Fingerprint generation for cache integrity.
"""

import dataclasses
import hashlib
from typing import Any


def fingerprint(obj: Any) -> str:
    """
    Generate a unique fingerprint (hash) for an object.

    Recursively handles:
    - Dataclasses (including nested)
    - Dicts, lists, tuples, sets
    - Primitives (str, int, float, bool, None)
    - Objects with __fingerprint__ method
    - Objects with settings attribute (CachableSettings)

    Args:
        obj: Object to fingerprint

    Returns:
        Hex digest of the object's state
    """
    return hashlib.md5(_serialize(obj).encode(), usedforsecurity=False).hexdigest()


def _serialize(obj: Any) -> str:
    """Serialize object to a stable string representation."""
    # Custom fingerprint method
    if hasattr(obj, "__fingerprint__"):
        return obj.__fingerprint__()

    # Dataclass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        items = []
        for field in dataclasses.fields(obj):
            value = getattr(obj, field.name)
            items.append(f"{field.name}={_serialize(value)}")
        return f"{obj.__class__.__name__}({','.join(items)})"

    # Dict
    if isinstance(obj, dict):
        items = sorted(f"{_serialize(k)}:{_serialize(v)}" for k, v in obj.items())
        return "{" + ",".join(items) + "}"

    # List/Tuple
    if isinstance(obj, (list, tuple)):
        items = [_serialize(v) for v in obj]
        bracket = "[]" if isinstance(obj, list) else "()"
        return bracket[0] + ",".join(items) + bracket[1]

    # Set/Frozenset
    if isinstance(obj, (set, frozenset)):
        items = sorted(_serialize(v) for v in obj)
        return "{" + ",".join(items) + "}"

    # Primitives
    if obj is None:
        return "None"
    if isinstance(obj, bool):
        return str(obj)
    if isinstance(obj, (int, float, str)):
        return repr(obj)

    # Fallback: use repr
    return repr(obj)
