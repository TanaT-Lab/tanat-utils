# Changelog

All notable changes to this project will be documented in this file.

## [v0.0.4] - Mixin refactor

### Added

- `SettingsMixin`: standalone settings management (no cache dependency)
- `shadow_dispatch` decorator with optional field targeting

### Changed

- Extract `Cachable` from `CachableSettings` (cache-only mixin, no settings)
- `CachableSettings` now composes `SettingsMixin` + `Cachable`
- `_get_or_create_shadow` filters non-settings keys automatically

## [v0.0.3] - Add pretty-format utilities

### Added

- `format_header`, `format_section`, `format_kv`, `format_bullet`, `format_feature_section`

## [v0.0.2] - Add DisplayMixin

### Added

- `DisplayMixin` with box-drawing progress output
- `DisplayIndentManager` for nested component display

## [v0.0.1] - Initial release

### Added

- `CachableSettings` mixin with LRU cache and thread-safe operations
- `Registrable` mixin for class registry with automatic registration via `__init_subclass__`
- Pydantic validation for `Registrable` types (string, dict, or instance)
- `@cached_method` decorator with `shadow_on` and `ignore` parameters
- `@cached_property` decorator with double-check locking
- `to_config()` / `from_config()` methods for serialization/deserialization
- `update_settings()` method with automatic cache clearing
- `@settings_dataclass` decorator combining frozen dataclass + Pydantic validation
- `fingerprint()` function for deterministic settings hashing