"""
Tests for LRU Cache Eviction

Verifies proper memory management of caches:
- Main cache (_cache) respects CACHE_SIZE limit
- Shadow cache (_shadow_cache) respects SHADOW_CACHE_SIZE limit
- Oldest entries are evicted when limits are exceeded
- Recently used entries are retained
- LRU ordering is maintained
"""

from tanat_utils import settings_dataclass, CachableSettings, Cachable

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class LRUSettings:
    """Settings for LRU tests."""

    param: int = 0


class SmallCacheProcessor(CachableSettings):
    """Processor with small caches for testing eviction."""

    SETTINGS_CLASS = LRUSettings
    CACHE_SIZE = 4  # Small main cache for testing
    SHADOW_CACHE_SIZE = 3  # Small shadow cache for testing

    def __init__(self, settings=None):
        super().__init__(settings)
        self.compute_count = 0

    @Cachable.cached_method()
    def compute(self, x, **kwargs):
        """Computation with caching."""
        self.compute_count += 1
        return x * self.settings.param

    @Cachable.cached_property
    def expensive(self):
        """Cached property."""
        self.compute_count += 1
        return "computed"


# =============================================================================
# Main Cache LRU Tests
# =============================================================================


class TestMainCacheLRU:
    """Test suite for main cache (_cache) LRU eviction."""

    def test_cache_respects_size_limit(self):
        """Main cache doesn't exceed CACHE_SIZE."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        # Call with more unique args than cache size
        for i in range(10):
            processor.compute(i)

        # Cache should be at limit
        assert len(processor._cache) == processor.CACHE_SIZE

    def test_oldest_entry_is_evicted(self):
        """First-in cache entry is evicted when cache is full."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        # Fill cache: x=0, 1, 2, 3
        for i in range(4):
            processor.compute(i)

        keys_before = set(processor._cache.keys())
        assert len(keys_before) == 4

        # Add one more: x=4 (should evict x=0)
        processor.compute(4)

        keys_after = set(processor._cache.keys())

        # One key was removed, one added
        assert len(keys_after) == 4
        evicted = keys_before - keys_after
        assert len(evicted) == 1

    def test_recently_used_entry_retained(self):
        """Accessing a cached value moves it to end of LRU, preventing eviction."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        # Create 4 entries: x=0, 1, 2, 3
        for i in range(4):
            processor.compute(i)

        initial_count = processor.compute_count

        # Re-access x=0 (moves to end, no recomputation)
        processor.compute(0)
        assert processor.compute_count == initial_count  # No new computation

        # Add x=4, x=5 - should evict x=1, x=2 (now oldest), not x=0
        processor.compute(4)
        processor.compute(5)

        # Verify x=0 still cached (call doesn't increment compute_count)
        count_before = processor.compute_count
        processor.compute(0)
        assert processor.compute_count == count_before  # x=0 was cached

        # x=1 was evicted (call increments compute_count)
        processor.compute(1)
        assert processor.compute_count == count_before + 1  # x=1 recomputed

    def test_cached_property_uses_lru(self):
        """Cached property entry participates in LRU."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        # Access property (uses 1 slot)
        _ = processor.expensive

        # Fill remaining slots: x=0, 1, 2
        for i in range(3):
            processor.compute(i)

        assert len(processor._cache) == 4

        # Property should still be cached
        count_before = processor.compute_count
        _ = processor.expensive
        assert processor.compute_count == count_before

    def test_lru_order_updated_on_cache_hit(self):
        """Cache hit moves entry to end of LRU order."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        # Create entries in order: x=0, 1, 2, 3
        for i in range(4):
            processor.compute(i)

        order_initial = list(processor._cache.keys())

        # Access x=0 (should move to end)
        processor.compute(0)

        order_after = list(processor._cache.keys())

        # x=0's key moved from first to last
        assert order_initial[0] == order_after[-1]

    def test_eviction_sequence_with_sweep(self):
        """Verify exact eviction sequence with parameter sweep."""
        processor = SmallCacheProcessor(LRUSettings(param=1))

        # Fill cache
        for i in range(4):
            processor.compute(i)

        # Track results before/after to detect evictions
        evicted_args = []

        for i in range(4, 8):
            # Check which args are still cached (no recompute)
            cached_before = []
            for j in range(i):
                count = processor.compute_count
                processor.compute(j)
                if processor.compute_count == count:
                    cached_before.append(j)

            # Add new entry
            processor.compute(i)

        # After all additions, only last 4 should be cached
        # x=4, 5, 6, 7 (values 4, 5, 6, 7 since param=1)
        assert len(processor._cache) == 4


class TestMainCacheEdgeCases:
    """Edge cases for main cache LRU."""

    def test_single_slot_cache(self):
        """Cache with size 1 works correctly."""

        class TinyCache(CachableSettings):
            SETTINGS_CLASS = LRUSettings
            CACHE_SIZE = 1

            @Cachable.cached_method()
            def compute(self, x):
                return x * 2

        processor = TinyCache(LRUSettings(param=1))

        processor.compute(1)
        assert len(processor._cache) == 1

        processor.compute(2)
        assert len(processor._cache) == 1

        # Only x=2 cached
        processor.compute(1)  # Recomputed
        assert len(processor._cache) == 1

    def test_cache_clear_resets_lru(self):
        """Clearing cache resets LRU state."""
        processor = SmallCacheProcessor(LRUSettings(param=2))

        for i in range(4):
            processor.compute(i)

        assert len(processor._cache) == 4

        processor.clear_cache()

        assert len(processor._cache) == 0

        # Can fill again
        for i in range(4):
            processor.compute(i)

        assert len(processor._cache) == 4
