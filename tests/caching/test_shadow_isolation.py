"""
Tests for Shadow View Isolation - "The No-Leak Test"

Verifies that shadow views have perfectly isolated caches:
- Shadow A's cache doesn't pollute parent or Shadow B
- Parent's cache doesn't leak into shadows
- Shared non-settings attributes remain accessible
"""

from tanat_utils import settings_dataclass, CachableSettings

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class IsolationSettings:
    """Settings for isolation tests."""

    multiplier: int = 10


class IsolationProcessor(CachableSettings):
    """Processor with shared data and isolated cache."""

    SETTINGS_CLASS = IsolationSettings

    def __init__(self, settings=None, shared_data=None):
        super().__init__(settings)
        self.shared_data = shared_data or [1, 2, 3]  # Shared across shadows
        self.compute_count = 0

    @CachableSettings.cached_method(shadow_on=["**kwargs"])
    def compute(self, x, **kwargs):
        """Computation that uses settings.multiplier."""
        self.compute_count += 1
        return x * self.settings.multiplier


# =============================================================================
# Isolation Tests
# =============================================================================


class TestShadowIsolation:
    """Test suite for shadow view cache isolation."""

    def test_shadow_cache_is_isolated_from_parent(self):
        """Shadow view cache doesn't pollute parent cache."""
        parent = IsolationProcessor()

        # Compute on parent
        result_parent = parent.compute(5)
        assert result_parent == 50  # 5 * 10
        assert len(parent._cache) == 1

        # Compute with override (creates shadow)
        result_shadow = parent.compute(5, multiplier=20)
        assert result_shadow == 100  # 5 * 20

        # Parent cache unchanged
        assert len(parent._cache) == 1
        # Shadow exists in parent's shadow_cache
        assert len(parent._shadow_cache) == 1

    def test_multiple_shadows_have_isolated_caches(self):
        """Shadow A and Shadow B have independent caches."""
        parent = IsolationProcessor()

        # Create Shadow A (multiplier=20)
        result_a = parent.compute(5, multiplier=20)
        assert result_a == 100

        # Create Shadow B (multiplier=30)
        result_b = parent.compute(5, multiplier=30)
        assert result_b == 150

        # Verify both shadows exist
        assert len(parent._shadow_cache) == 2

        # Get shadow references
        shadows = list(parent._shadow_cache.values())
        shadow_a, shadow_b = shadows

        # Each shadow has its own cache
        assert len(shadow_a._cache) == 1
        assert len(shadow_b._cache) == 1

        # Caches contain different results
        assert shadow_a._cache != shadow_b._cache

    def test_parent_cache_untouched_after_shadow_computation(self):
        """Parent cache remains empty when only shadows compute."""
        parent = IsolationProcessor()

        # Only compute via shadows
        parent.compute(5, multiplier=20)
        parent.compute(5, multiplier=30)
        parent.compute(10, multiplier=40)

        # Parent cache should be empty
        assert len(parent._cache) == 0

        # Shadows have their caches populated
        for shadow in parent._shadow_cache.values():
            assert len(shadow._cache) >= 1

    def test_shared_data_accessible_in_shadows(self):
        """Non-settings attributes are shared across shadows."""
        parent = IsolationProcessor(shared_data=[10, 20, 30])

        # Compute via shadow
        parent.compute(5, multiplier=99)

        # Get shadow
        shadow = list(parent._shadow_cache.values())[0]

        # Shared data is the same object (not copied)
        assert shadow.shared_data is parent.shared_data
        assert shadow.shared_data == [10, 20, 30]

    def test_shadow_fingerprint_differs_from_parent(self):
        """Shadow views have different fingerprints than parent."""
        parent = IsolationProcessor()

        # Trigger shadow creation
        parent.compute(5, multiplier=99)
        shadow = list(parent._shadow_cache.values())[0]

        # Fingerprints are different
        assert parent.cache_fingerprint != shadow.cache_fingerprint

    def test_same_override_reuses_shadow(self):
        """Same settings override returns the same shadow (LRU cache hit)."""
        parent = IsolationProcessor()

        # First call with multiplier=20
        parent.compute(5, multiplier=20)
        assert len(parent._shadow_cache) == 1

        # Second call with same override
        parent.compute(10, multiplier=20)
        assert len(parent._shadow_cache) == 1  # Still just one shadow

        # The shadow's cache should have both results
        shadow = list(parent._shadow_cache.values())[0]
        assert len(shadow._cache) == 2
