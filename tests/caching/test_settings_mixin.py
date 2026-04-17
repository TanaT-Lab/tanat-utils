"""
Tests for SettingsMixin - standalone settings management without cache.

Verifies:
- update_settings works correctly
- _resolve_settings returns correct settings with/without overrides
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

    def compute(self, x, **kwargs):
        """Explicit settings threading via _resolve_settings."""
        settings = self._resolve_settings(kwargs)
        return x * settings.alpha


# =============================================================================
# Test: _resolve_settings
# =============================================================================


class TestResolveSettings:
    """_resolve_settings returns a settings copy with overrides applied."""

    def test_no_override_returns_same_object(self):
        """Empty overrides return the original settings object unchanged."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc._resolve_settings({})

        assert result is proc.settings

    def test_valid_override_returns_copy(self):
        """A matching override returns a new settings instance with the value applied."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc._resolve_settings({"alpha": 0.8})

        assert result is not proc.settings
        assert result.alpha == 0.8
        assert proc.settings.alpha == 0.5  # original unchanged

    def test_unknown_keys_are_ignored(self):
        """Non-settings keys are silently filtered out."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc._resolve_settings({"alpha": 0.9, "verbose": True})

        assert result.alpha == 0.9
        assert not hasattr(result, "verbose")

    def test_none_settings_returns_none(self):
        """_resolve_settings returns None when _settings is None."""

        class NoSettingsProc(SettingsMixin):
            SETTINGS_CLASS = None

        proc = NoSettingsProc()

        result = proc._resolve_settings({"alpha": 0.5})

        assert result is None

    def test_overrides_used_in_compute(self):
        """Override applied through _resolve_settings affects computation."""
        proc = SimpleProcessor(alpha=0.5)

        result = proc.compute(10, alpha=0.8)

        assert result == 8.0
        assert proc.settings.alpha == 0.5  # original unchanged


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
    """SettingsMixin.update_settings works correctly."""

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
        proc = SimpleProcessor(alpha=0.9, method="fast")

        config = proc.to_config()

        assert config == {"settings": {"alpha": 0.9, "method": "fast"}}

    def test_to_config_default_settings(self):
        """to_config with default settings."""
        proc = SimpleProcessor()

        config = proc.to_config()

        assert config == {"settings": {"alpha": 0.5, "method": "default"}}

    def test_from_config_reconstructs(self):
        """from_config creates a working instance."""
        config = {"settings": {"alpha": 0.7, "method": "custom"}}

        proc = SimpleProcessor.from_config(config)

        assert isinstance(proc, SimpleProcessor)
        assert proc.settings.alpha == 0.7
        assert proc.settings.method == "custom"

    def test_config_roundtrip(self):
        """to_config -> from_config preserves state."""
        original = SimpleProcessor(alpha=0.3, method="new")

        config = original.to_config()
        restored = SimpleProcessor.from_config(config)

        assert restored.settings.alpha == original.settings.alpha
        assert restored.settings.method == original.settings.method

    def test_save_config(self, tmp_path):
        """save_config persists to disk as JSON."""
        proc = SimpleProcessor(alpha=0.4)
        path = tmp_path / "config.json"

        proc.save_config(path)

        data = json.loads(path.read_text())
        assert data == {"settings": {"alpha": 0.4, "method": "default"}}
