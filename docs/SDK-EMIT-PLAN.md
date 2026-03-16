# Emit SDK Extraction Plan

This is the first concrete extraction plan for the proposed `loops.sdk` layer.
`emit` is the best pilot because it is central, semantically crisp, and already has a
broad test surface.

## Goal

Move `emit` semantics out of `loops.main` into a structured SDK operation while keeping
CLI behavior unchanged.

End state:

```text
argv -> argparse -> EmitRequest -> sdk.emit() -> EmitResult -> CLI rendering
```

## Scope of the pilot

In scope:

- target resolution for emit
- payload-part parsing into fact payload
- observer resolution / scoping
- entity-ref resolution
- store resolution and persistence
- dry-run behavior as structured result
- typed errors

Out of scope for the pilot:

- redesigning all CLI rendering
- changing user-facing command syntax
- extracting `read`, `sync`, or `population`
- changing engine/lib boundaries

## Proposed module layout

```text
apps/loops/src/loops/sdk/
  __init__.py
  errors.py
  targets.py
  emit.py
```

## Request / result types

```python
@dataclass(frozen=True)
class EmitRequest:
    target: str | Path | None
    kind: str
    parts: tuple[str, ...]
    observer: str | None = None
    dry_run: bool = False

@dataclass(frozen=True)
class EmitResult:
    vertex_path: Path
    store_path: Path | None
    fact: dict[str, object]
    persisted: bool
```

Potential follow-up refinements:
- split parsed payload from raw parts if useful
- include `resolved_observer` explicitly
- include typed `Fact` instead of a plain dict if that improves composition

## Error types

```python
class LoopsSDKError(Exception): ...
class TargetNotFound(LoopsSDKError): ...
class StoreNotConfigured(LoopsSDKError): ...
class ObserverRejected(LoopsSDKError): ...
class InvalidEmitPayload(LoopsSDKError): ...
```

The CLI catches these and maps them to current behavior:
- user message to stderr
- exit code 1

## Responsibilities by module

### `sdk.targets`
Owns emit target resolution.

Functions likely needed:

```python
def resolve_emit_target(target: str | Path | None) -> ResolvedTarget: ...
```

`ResolvedTarget` should contain at least:
- `vertex_path`
- `store_path | None`
- maybe `name`

This module should absorb logic currently scattered across local/session/named/path-like
resolution branches.

### `sdk.emit`
Owns semantic emit flow.

Likely internal steps:

1. resolve target to vertex/store
2. parse `parts` into payload
3. resolve observer
4. apply vertex scoping if needed
5. validate observer against vertex grants
6. construct fact
7. resolve entity references
8. persist unless dry-run
9. return `EmitResult`

## Likely code movement out of `main.py`

The pilot should move logic, not just wrap it.

Candidates to relocate behind the SDK boundary:

- emit target resolution
- payload part parsing / message assembly
- observer flag resolution as used by emit
- vertex-scoped observer application
- emit validation against observer grants
- store path resolution for emit
- dry-run fact construction path
- entity-ref enrichment

The CLI should retain only:
- argparse wiring
- error formatting
- output formatting

## Desired CLI shape after extraction

```python
def cmd_emit(args, *, vertex_path=None):
    req = EmitRequest(
        target=vertex_path or args.vertex,
        kind=args.kind,
        parts=tuple(args.parts),
        observer=args.observer,
        dry_run=args.dry_run,
    )
    try:
        result = sdk_emit(req)
    except LoopsSDKError as e:
        show_error(e)
        return 1
    return render_emit_result(result, dry_run=args.dry_run)
```

## Test migration plan

### Current test shape
`apps/loops/tests/test_emit.py` mixes several concerns:
- CLI syntax
- semantic emit behavior
- store persistence
- entity-ref logic
- observer resolution behavior

### Target test shape

#### SDK tests
New or migrated tests should focus on:
- request -> result behavior
- error semantics
- store side effects
- entity refs
- observer resolution/scoping/validation

These tests should not need full CLI invocation unless command syntax itself matters.

#### CLI tests
Keep a smaller number of tests for:
- argv parsing
- `--dry-run` shell output shape
- exit codes / stderr mapping
- user-facing syntax guarantees

## Expected benefits

### For the codebase
- slimmer `main.py`
- one canonical emit implementation
- easier future extraction of read/population/sync

### For tests
- easier direct semantic tests
- fewer environment-heavy CLI tests
- clearer boundary between command syntax and app behavior

### For a future workspace SDK
A `LoopsWorkspace` or similar test harness becomes much cleaner once it can call
`sdk.emit()` instead of `main([...])` for non-CLI assertions.

## Follow-on extractions if emit succeeds

1. `population`
2. `read`
3. `sync`

That order is deliberate:
- `population` has high setup boilerplate and should benefit quickly
- `read` is easier once result/render boundaries are better established
- `sync` likely benefits from patterns proven by the first two

## What success looks like

The pilot is successful if:

- `cmd_emit` becomes visibly thinner
- `test_emit.py` can be split between SDK tests and true CLI tests
- target resolution and observer logic are centralized instead of scattered
- the extracted API looks like something future automation could plausibly use

## Non-goal reminder

This pilot should not chase abstraction for its own sake. The point is to create a
clean semantic seam that simplifies both the CLI and the tests, while preserving
current behavior.
