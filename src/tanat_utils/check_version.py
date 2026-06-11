#!/usr/bin/env python3
"""
Check for the latest version of a package on PyPI and warn if an update is available.
"""

import json
import urllib.error
import urllib.request
import warnings
from importlib.metadata import PackageNotFoundError, version


def _parse_version(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".")[:3])


def check_latest_version(package_name: str):
    """
    Check for the latest version of a package on PyPI and warn if an update is available.
    """
    try:
        current = version(package_name)
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{package_name}/json", timeout=0.5
        ) as r:
            latest = json.loads(r.read())["info"]["version"]
        if _parse_version(current) < _parse_version(latest):
            warnings.warn(
                f"A new release of {package_name} is available: {current} -> {latest}.\n"
                f"To silence this warning, run: pip install --upgrade {package_name}",
                UserWarning,
                stacklevel=2,
            )
    except (
        PackageNotFoundError,
        urllib.error.URLError,
        json.JSONDecodeError,
        KeyError,
        ValueError,
    ):
        pass
