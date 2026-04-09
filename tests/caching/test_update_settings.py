"""
Tests for update_settings Method

Verifies that settings can be updated properly:
- Accepts dataclass, dict, or kwargs
- Clears cache after update
- Updates fingerprint
- Thread-safe operation
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait

import pytest

from tanat_utils import settings_dataclass, Cachable, CachableSettings

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class UpdateSettings:
    """Settings for update tests."""

    value: int = 10
    name: str = "default"


class UpdateProcessor(CachableSettings):
    """Processor for testing update_settings."""

    SETTINGS_CLASS = UpdateSettings

    def __init__(self, settings=None):
        super().__init__(settings)
        self.compute_count = 0

    @Cachable.cached_method()
    def compute(self, x):
        self.compute_count += 1
        return x * self.settings.value


class NoSettingsProcessor(CachableSettings):
    """Processor without SETTINGS_CLASS."""

    SETTINGS_CLASS = None


# =============================================================================
# Basic Update Tests
# =============================================================================


class TestUpdateWithKwargs:
    """Test updating settings via keyword arguments."""

    def test_update_single_field(self):
        """Update a single field via kwarg."""
        processor = UpdateProcessor()
        assert processor.settings.value == 10

        processor.update_settings(value=20)

        assert processor.settings.value == 20
        assert processor.settings.name == "default"  # Unchanged

    def test_update_multiple_fields(self):
        """Update multiple fields via kwargs."""
        processor = UpdateProcessor()

        processor.update_settings(value=50, name="updated")

        assert processor.settings.value == 50
        assert processor.settings.name == "updated"

    def test_update_returns_self(self):
        """update_settings returns self for chaining."""
        processor = UpdateProcessor()

        result = processor.update_settings(value=30)

        assert result is processor


class TestUpdateWithDict:
    """Test updating settings via dict."""

    def test_update_with_dict(self):
        """Update settings via dict."""
        processor = UpdateProcessor()

        processor.update_settings({"value": 100, "name": "from_dict"})

        assert processor.settings.value == 100
        assert processor.settings.name == "from_dict"

    def test_dict_merged_with_kwargs(self):
        """Dict and kwargs are merged, kwargs take precedence."""
        processor = UpdateProcessor()

        processor.update_settings({"value": 50, "name": "dict"}, name="kwarg")

        assert processor.settings.value == 50  # From dict
        assert processor.settings.name == "kwarg"  # Kwarg overrides


class TestUpdateWithDataclass:
    """Test updating settings via dataclass instance."""

    def test_update_with_dataclass(self):
        """Update settings via dataclass instance."""
        processor = UpdateProcessor()

        new_settings = UpdateSettings(value=200, name="new")
        processor.update_settings(new_settings)

        assert processor.settings.value == 200
        assert processor.settings.name == "new"

    def test_dataclass_with_kwargs_override(self):
        """Dataclass fields can be overridden with kwargs."""
        processor = UpdateProcessor()

        processor.update_settings(UpdateSettings(value=100, name="base"), value=999)

        assert processor.settings.value == 999  # Overridden
        assert processor.settings.name == "base"  # From dataclass


# =============================================================================
# Cache Invalidation Tests
# =============================================================================


class TestCacheInvalidation:
    """Test that cache is cleared after update."""

    def test_cache_cleared_after_update(self):
        """Cache is cleared when settings are updated."""
        processor = UpdateProcessor()

        # Populate cache
        processor.compute(5)
        assert len(processor._cache) == 1
        assert processor.compute_count == 1

        # Update settings
        processor.update_settings(value=20)

        # Cache should be empty
        assert len(processor._cache) == 0

    def test_recomputation_after_update(self):
        """Computation uses new settings after update."""
        processor = UpdateProcessor()

        # Compute with value=10
        result1 = processor.compute(5)
        assert result1 == 50  # 5 * 10

        # Update to value=3
        processor.update_settings(value=3)

        # Recompute
        result2 = processor.compute(5)
        assert result2 == 15  # 5 * 3
        assert processor.compute_count == 2  # Recomputed

    def test_fingerprint_updated(self):
        """Fingerprint is updated after settings change."""
        processor = UpdateProcessor()

        fp_before = processor.cache_fingerprint

        processor.update_settings(value=999)

        fp_after = processor.cache_fingerprint

        assert fp_before != fp_after


# =============================================================================
# Edge Cases and Errors
# =============================================================================


class TestUpdateEdgeCases:
    """Edge cases and error handling."""

    def test_update_no_settings_class_raises(self):
        """Updating when SETTINGS_CLASS is None raises ValueError."""
        processor = NoSettingsProcessor()

        with pytest.raises(ValueError, match="SETTINGS_CLASS is None"):
            processor.update_settings(value=10)

    def test_update_with_wrong_type_raises(self):
        """Updating with wrong type raises TypeError."""
        processor = UpdateProcessor()

        with pytest.raises(TypeError, match="must be UpdateSettings or dict"):
            processor.update_settings("invalid")

    def test_update_with_invalid_field_ignored(self):
        """Updating with non-existent field is ignored (with warning)."""
        processor = UpdateProcessor()

        # Unknown fields are ignored by @settings_dataclass
        processor.update_settings(nonexistent_field=123)

        # Original values unchanged
        assert processor.settings.value == 10
        assert processor.settings.name == "default"

    def test_chained_updates(self):
        """Multiple chained updates work correctly."""
        processor = UpdateProcessor()

        processor.update_settings(value=1).update_settings(value=2).update_settings(
            value=3
        )

        assert processor.settings.value == 3


# =============================================================================
# Thread Safety Tests
# =============================================================================


class TestUpdateConcurrency:
    """Thread safety of update_settings."""

    def test_concurrent_updates_no_corruption(self):
        """Concurrent updates don't corrupt state."""
        processor = UpdateProcessor()

        def updater(val):
            processor.update_settings(value=val)
            time.sleep(0.01)
            return processor.settings.value

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(updater, i) for i in range(10)]
            wait(futures)

        # Final state should be valid (one of the values)
        assert processor.settings.value in range(10)

    def test_update_during_computation(self):
        """Update during computation is handled safely."""
        processor = UpdateProcessor(UpdateSettings(value=1))

        results = []

        def compute_loop():
            for _ in range(5):
                results.append(processor.compute(10))

        def update_loop():
            for i in range(5):
                time.sleep(0.001)
                processor.update_settings(value=i + 1)

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(compute_loop)
            f2 = executor.submit(update_loop)
            wait([f1, f2])

        # All results should be valid (10 * some value)
        for r in results:
            assert r % 10 == 0
