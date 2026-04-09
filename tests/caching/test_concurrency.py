"""
Tests for Thread Safety and Concurrency - "Compute-Once" Validation

Verifies that the caching system guarantees single execution under concurrent access:
- @cached_method decorator alone provides thread-safety
- No manual locking needed in user code
- All threads receive the same result from single computation
"""

import time
from concurrent.futures import ThreadPoolExecutor, wait

from tanat_utils import settings_dataclass, Cachable, CachableSettings

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class SlowSettings:
    """Settings with configurable delay."""

    delay: float = 0.2


class SlowProcessor(CachableSettings):
    """Processor with slow computation - NO manual locking."""

    SETTINGS_CLASS = SlowSettings

    def __init__(self, settings=None):
        super().__init__(settings)
        self.execution_count = 0  # Simple counter, no lock

    @Cachable.cached_method()
    def compute(self, x):
        """Slow computation - counter increment is unprotected on purpose."""
        self.execution_count += 1
        time.sleep(self.settings.delay)
        return x * 2

    @Cachable.cached_property
    def expensive_value(self):
        """Slow property - counter increment is unprotected on purpose."""
        self.execution_count += 1
        time.sleep(self.settings.delay)
        return "computed"


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestComputeOnce:
    """Validates that @cached_method guarantees single execution."""

    def test_method_executes_once_under_10_concurrent_calls(self):
        """10 threads, same key → exactly 1 computation."""
        processor = SlowProcessor(SlowSettings(delay=0.3))

        start = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(processor.compute, 42) for _ in range(10)]
            wait(futures)
            results = [f.result() for f in futures]
        elapsed = time.time() - start

        # Single execution
        assert processor.execution_count == 1

        # All results identical
        assert results == [84] * 10

        # Time ~0.3s, not 3s (proves parallel wait, not sequential)
        assert elapsed < 0.6

    def test_property_executes_once_under_10_concurrent_calls(self):
        """10 threads accessing property → exactly 1 computation."""
        processor = SlowProcessor(SlowSettings(delay=0.3))

        start = time.time()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [
                executor.submit(lambda: processor.expensive_value) for _ in range(10)
            ]
            wait(futures)
            results = [f.result() for f in futures]
        elapsed = time.time() - start

        assert processor.execution_count == 1
        assert results == ["computed"] * 10
        assert elapsed < 0.6

    def test_different_keys_compute_once_each(self):
        """3 unique keys × 10 threads each → exactly 3 computations."""
        processor = SlowProcessor(SlowSettings(delay=0.1))

        start = time.time()
        with ThreadPoolExecutor(max_workers=30) as executor:
            futures = []
            for x in [1, 2, 3]:
                for _ in range(10):
                    futures.append(executor.submit(processor.compute, x))
            wait(futures)
            results = [f.result() for f in futures]
        elapsed = time.time() - start

        # 3 unique keys = 3 computations
        assert processor.execution_count == 3

        # Results correct
        assert sorted(set(results)) == [2, 4, 6]

        # Time ~0.1s (parallel), not 3s (sequential)
        assert elapsed < 0.5


class TestCacheConsistency:
    """Validates cache integrity after concurrent access."""

    def test_cache_populated_once(self):
        """Cache contains single entry after concurrent storm."""
        processor = SlowProcessor(SlowSettings(delay=0.05))

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(processor.compute, 99) for _ in range(20)]
            wait(futures)

        assert len(processor._cache) == 1
        assert processor.execution_count == 1

    def test_subsequent_reads_instant(self):
        """After initial computation, reads are instant."""
        processor = SlowProcessor(SlowSettings(delay=0.2))

        # Populate cache
        processor.compute(42)
        assert processor.execution_count == 1

        # Many fast reads
        start = time.time()
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(processor.compute, 42) for _ in range(50)]
            wait(futures)
        elapsed = time.time() - start

        # Still single execution
        assert processor.execution_count == 1

        # Reads nearly instant (< 50ms for 50 threads)
        assert elapsed < 0.05


class TestStressScenarios:
    """High-load stress tests."""

    def test_100_concurrent_calls_same_key(self):
        """100 threads → single computation."""
        processor = SlowProcessor(SlowSettings(delay=0.1))

        with ThreadPoolExecutor(max_workers=100) as executor:
            futures = [executor.submit(processor.compute, 0) for _ in range(100)]
            wait(futures)
            results = [f.result() for f in futures]

        assert processor.execution_count == 1
        assert all(r == 0 for r in results)

    def test_mixed_workload_stress(self):
        """Mixed keys under heavy load."""
        processor = SlowProcessor(SlowSettings(delay=0.02))

        with ThreadPoolExecutor(max_workers=50) as executor:
            # 10 different keys, 10 calls each
            futures = []
            for x in range(10):
                for _ in range(10):
                    futures.append(executor.submit(processor.compute, x))
            wait(futures)

        # 10 unique keys = 10 computations
        assert processor.execution_count == 10
        assert len(processor._cache) == 10
