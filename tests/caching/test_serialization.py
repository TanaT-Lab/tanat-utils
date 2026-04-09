"""
Tests for Serialization Resilience - "The Pickle-Trip"

Verifies that CachableSettings survives serialization:
- Cache is preserved through pickle round-trip
- _LazyRLock reinstantiates properly
- Cached methods work after deserialization
- Shadow views handle serialization correctly
"""

import pickle
import time

from tanat_utils import settings_dataclass, Cachable, CachableSettings, SettingsMixin

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class SerializationSettings:
    """Settings for serialization tests."""

    factor: int = 5
    name: str = "test"


class SerializableProcessor(CachableSettings):
    """Processor designed for serialization tests."""

    SETTINGS_CLASS = SerializationSettings

    def __init__(self, settings=None):
        super().__init__(settings)
        self.compute_count = 0

    @Cachable.cached_property
    def cached_value(self):
        """Cached property that tracks computation."""
        self.compute_count += 1
        time.sleep(0.05)
        return f"value_{self.settings.factor}"

    @Cachable.cached_method()
    def compute(self, x):
        """Cached method that tracks computation."""
        self.compute_count += 1
        time.sleep(0.05)
        return x * self.settings.factor

    @SettingsMixin.shadow_dispatch
    def compute_with_shadow(self, x, **kwargs):
        """Cached method with shadow support."""
        self.compute_count += 1
        return x * self.settings.factor


# =============================================================================
# Serialization Tests
# =============================================================================


class TestPickleRoundTrip:
    """Test suite for pickle serialization."""

    def test_basic_pickle_roundtrip(self):
        """Object survives basic pickle round-trip."""
        original = SerializableProcessor(SerializationSettings(factor=10))

        # Populate cache
        _ = original.cached_value
        _ = original.compute(5)

        # Pickle round-trip
        pickled = pickle.dumps(original)
        restored = pickle.loads(pickled)

        # Settings preserved
        assert restored.settings.factor == 10
        assert restored.settings.name == "test"

        # Fingerprint preserved
        assert restored.cache_fingerprint == original.cache_fingerprint

    def test_cache_preserved_after_pickle(self):
        """Cache contents survive pickle round-trip."""
        original = SerializableProcessor()

        # Populate cache
        value1 = original.cached_value
        value2 = original.compute(42)
        original_count = original.compute_count

        # Pickle round-trip
        restored = pickle.loads(pickle.dumps(original))

        # Cache should be preserved
        assert len(restored._cache) == len(original._cache)

        # Accessing cached values should NOT increment compute_count
        assert restored.cached_value == value1
        assert restored.compute(42) == value2

        # compute_count was pickled too
        assert restored.compute_count == original_count

    def test_lock_reinstantiates_after_pickle(self):
        """_LazyRLock properly reinstantiates after deserialization."""
        original = SerializableProcessor()
        _ = original.cached_value  # Trigger lock creation

        # Pickle round-trip
        restored = pickle.loads(pickle.dumps(original))

        # Lock should be a fresh _LazyRLock (internal _lock is None until used)
        assert restored._lock is not None
        assert restored._lock._lock is None  # Lazy, not yet initialized

        # Using the lock should work
        with restored._lock:
            pass  # Should not raise

        # Now internal lock exists
        assert restored._lock._lock is not None

    def test_cached_methods_work_after_pickle(self):
        """Cached methods function correctly after deserialization."""
        original = SerializableProcessor(SerializationSettings(factor=7))

        # Pickle without populating cache
        restored = pickle.loads(pickle.dumps(original))

        # Should be able to compute and cache
        result = restored.compute(10)
        assert result == 70  # 10 * 7

        # Second call should hit cache
        restored.compute_count = 0
        result2 = restored.compute(10)
        assert result2 == 70
        assert restored.compute_count == 0  # Cache hit

    def test_shadow_cache_survives_pickle(self):
        """Shadow cache state after pickle (documents current behavior)."""
        original = SerializableProcessor()

        # Create shadows
        original.compute_with_shadow(5, factor=20)
        original.compute_with_shadow(5, factor=30)
        shadow_count_before = len(original._shadow_cache)

        # Pickle round-trip
        restored = pickle.loads(pickle.dumps(original))

        # Document actual behavior: shadow_cache is preserved or not
        # The current implementation preserves shadow_cache through pickle
        assert len(restored._shadow_cache) == shadow_count_before


class TestMultiprocessingCompatibility:
    """Tests for multiprocessing-style serialization patterns."""

    def test_multiple_pickle_roundtrips(self):
        """Object survives multiple consecutive pickle round-trips."""
        obj = SerializableProcessor()
        _ = obj.cached_value

        for i in range(5):
            obj = pickle.loads(pickle.dumps(obj))

        # Should still work
        assert obj.cached_value == "value_5"
        assert obj.settings.factor == 5

    def test_pickle_different_protocols(self):
        """Object works with different pickle protocols."""
        original = SerializableProcessor()
        _ = original.compute(100)

        for protocol in range(pickle.HIGHEST_PROTOCOL + 1):
            pickled = pickle.dumps(original, protocol=protocol)
            restored = pickle.loads(pickled)

            assert restored.compute(100) == 500
            assert restored.cache_fingerprint == original.cache_fingerprint
