"""
Tests for Nested CachableSettings - Settings containing CachableSettings attributes

Verifies that when a settings dataclass contains a CachableSettings instance:
- Pydantic validation accepts the type correctly
- Cache behaves correctly with nested instances
- Pickle serialization works end-to-end
- Fingerprinting captures the nested state
"""

import pickle
from dataclasses import field

from tanat_utils import settings_dataclass, Cachable, CachableSettings
from tanat_utils.caching.fingerprint import fingerprint

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class ChildSettings:
    """Settings for child processor."""

    multiplier: int = 2


class ChildProcessor(CachableSettings):
    """A processor that will be embedded in parent settings."""

    SETTINGS_CLASS = ChildSettings

    @Cachable.cached_method()
    def transform(self, x):
        return x * self.settings.multiplier


@settings_dataclass(config={"arbitrary_types_allowed": True})
class ParentSettings:
    """Settings containing a CachableSettings instance as attribute."""

    name: str = "parent"
    child: ChildProcessor = field(  # pylint: disable=invalid-field-call
        default_factory=ChildProcessor
    )


class ParentProcessor(CachableSettings):
    """Parent processor with nested CachableSettings in its settings."""

    SETTINGS_CLASS = ParentSettings

    @Cachable.cached_method()
    def compute(self, x):
        """Uses the child processor from settings."""
        return self.settings.child.transform(x) + len(self.settings.name)


# =============================================================================
# Pydantic Validation Tests
# =============================================================================


class TestPydanticValidation:
    """Verify Pydantic accepts CachableSettings as field type."""

    def test_default_child_created(self):
        """Default child processor is created via default_factory."""
        settings = ParentSettings()

        assert settings.child is not None
        assert isinstance(settings.child, ChildProcessor)

    def test_custom_child_accepted(self):
        """Custom child processor is accepted."""
        child = ChildProcessor(ChildSettings(multiplier=10))
        settings = ParentSettings(name="custom", child=child)

        assert settings.child is child
        assert settings.child.settings.multiplier == 10

    def test_parent_processor_with_default_settings(self):
        """ParentProcessor works with default settings."""
        parent = ParentProcessor()

        assert parent.settings.child is not None
        result = parent.compute(5)
        # 5 * 2 (child multiplier) + 6 (len("parent"))
        assert result == 16

    def test_parent_processor_with_custom_child(self):
        """ParentProcessor works with custom child in settings."""
        child = ChildProcessor(ChildSettings(multiplier=100))
        parent = ParentProcessor(ParentSettings(name="test", child=child))

        result = parent.compute(5)
        # 5 * 100 + 4 (len("test"))
        assert result == 504


# =============================================================================
# Cache Behavior Tests
# =============================================================================


class TestNestedCacheBehavior:
    """Verify cache works correctly with nested CachableSettings."""

    def test_child_cache_independent_from_parent(self):
        """Child's cache is separate from parent's cache."""
        child = ChildProcessor(ChildSettings(multiplier=3))
        parent = ParentProcessor(ParentSettings(child=child))

        # Compute via parent (populates both caches)
        parent.compute(10)

        # Child has its own cache entry
        assert len(child._cache) == 1

        # Parent has its own cache entry
        assert len(parent._cache) == 1

    def test_child_cache_reused_across_parent_calls(self):
        """Child's cached value is reused when parent calls it again."""
        child = ChildProcessor(ChildSettings(multiplier=5))
        parent = ParentProcessor(ParentSettings(child=child))

        # First call
        parent.compute(7)
        child_cache_size_after_first = len(child._cache)

        # Clear parent cache, call again
        parent.clear_cache()
        parent.compute(7)

        # Child cache unchanged (reused)
        assert len(child._cache) == child_cache_size_after_first

    def test_different_parents_same_child_share_cache(self):
        """Multiple parents sharing same child share child's cache."""
        child = ChildProcessor(ChildSettings(multiplier=2))

        parent1 = ParentProcessor(ParentSettings(name="p1", child=child))
        parent2 = ParentProcessor(ParentSettings(name="p2", child=child))

        # Both parents compute with same x
        parent1.compute(10)
        parent2.compute(10)

        # Child only computed once (cache hit for parent2)
        assert len(child._cache) == 1

    def test_clear_parent_cache_preserves_child_cache(self):
        """Clearing parent cache doesn't affect child cache."""
        child = ChildProcessor()
        parent = ParentProcessor(ParentSettings(child=child))

        parent.compute(5)
        assert len(child._cache) == 1

        parent.clear_cache()

        # Child cache untouched
        assert len(child._cache) == 1


# =============================================================================
# Serialization (Pickle) Tests
# =============================================================================


class TestNestedSerialization:
    """Verify pickle works with nested CachableSettings."""

    def test_pickle_parent_with_child(self):
        """Parent with embedded child pickles and unpickles correctly."""
        child = ChildProcessor(ChildSettings(multiplier=7))
        parent = ParentProcessor(ParentSettings(name="pickled", child=child))

        # Populate caches
        parent.compute(3)

        # Pickle round-trip
        data = pickle.dumps(parent)
        restored = pickle.loads(data)

        # Settings preserved
        assert restored.settings.name == "pickled"
        assert restored.settings.child.settings.multiplier == 7

    def test_pickle_preserves_child_cache(self):
        """Child's cache is preserved through pickle."""
        child = ChildProcessor(ChildSettings(multiplier=4))
        parent = ParentProcessor(ParentSettings(child=child))

        # Populate child cache
        parent.compute(10)
        original_child_cache_size = len(child._cache)

        # Pickle round-trip
        restored = pickle.loads(pickle.dumps(parent))

        # Child cache preserved
        assert len(restored.settings.child._cache) == original_child_cache_size

    def test_pickle_child_still_functional(self):
        """Child processor works after unpickling."""
        child = ChildProcessor(ChildSettings(multiplier=5))
        parent = ParentProcessor(ParentSettings(child=child))

        parent.compute(2)

        restored = pickle.loads(pickle.dumps(parent))

        # Child can still compute
        result = restored.settings.child.transform(10)
        assert result == 50  # 10 * 5

    def test_pickle_parent_still_functional(self):
        """Parent processor works after unpickling."""
        parent = ParentProcessor(ParentSettings(name="xyz"))

        result_before = parent.compute(5)

        restored = pickle.loads(pickle.dumps(parent))
        result_after = restored.compute(5)

        assert result_before == result_after


# =============================================================================
# Fingerprint Tests
# =============================================================================


class TestNestedFingerprint:
    """Verify fingerprinting captures nested state."""

    def test_child_fingerprint_captured(self):
        """Child's fingerprint is part of parent settings serialization."""
        child1 = ChildProcessor(ChildSettings(multiplier=10))
        child2 = ChildProcessor(ChildSettings(multiplier=20))

        settings1 = ParentSettings(name="same", child=child1)
        settings2 = ParentSettings(name="same", child=child2)

        # Different children = different fingerprints
        fp1 = fingerprint(settings1)
        fp2 = fingerprint(settings2)

        assert fp1 != fp2

    def test_same_config_same_fingerprint(self):
        """Identical nested configuration produces same fingerprint."""
        child1 = ChildProcessor(ChildSettings(multiplier=5))
        child2 = ChildProcessor(ChildSettings(multiplier=5))

        settings1 = ParentSettings(name="test", child=child1)
        settings2 = ParentSettings(name="test", child=child2)

        fp1 = fingerprint(settings1)
        fp2 = fingerprint(settings2)

        assert fp1 == fp2

    def test_parent_change_changes_fingerprint(self):
        """Changing parent attribute changes fingerprint."""
        child = ChildProcessor()

        settings1 = ParentSettings(name="alpha", child=child)
        settings2 = ParentSettings(name="beta", child=child)

        fp1 = fingerprint(settings1)
        fp2 = fingerprint(settings2)

        assert fp1 != fp2
