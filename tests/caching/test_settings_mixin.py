"""
Tests for SettingsMixin - standalone settings management without cache.

Verifies:
- SettingsMixin works without _cache or _lock
- Non-settings kwargs are silently filtered in _get_or_create_shadow
- Empty/invalid overrides return self (no shadow created)
- update_settings only clears _shadow_cache, not any compute cache
- to_config / from_config work without Cachable
"""

import json

import pytest

from tanat_utils import settings_dataclass, SettingsMixin

# =============================================================================
# Fixtures
# =============================================================================


@settings_dataclass
class MixinSettings:
    """Settings for SettingsMixin tests."""

    alpha: float = 0.5
    method: str = "default"


class SimpleProcessor(SettingsMixin):
    """Minimal processor using only SettingsMixin (no cache)."""

    SETTINGS_CLASS = MixinSettings

    def __init__(self, alpha=0.5, method="default"):
        super().__init__(settings=MixinSettings(alpha=alpha, method=method))

    @SettingsMixin.shadow_dispatch
    def compute(self, x, **kwargs):
        """Shadow dispatch: settings kwargs consumed, self = correct target."""
        return x * self.settings.alpha


class VerboseProcessor(SettingsMixin):
    """Processor whose compute returns (result, verbose) for passthrough tests."""

    SETTINGS_CLASS = MixinSettings

    def __init__(self):
        super().__init__()

    @SettingsMixin.shadow_dispatch
    def compute(self, x, verbose=False, **kwargs):
        """Returns tuple so tests can assert both value and passthrough."""
        return (x * self.settings.alpha, verbose)


class ConfigProcessor(SettingsMixin):
    """Processor with standard settings init for config serialisation tests."""

    SETTINGS_CLASS = MixinSettings

    def __init__(self, settings=None):
        super().__init__(settings)


# =============================================================================
# Test: shadow_dispatch decorator
# =============================================================================


class TestShadowDispatch:
    """shadow_dispatch separates settings kwargs from method kwargs."""

    def test_no_kwargs_uses_self(self):
        """No kwargs → self, no shadow created."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc.compute(10)

        assert result == 5.0
        assert len(proc._shadow_cache) == 0

    def test_settings_kwarg_creates_shadow(self):
        """A settings-matching kwarg creates a shadow and is consumed."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc.compute(10, alpha=0.8)

        assert result == 8.0
        assert len(proc._shadow_cache) == 1

    def test_non_settings_kwarg_passes_through(self):
        """A non-settings kwarg doesn't trigger a shadow and reaches the method."""
        proc = VerboseProcessor()
        result = proc.compute(10, verbose=True)

        assert result == (5.0, True)  # verbose passed through, no shadow
        assert len(proc._shadow_cache) == 0

    def test_mixed_kwargs_shadow_created_extra_passed_through(self):
        """Settings kwargs consumed for shadow; non-settings kwargs reach method."""
        proc = VerboseProcessor()
        result = proc.compute(10, alpha=0.8, verbose=True)

        assert result == (8.0, True)  # alpha consumed -> shadow; verbose passed through
        assert len(proc._shadow_cache) == 1

    def test_same_override_reuses_shadow(self):
        """Same settings override reuses the cached shadow."""
        proc = SimpleProcessor(alpha=0.5)

        proc.compute(10, alpha=0.8)
        proc.compute(20, alpha=0.8)

        assert len(proc._shadow_cache) == 1  # single shadow reused


# =============================================================================
# Test: shadow_dispatch with non-settings kwargs
# =============================================================================


class TestShadowDispatchUnknownFields:
    """shadow_dispatch routes non-settings kwargs to the method, not to the shadow."""

    def test_unknown_kwarg_passes_through_no_shadow(self):
        """Non-settings kwarg reaches the method unchanged, no shadow is created."""
        proc = VerboseProcessor()

        result = proc.compute(10, verbose=True)

        assert result == (5.0, True)
        assert len(proc._shadow_cache) == 0

    def test_mixed_kwargs_shadow_for_settings_passthrough_for_rest(self):
        """Settings kwarg creates shadow; non-settings kwarg still reaches the method."""
        proc = VerboseProcessor()

        result = proc.compute(10, alpha=0.8, verbose=True)

        assert result == (8.0, True)  # shadow applied alpha; verbose passed through
        assert len(proc._shadow_cache) == 1

    def test_valid_settings_kwarg_creates_shadow_no_warning(self, recwarn):
        """Valid settings kwarg creates a shadow with no warning."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc.compute(10, alpha=0.8)

        assert result == 8.0
        assert len(proc._shadow_cache) == 1
        assert len(recwarn) == 0


# =============================================================================
# Test: no valid override → return self
# =============================================================================


class TestShadowReturnsSelfIfEmpty:
    """_get_or_create_shadow returns self when overrides resolve to nothing."""

    def test_empty_overrides_returns_self(self):
        """Empty dict → self."""
        proc = SimpleProcessor()

        result = proc._get_or_create_shadow({})

        assert result is proc

    def test_no_kwargs_in_compute_uses_self(self):
        """compute() called without kwargs dispatches directly on self."""
        proc = SimpleProcessor(alpha=2.0)

        result = proc.compute(5)

        assert result == 10.0
        assert len(proc._shadow_cache) == 0


# =============================================================================
# Test: SettingsMixin alone - no _cache, no _lock
# =============================================================================


class TestSettingsMixinWithoutCache:
    """SettingsMixin works standalone with no Cachable infrastructure."""

    def test_no_cache_attribute(self):
        """SettingsMixin instances do not have _cache."""
        proc = SimpleProcessor()

        assert not hasattr(proc, "_cache")

    def test_no_lock_attribute(self):
        """SettingsMixin instances do not have _lock."""
        proc = SimpleProcessor()

        assert not hasattr(proc, "_lock")

    def test_settings_accessible(self):
        """settings property returns the current settings."""
        proc = SimpleProcessor(alpha=0.7, method="custom")

        assert proc.settings.alpha == 0.7
        assert proc.settings.method == "custom"

    def test_fingerprint_computed(self):
        """cache_fingerprint is not None when SETTINGS_CLASS is defined."""
        proc = SimpleProcessor()

        assert proc.cache_fingerprint is not None

    def test_shadow_has_no_cache(self):
        """Shadows created by SettingsMixin alone also have no _cache."""
        proc = SimpleProcessor(alpha=0.5)

        shadow = proc._get_or_create_shadow({"alpha": 0.9})

        assert shadow is not proc
        assert not hasattr(shadow, "_cache")
        assert not hasattr(shadow, "_lock")

    def test_repr(self):
        """__repr__ works without cache."""
        proc = SimpleProcessor(alpha=0.3)

        r = repr(proc)
        assert "SimpleProcessor" in r
        assert "settings=" in r


# =============================================================================
# Test: update_settings does NOT touch a compute cache
# =============================================================================


class TestUpdateDoesNotClearCache:
    """SettingsMixin.update_settings only clears _shadow_cache."""

    def test_shadow_cache_cleared_on_update(self):
        """update_settings clears _shadow_cache."""
        proc = SimpleProcessor(alpha=0.5)

        # Create a shadow
        proc._get_or_create_shadow({"alpha": 0.9})
        assert len(proc._shadow_cache) == 1

        proc.update_settings(alpha=0.3)

        assert len(proc._shadow_cache) == 0

    def test_no_cache_interference(self):
        """update_settings on SettingsMixin does not attempt to clear _cache."""
        proc = SimpleProcessor(alpha=0.5)

        # Should not raise even though _cache doesn't exist
        proc.update_settings(alpha=0.8)

        assert proc.settings.alpha == 0.8

    def test_fingerprint_updated(self):
        """Fingerprint changes after update_settings."""
        proc = SimpleProcessor(alpha=0.5)
        fp_before = proc.cache_fingerprint

        proc.update_settings(alpha=0.9)

        assert proc.cache_fingerprint != fp_before

    def test_chained_updates(self):
        """update_settings returns self for chaining."""
        proc = SimpleProcessor()

        result = proc.update_settings(alpha=0.1).update_settings(method="new")

        assert result is proc
        assert proc.settings.alpha == 0.1
        assert proc.settings.method == "new"


# =============================================================================
# Test: to_config / from_config on SettingsMixin standalone
# =============================================================================


class TestConfigSerialization:
    """SettingsMixin serialisation works without Cachable."""

    def test_to_config_returns_settings(self):
        """to_config includes settings dict."""
        proc = ConfigProcessor(MixinSettings(alpha=0.9, method="fast"))

        config = proc.to_config()

        assert config == {"settings": {"alpha": 0.9, "method": "fast"}}

    def test_to_config_default_settings(self):
        """to_config with default settings."""
        proc = ConfigProcessor()

        config = proc.to_config()

        assert config == {"settings": {"alpha": 0.5, "method": "default"}}

    def test_from_config_reconstructs(self):
        """from_config creates a working instance."""
        config = {"settings": {"alpha": 0.7, "method": "custom"}}

        proc = ConfigProcessor.from_config(config)

        assert isinstance(proc, ConfigProcessor)
        assert proc.settings.alpha == 0.7
        assert proc.settings.method == "custom"

    def test_config_roundtrip(self):
        """to_config -> from_config preserves state."""
        original = ConfigProcessor(MixinSettings(alpha=0.3, method="new"))

        config = original.to_config()
        restored = ConfigProcessor.from_config(config)

        assert restored.settings.alpha == original.settings.alpha
        assert restored.settings.method == original.settings.method

    def test_save_config(self, tmp_path):
        """save_config persists to disk as JSON."""
        proc = ConfigProcessor(MixinSettings(alpha=0.4))
        path = tmp_path / "config.json"

        proc.save_config(path)

        data = json.loads(path.read_text())
        assert data == {"settings": {"alpha": 0.4, "method": "default"}}
