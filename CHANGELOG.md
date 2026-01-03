# Changelog

All notable changes to ev are documented here.

Format based on [Keep a Changelog](https://keepachangelog.com/). Pre-1.0 releases may have breaking changes in minor versions.

## [0.3.0] - 2026-01-03

### Added

- **Event factory methods**: `Event.log()`, `Event.progress()`, `Event.artifact()`, `Event.metric()`, `Event.input()`
- **Event.is_kind(*kinds)**: Check if event matches any of given kinds
- **Result factory methods**: `Result.ok()`, `Result.error()`
- **Result.is_ok / Result.is_error**: Boolean properties for status checking
- **Result invariants**: `ok` requires `code=0`, `error` requires `code != 0`
- **Emitter patterns documentation**: domain-emitters, emitter-archetypes, aggregating-emitter, live-emitter

### Changed

- **Event.artifact() now requires `type` as first positional argument**
  - Old: `Event.artifact("message", type="file", path="/tmp/x")`
  - New: `Event.artifact("file", "message", path="/tmp/x")`
  - Rationale: Artifacts need a type for consumers to discriminate; factory enforces this convention
  - Raw constructor `Event(kind="artifact", ...)` unchanged for escape hatch

- **Event.ts is now auto-populated with `time.time()`**
  - Old: `ts: float | None = None` (user must set explicitly)
  - New: `ts: float = time.time()` (auto-populated at creation)
  - Explicit `ts=` parameter still works for replay/testing
  - `from_dict()` uses `0.0` for missing/null ts (sentinel for unknown original time)
  - Rationale: Events always have an emission timestamp; domain timing goes in `data` or `metric`

### Breaking

- `Event.artifact()` signature changed: `type` is now required first positional arg
  - Migration: Move `type=` to first positional: `Event.artifact("file", ...)` instead of `Event.artifact(type="file", ...)`
- `Event.ts` type changed from `float | None` to `float` (always present)
  - Migration: Remove `if event.ts is not None` checks; ts is always a float
  - Tests comparing full Event equality need explicit `ts=` or field-by-field comparison
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
