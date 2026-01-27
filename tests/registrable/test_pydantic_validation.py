#!/usr/bin/env python3
"""
Tests for Pydantic validation of Registrable types.

Verifies that Registrable classes can be used as Pydantic field types:
- String → lookup and instantiate registered class
- Instance → pass-through
- Serialization → registration name
"""

import pytest
from pydantic import BaseModel, ValidationError

from tanat_utils.registrable import Registrable

# =============================================================================
# Fixtures
# =============================================================================


class BaseMetric(Registrable):
    """Base class for registrable metrics."""

    _REGISTER = {}

    def __init__(self, normalize: bool = False):
        self.normalize = normalize

    def compute(self, x, y):
        raise NotImplementedError


class EuclideanMetric(BaseMetric, register_name="euclidean"):
    """Euclidean distance metric."""

    def compute(self, x, y):
        return sum((a - b) ** 2 for a, b in zip(x, y)) ** 0.5


class ManhattanMetric(BaseMetric, register_name="manhattan"):
    """Manhattan distance metric."""

    def compute(self, x, y):
        return sum(abs(a - b) for a, b in zip(x, y))


class MetricConfig(BaseModel):
    """Pydantic model with Registrable field."""

    name: str
    metric: BaseMetric


# =============================================================================
# Validation Tests
# =============================================================================


class TestPydanticValidation:
    """Test Pydantic validation of Registrable fields."""

    def test_string_creates_instance(self):
        """String value creates instance via get_registered."""
        config = MetricConfig(name="test", metric="euclidean")

        assert isinstance(config.metric, EuclideanMetric)

    def test_instance_passthrough(self):
        """Existing instance is passed through unchanged."""
        metric = EuclideanMetric(normalize=True)
        config = MetricConfig(name="test", metric=metric)

        assert config.metric is metric
        assert config.metric.normalize is True

    def test_invalid_string_raises_error(self):
        """Invalid registration name raises ValidationError."""
        with pytest.raises(ValidationError):
            MetricConfig(name="test", metric="nonexistent")

    def test_invalid_type_raises_error(self):
        """Invalid type raises ValidationError."""
        with pytest.raises(ValidationError):
            MetricConfig(name="test", metric=123)


# =============================================================================
# Serialization Tests
# =============================================================================


class TestPydanticSerialization:
    """Test Pydantic serialization of Registrable fields."""

    def test_serialize_to_registration_name(self):
        """Serialization returns registration name."""
        config = MetricConfig(name="test", metric="euclidean")
        data = config.model_dump()

        assert data == {"name": "test", "metric": "euclidean"}

    def test_serialize_instance_to_name(self):
        """Instance serializes to its registration name."""
        config = MetricConfig(name="test", metric=EuclideanMetric())
        data = config.model_dump()

        assert data["metric"] == "euclidean"

    def test_json_roundtrip(self):
        """JSON serialization and deserialization roundtrip."""
        config = MetricConfig(name="test", metric="manhattan")
        json_str = config.model_dump_json()
        restored = MetricConfig.model_validate_json(json_str)

        assert isinstance(restored.metric, ManhattanMetric)
        assert restored.name == "test"


# =============================================================================
# Nested Model Tests
# =============================================================================


class TestNestedModels:
    """Test Registrable in nested Pydantic models."""

    def test_nested_model_with_registrable(self):
        """Registrable works in nested models."""

        class Pipeline(BaseModel):
            steps: list[MetricConfig]

        pipeline = Pipeline(
            steps=[
                {"name": "step1", "metric": "euclidean"},
                {"name": "step2", "metric": "manhattan"},
            ]
        )

        assert len(pipeline.steps) == 2
        assert isinstance(pipeline.steps[0].metric, EuclideanMetric)
        assert isinstance(pipeline.steps[1].metric, ManhattanMetric)

    def test_nested_serialization(self):
        """Nested models serialize correctly."""

        class Pipeline(BaseModel):
            steps: list[MetricConfig]

        pipeline = Pipeline(
            steps=[
                MetricConfig(name="step1", metric=EuclideanMetric()),
            ]
        )

        data = pipeline.model_dump()
        assert data["steps"][0]["metric"] == "euclidean"
