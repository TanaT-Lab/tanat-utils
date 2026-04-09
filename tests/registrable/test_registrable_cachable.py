#!/usr/bin/env python3
"""
Tests for combined Registrable + CachableSettings usage.

Verifies that classes can inherit from both mixins:
- Registration works with settings-aware classes
- Pydantic validation can deserialize with settings
- Serialization captures both type and settings
- Cache behavior works correctly with registered types
"""

import pickle
import json

import pytest
from pydantic import BaseModel

from tanat_utils import settings_dataclass, Cachable, CachableSettings
from tanat_utils.registrable import Registrable

# =============================================================================
# Fixtures: Registrable + CachableSettings classes
# =============================================================================


@settings_dataclass
class MetricSettings:
    """Settings for metrics."""

    normalize: bool = False
    threshold: float = 0.0


class BaseMetric(CachableSettings, Registrable):
    """Base class combining CachableSettings and Registrable."""

    _REGISTER = {}
    SETTINGS_CLASS = MetricSettings

    def compute(self, x, y):
        raise NotImplementedError


class EuclideanMetric(BaseMetric, register_name="euclidean"):
    """Euclidean distance metric with caching."""

    @Cachable.cached_method()
    def compute(self, x, y):
        """Compute euclidean distance (cached)."""
        dist = sum((a - b) ** 2 for a, b in zip(x, y)) ** 0.5
        if self.settings.normalize:
            dist = dist / (len(x) ** 0.5)
        return dist


class ManhattanMetric(BaseMetric, register_name="manhattan"):
    """Manhattan distance metric with caching."""

    @Cachable.cached_method()
    def compute(self, x, y):
        """Compute manhattan distance (cached)."""
        dist = sum(abs(a - b) for a, b in zip(x, y))
        if self.settings.normalize:
            dist = dist / len(x)
        return dist


# =============================================================================
# Combined Functionality Tests
# =============================================================================


class TestRegistrableCachable:
    """Test that both mixins work together."""

    def test_registration_works(self):
        """Classes are registered correctly."""
        assert "euclidean" in BaseMetric.list_registered()
        assert BaseMetric.get_registered("euclidean") is EuclideanMetric

    def test_settings_work(self):
        """Settings are initialized correctly."""
        metric = EuclideanMetric(MetricSettings(normalize=True))
        assert metric.settings.normalize is True

    def test_caching_works(self):
        """Caching works on registered classes."""
        metric = EuclideanMetric()

        # First call computes
        result1 = metric.compute([0, 0], [3, 4])
        assert result1 == 5.0

        # Second call uses cache
        result2 = metric.compute([0, 0], [3, 4])
        assert result2 == 5.0
        assert len(metric._cache) == 1

    def test_get_registration_name(self):
        """Can get registration name from instance."""
        metric = EuclideanMetric()
        assert metric.get_registration_name() == "euclidean"


# =============================================================================
# Pydantic Validation Tests
# =============================================================================


class TestPydanticWithSettings:
    """Test Pydantic validation creates instances with default settings."""

    def test_string_creates_with_defaults(self):
        """String creates instance with default settings."""

        class Config(BaseModel):
            metric: BaseMetric

        config = Config(metric="euclidean")

        assert isinstance(config.metric, EuclideanMetric)
        assert config.metric.settings.normalize is False
        assert config.metric.settings.threshold == 0.0

    def test_instance_preserves_settings(self):
        """Existing instance preserves its settings."""

        class Config(BaseModel):
            metric: BaseMetric

        metric = EuclideanMetric(MetricSettings(normalize=True, threshold=0.5))
        config = Config(metric=metric)

        assert config.metric.settings.normalize is True
        assert config.metric.settings.threshold == 0.5


# =============================================================================
# Serialization Tests
# =============================================================================


class TestSerialization:
    """Test serialization of Registrable + CachableSettings."""

    def test_pydantic_serializes_to_config(self):
        """Pydantic serializes to full config dict."""

        class Config(BaseModel):
            metric: BaseMetric

        config = Config(metric=EuclideanMetric())
        data = config.model_dump()

        assert data["metric"] == {
            "type": "euclidean",
            "settings": {"normalize": False, "threshold": 0.0},
        }

    def test_pydantic_roundtrip(self):
        """Pydantic JSON roundtrip works."""

        class Config(BaseModel):
            metric: BaseMetric

        config = Config(metric="manhattan")
        json_str = config.model_dump_json()
        restored = Config.model_validate_json(json_str)

        assert isinstance(restored.metric, ManhattanMetric)

    def test_pickle_roundtrip(self):
        """Pickle serialization preserves both registration and settings."""
        metric = EuclideanMetric(MetricSettings(normalize=True))

        # Populate cache
        metric.compute([0, 0], [3, 4])

        # Pickle roundtrip
        pickled = pickle.dumps(metric)
        restored = pickle.loads(pickled)

        assert isinstance(restored, EuclideanMetric)
        assert restored.settings.normalize is True
        assert restored.get_registration_name() == "euclidean"

    def test_pickle_cache_cleared(self):
        """Pickle clears cache but preserves settings."""
        metric = EuclideanMetric()
        metric.compute([0, 0], [3, 4])
        assert len(metric._cache) == 1

        restored = pickle.loads(pickle.dumps(metric))
        # Cache is cleared after pickle (lock reset)
        # But method still works
        result = restored.compute([0, 0], [3, 4])
        assert result == 5.0


# =============================================================================
# Update Settings Tests
# =============================================================================


class TestUpdateSettingsWithRegistry:
    """Test update_settings with registered classes."""

    def test_update_settings_clears_cache(self):
        """update_settings clears cache on registered instance."""
        metric = EuclideanMetric()

        # Populate cache
        metric.compute([0, 0], [3, 4])
        assert len(metric._cache) == 1

        # Update settings
        metric.update_settings(normalize=True)
        assert len(metric._cache) == 0
        assert metric.settings.normalize is True

    def test_update_preserves_registration(self):
        """update_settings preserves registration name."""
        metric = EuclideanMetric()
        metric.update_settings(normalize=True)

        assert metric.get_registration_name() == "euclidean"


# =============================================================================
# Multiple Inheritance Order Tests
# =============================================================================


class TestInheritanceOrder:
    """Test different inheritance orders work."""

    def test_cachable_first(self):
        """CachableSettings first in MRO works."""

        class CachableFirst(CachableSettings, Registrable):
            _REGISTER = {}
            SETTINGS_CLASS = MetricSettings

        class ChildCF(CachableFirst, register_name="cf"):
            pass

        assert CachableFirst.get_registered("cf") is ChildCF
        instance = ChildCF()
        assert instance.settings is not None

    def test_registrable_first(self):
        """Registrable first in MRO works."""

        class RegistrableFirst(Registrable, CachableSettings):
            _REGISTER = {}
            SETTINGS_CLASS = MetricSettings

        class ChildRF(RegistrableFirst, register_name="rf"):
            pass

        assert RegistrableFirst.get_registered("rf") is ChildRF
        instance = ChildRF()
        assert instance.settings is not None


# =============================================================================
# Config Serialization Tests (to_config / from_config)
# =============================================================================


class TestConfigSerialization:
    """Test to_config / from_config methods."""

    def test_to_config_includes_type_and_settings(self):
        """to_config returns type and settings."""
        metric = EuclideanMetric(MetricSettings(normalize=True, threshold=0.5))
        config = metric.to_config()

        assert config == {
            "type": "euclidean",
            "settings": {"normalize": True, "threshold": 0.5},
        }

    def test_to_config_default_settings(self):
        """to_config with default settings."""
        metric = EuclideanMetric()
        config = metric.to_config()

        assert config == {
            "type": "euclidean",
            "settings": {"normalize": False, "threshold": 0.0},
        }

    def test_from_config_with_type_and_settings(self):
        """from_config reconstructs with type and settings."""
        config = {
            "type": "euclidean",
            "settings": {"normalize": True, "threshold": 0.5},
        }
        metric = BaseMetric.from_config(config)

        assert isinstance(metric, EuclideanMetric)
        assert metric.settings.normalize is True
        assert metric.settings.threshold == 0.5

    def test_from_config_type_only(self):
        """from_config with type only uses defaults."""
        config = {"type": "manhattan"}
        metric = BaseMetric.from_config(config)

        assert isinstance(metric, ManhattanMetric)
        assert metric.settings.normalize is False

    def test_from_config_on_concrete_class(self):
        """from_config on concrete class ignores type."""
        config = {"settings": {"normalize": True}}
        metric = EuclideanMetric.from_config(config)

        assert isinstance(metric, EuclideanMetric)
        assert metric.settings.normalize is True

    def test_config_roundtrip(self):
        """to_config → from_config roundtrip preserves state."""
        original = EuclideanMetric(MetricSettings(normalize=True, threshold=0.75))
        config = original.to_config()
        restored = BaseMetric.from_config(config)

        assert type(restored) is type(original)
        assert restored.settings.normalize == original.settings.normalize
        assert restored.settings.threshold == original.settings.threshold

    def test_json_roundtrip(self):
        """JSON serialization roundtrip."""
        metric = EuclideanMetric(MetricSettings(normalize=True))
        json_str = json.dumps(metric.to_config())
        restored = BaseMetric.from_config(json.loads(json_str))

        assert isinstance(restored, EuclideanMetric)
        assert restored.settings.normalize is True


class TestPydanticDictValidation:
    """Test Pydantic validation with dict format."""

    def test_dict_with_type_and_settings(self):
        """Pydantic accepts dict with type and settings."""

        class Config(BaseModel):
            metric: BaseMetric

        config = Config(metric={"type": "euclidean", "settings": {"normalize": True}})

        assert isinstance(config.metric, EuclideanMetric)
        assert config.metric.settings.normalize is True

    def test_dict_with_type_only(self):
        """Pydantic accepts dict with type only."""

        class Config(BaseModel):
            metric: BaseMetric

        config = Config(metric={"type": "manhattan"})

        assert isinstance(config.metric, ManhattanMetric)
        assert config.metric.settings.normalize is False

    def test_pydantic_json_roundtrip_with_settings(self):
        """Pydantic JSON roundtrip preserves settings."""

        class Config(BaseModel):
            metric: BaseMetric

        original = Config(
            metric=EuclideanMetric(MetricSettings(normalize=True, threshold=0.5))
        )
        json_str = original.model_dump_json()
        restored = Config.model_validate_json(json_str)

        assert isinstance(restored.metric, EuclideanMetric)
        assert restored.metric.settings.normalize is True
        assert restored.metric.settings.threshold == 0.5
