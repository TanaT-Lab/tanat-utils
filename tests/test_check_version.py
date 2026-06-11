#!/usr/bin/env python3
"""
Tests for the version checking functionality.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import urllib

from tanat_utils.check_version import check_latest_version


def _mock_response(latest: str):
    """
    Creates a mock response object for urllib.request.urlopen that simulates a JSON response from PyPI.
    """
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps({"info": {"version": latest}}).encode()
    return mock


def test_warns_when_outdated():
    """
    Tests that a warning is issued when the installed version is outdated.
    """
    with patch("tanat_utils.check_version.version", return_value="0.1.0"):
        with patch("urllib.request.urlopen", return_value=_mock_response("0.2.0")):
            with pytest.warns(UserWarning, match="0.2.0"):
                check_latest_version("tanat-utils")


def test_no_warning_when_up_to_date(recwarn):
    """
    Tests that no warning is issued when the installed version is up to date.
    """
    with patch("tanat_utils.check_version.version", return_value="0.1.0"):
        with patch("urllib.request.urlopen", return_value=_mock_response("0.1.0")):
            check_latest_version("tanat-utils")
    assert len(recwarn) == 0


def test_silent_on_network_error(recwarn):
    """
    Tests that no warning is issued when there is a network error while checking for the latest version.
    """
    with patch("tanat_utils.check_version.version", return_value="0.1.0"):
        with patch(
            "urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")
        ):
            check_latest_version("tanat-utils")
    assert len(recwarn) == 0
