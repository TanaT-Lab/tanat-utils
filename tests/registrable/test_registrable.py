#!/usr/bin/env python3
"""
Tests for Registrable mixin - basic registration functionality.
"""

import pytest

from tanat_utils.registrable import Registrable
from tanat_utils.registrable.exceptions import (
    UnregisteredTypeError,
    InvalidRegistrationNameError,
)

# =============================================================================
# Fixtures
# =============================================================================


class BaseMetric(Registrable):
    """Base class for registrable metrics."""

    _REGISTER = {}


class EuclideanMetric(BaseMetric, register_name="euclidean"):
    """Euclidean distance metric."""


class ManhattanMetric(BaseMetric, register_name="manhattan"):
    """Manhattan distance metric."""


# =============================================================================
# Registration Tests
# =============================================================================


class TestAutoRegistration:
    """Test automatic registration via __init_subclass__."""

    def test_subclass_registered_automatically(self):
        """Subclasses with register_name are registered automatically."""
        assert "euclidean" in BaseMetric.list_registered()
        assert "manhattan" in BaseMetric.list_registered()

    def test_get_registered_returns_class(self):
        """get_registered returns the correct class."""
        assert BaseMetric.get_registered("euclidean") is EuclideanMetric
        assert BaseMetric.get_registered("manhattan") is ManhattanMetric


class TestCaseInsensitive:
    """Test case-insensitive registration and lookup."""

    def test_get_registered_case_insensitive(self):
        """Lookup is case-insensitive."""
        assert BaseMetric.get_registered("EUCLIDEAN") is EuclideanMetric
        assert BaseMetric.get_registered("Euclidean") is EuclideanMetric
        assert BaseMetric.get_registered("eUcLiDeAn") is EuclideanMetric

    def test_registration_name_normalized(self):
        """Registration names are normalized to lowercase."""
        assert "euclidean" in BaseMetric.list_registered()
        assert "EUCLIDEAN" not in BaseMetric.list_registered()


class TestManualRegistration:
    """Test explicit registration via register() method."""

    def test_manual_registration(self):
        """Classes can be registered manually."""

        class CustomMetric(BaseMetric):
            pass

        CustomMetric.register(register_name="custom")
        assert BaseMetric.get_registered("custom") is CustomMetric

    def test_re_registration_replaces(self):
        """Re-registering a name replaces the previous class."""

        class NewEuclidean(BaseMetric):
            pass

        NewEuclidean.register(register_name="euclidean")
        assert BaseMetric.get_registered("euclidean") is NewEuclidean

        # Restore original
        EuclideanMetric.register(register_name="euclidean")


class TestGetRegistrationName:
    """Test get_registration_name method."""

    def test_get_registration_name_from_class(self):
        """Can get registration name from class."""
        assert EuclideanMetric.get_registration_name() == "euclidean"

    def test_get_registration_name_from_instance(self):
        """Can get registration name from instance."""
        instance = EuclideanMetric()
        assert instance.get_registration_name() == "euclidean"

    def test_unregistered_class_returns_none(self):
        """Unregistered class returns None."""

        class UnregisteredMetric(BaseMetric):
            pass

        assert UnregisteredMetric.get_registration_name() is None


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestUnregisteredErrors:
    """Test error handling for unregistered types."""

    def test_unregistered_raises_error(self):
        """Requesting unregistered name raises UnregisteredTypeError."""
        with pytest.raises(UnregisteredTypeError):
            BaseMetric.get_registered("nonexistent", retry_with_reload=False)

    def test_close_match_suggestion(self):
        """Error message suggests close matches."""
        with pytest.raises(UnregisteredTypeError, match="Did you mean"):
            BaseMetric.get_registered("euclidien", retry_with_reload=False)

    def test_empty_name_raises_error(self):
        """Empty registration name raises InvalidRegistrationNameError."""
        with pytest.raises(InvalidRegistrationNameError):
            BaseMetric.validate_registration_name("")


# =============================================================================
# Registry Management Tests
# =============================================================================


class TestRegistryManagement:
    """Test registry clearing and listing."""

    def test_list_registered_sorted(self):
        """list_registered returns sorted list."""
        names = BaseMetric.list_registered()
        assert names == sorted(names)

    def test_clear_registered(self):
        """clear_registered removes all entries."""

        # Create isolated registry for this test
        class IsolatedBase(Registrable):
            _REGISTER = {}

        class IsolatedChild(IsolatedBase, register_name="child"):
            pass

        assert len(IsolatedBase.list_registered()) == 1
        IsolatedBase.clear_registered()
        assert len(IsolatedBase.list_registered()) == 0
