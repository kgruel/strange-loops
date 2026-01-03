# Changelog

All notable changes to ev are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/). Pre-1.0 releases may have breaking changes in minor versions.

## [0.2.0] - 2026-01-03

### Added

- **Event factory methods**: `Event.log()`, `Event.progress()`, `Event.artifact()`, `Event.metric()`, `Event.input()`
- **Event.is_kind(*kinds)**: Check if event matches any of given kinds
- **Result factory methods**: `Result.ok()`, `Result.error()`
- **Result.is_ok / Result.is_error**: Boolean properties for status checking
- **Result invariants**: `ok` requires `code=0`, `error` requires `code != 0`
- **Emitter patterns documentation**: domain-emitters, emitter-archetypes, aggregating-emitter, live-emitter
- **Artifact `type` convention**: Explicit guidance on using `data.type` for discrimination

### Breaking

- `Result(status="error")` without explicit `code` now raises `ValueError`
  - Migration: Use `Result.error()` or provide `code=1`
- `Result(status="ok", code=N)` where N != 0 now raises `ValueError`
  - Migration: Use `Result.ok()` or ensure `code=0`

## [0.1.0] - 2026-01-02

Initial release.

### Added

- Core types: `Event`, `Result`
- Event kinds: `log`, `progress`, `artifact`, `metric`, `input`
- `Emitter` protocol with `emit()` and `finish()`
- Reference emitters: `ListEmitter`, `NullEmitter`
- Rendering emitters: `JsonEmitter`, `PlainEmitter`, `RichEmitter`
- Immutability via frozen dataclasses and `MappingProxyType`
- Serialization: `to_dict()` / `from_dict()` on Event and Result
