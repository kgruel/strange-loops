---
status: not-started
updated: 2026-01-04
related:
  - 2026-01-04-trifecta-alignment.md
  - ev-present: 2026-01-04-trifecta-ev-present-changes.md
  - ev-runtime: 2026-01-04-trifecta-ev-runtime-changes.md
  - ev-toolkit: 2026-01-04-trifecta-ev-toolkit-changes.md
---

# ev Core Changes - Trifecta Alignment

Changes to ev as part of the trifecta boundary alignment.

## Related Plans

| Project | Plan | Coordination |
|---------|------|--------------|
| **ev-present** | `2026-01-04-trifecta-ev-present-changes.md` | Documents Normalizer protocol |
| **ev-runtime** | `2026-01-04-trifecta-ev-runtime-changes.md` | Respects Result.code from this contract |
| **ev-toolkit** | `2026-01-04-trifecta-ev-toolkit-changes.md` | Receives TeeEmitter, FileEmitter, RichEmitter |

## Changes

### 1. Schema Versioning

Add `_schema` field to `Event.to_dict()` and `Result.to_dict()` for forward compatibility.

**Files**: `src/ev/types.py`

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "_schema": "ev:event@0.1",
        "kind": self.kind,
        # ...existing fields
    }
```

```python
def to_dict(self) -> dict[str, Any]:
    return {
        "_schema": "ev:result@0.1",
        "status": self.status,
        # ...existing fields
    }
```

**Tests**: Update `test_types.py` to verify `_schema` in serialized output.

### 2. Move Utility Emitters to ev-toolkit

Remove from ev, relocate to ev-toolkit:
- `TeeEmitter` (emitters/tee.py)
- `FileEmitter` (emitters/tee.py)
- `RichEmitter` (emitters/rich.py)

**Files to remove**:
- `src/ev/emitters/tee.py`
- `src/ev/emitters/rich.py`

**Files to update**:
- `src/ev/emitters/__init__.py` - remove exports
- `pyproject.toml` - remove `rich` optional dependency

**Remaining in ev**:
- `emitter.py`: Emitter protocol, ListEmitter, NullEmitter
- `emitters/plain.py`: PlainEmitter
- `emitters/json.py`: JsonEmitter

### 3. Progress Data Conventions (Documentation)

Document recommended fields for progress events in `docs/concept/progress.md`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Unique identifier for this progress stream |
| `parent_id` | str | Parent progress id (for nesting) |
| `current` | int/float | Current value |
| `total` | int/float | Total value |
| `unit` | str | What's being counted |
| `phase` | str | Named phase identifier |
| `status` | str | "running" / "ok" / "error" |

These are conventions in `Event.data`, not new top-level fields.

## Test Plan

- [ ] `_schema` field present in Event.to_dict() output
- [ ] `_schema` field present in Result.to_dict() output
- [ ] JsonEmitter output includes `_schema`
- [ ] PlainEmitter still works after removals
- [ ] JsonEmitter still works after removals
- [ ] No import errors after removing tee.py/rich.py

## Dependencies

- ev-toolkit must be ready to receive TeeEmitter, FileEmitter, RichEmitter before removal
