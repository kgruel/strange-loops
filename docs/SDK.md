# SDK / Service Layer Proposal

A programmatic SDK should become the primary semantic interface for `loops` operations.
The CLI remains important, but as an adapter: parse argv, call the SDK, render the
result. The stable thing in this system is the operation model (`emit`, `read`, `sync`,
`ls`/`add`/`rm`/`export`), not the current plumbing in `main.py`.

## Why

The current codebase already separates low-level concerns well:

- `atoms` — primitives
- `engine` — runtime + persistence
- `lang` — configuration parsing
- `painted` — rendering

What is missing is an app-level semantic layer for `loops` itself.

Today, `apps/loops` often mixes:

- target resolution
- workspace / `LOOPS_HOME` conventions
- command orchestration
- mutation / read semantics
- CLI output concerns

That makes `main.py` heavy and pushes tests to choose between low-level internals and
full CLI invocations. A service layer gives one canonical implementation of app
behavior, with CLI, tests, and future automation all consuming the same operations.

## Proposed layer

Add an internal app service package first:

```text
apps/loops/src/loops/
  sdk/
    __init__.py
    errors.py
    targets.py
    emit.py
    read.py
    population.py
    sync.py
```

Keep it in `apps/loops` initially. If it proves stable and broadly useful, it can be
promoted later to a dedicated lib.

## Responsibilities

The SDK owns:

- target resolution (`name`, path-like, local/session fallback)
- workspace / env conventions
- orchestration of app-level operations
- structured request/result types
- typed app-level errors

The SDK does **not** own:

- `argparse`
- printing to stdout/stderr
- painted rendering
- shell-oriented UX text

## Request / result model

Each verb gets typed request/result pairs.

Example:

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

The exact fields can evolve, but the rule is:

- requests are interface-agnostic
- results are structured and reusable

## Errors

Typed app-level errors should replace stringly-typed failure flow in the CLI.

```python
class LoopsSDKError(Exception): ...
class TargetNotFound(LoopsSDKError): ...
class StoreNotConfigured(LoopsSDKError): ...
class ObserverRejected(LoopsSDKError): ...
class AmbiguousTemplate(LoopsSDKError): ...
class UsageError(LoopsSDKError): ...
```

The CLI maps these to user-facing messages and exit codes.

## Rendering boundary

The SDK returns data/result objects. Rendering remains separate.

```text
CLI argv -> Request -> SDK Result -> lens / JSON / plain rendering
```

This preserves the existing architecture:

- SDK = what happened
- lenses / CLI = how it is shown

That makes the SDK usable from:

- tests
- scripts
- future automation
- possible non-CLI interfaces

## Test impact

This is the biggest payoff.

Without an SDK, tests often need to:

- create temp dirs
- write `.vertex` / `.loop` files
- set env vars
- call `main([...])`
- inspect stdout/stderr and/or stores

With an SDK, many tests can instead:

- build scenario/workspace state
- call `sdk.emit(...)` or `sdk.population.add(...)`
- assert structured results
- inspect the store only when needed

This should let the suite converge toward:

- many SDK/service tests
- fewer CLI adapter tests
- a small number of true end-to-end shell tests

## Interaction with a broader test SDK

A service layer also makes a scenario/workspace test SDK much easier.

Likely next abstraction after SDK extraction:

- `LoopsWorkspace` / `WorkspaceBuilder`
- writes vertex/source/template files
- sets `LOOPS_HOME`
- exposes helpers to call SDK operations
- provides store/output inspection helpers

These two efforts reinforce each other:

- service SDK simplifies semantics
- workspace SDK simplifies setup

## Candidate first vertical slices

### 1. `emit`
Best pilot.

Why:
- semantically crisp
- central to the app
- broad existing test surface
- exercises target resolution, observer resolution, payload parsing, store persistence

### 2. `population`
Best second slice.

Why:
- high setup boilerplate
- repeated template/target logic
- strong likely payoff for test simplification

### 3. `read`
Good later slice.

Why:
- central command
- natural request/result shape
- likely to simplify rendering boundary once emit/population are proven

## CLI after extraction

The desired CLI shape is thin:

```python
def cmd_emit(args):
    req = EmitRequest(
        target=args.vertex,
        kind=args.kind,
        parts=tuple(args.parts),
        observer=args.observer,
        dry_run=args.dry_run,
    )
    result = sdk.emit(req)
    return render_emit_result(result, args)
```

The CLI should stop being the place where semantics are invented.

## Generic offering potential

This can begin as an internal service layer and later become a supported
programmatic interface.

The key rule:

- if an abstraction models a real domain action cleanly, it can become generic
- if it only exists to make pytest convenient, keep it test-only

`engine.builder` is already evidence that this pattern can produce generally useful
APIs, not just test helpers.

## Migration principles

- extract one vertical slice at a time
- keep CLI behavior unchanged during migration
- keep rendering separate from execution
- prefer typed requests/results over ad hoc tuples/dicts at boundaries
- move semantics out of `main.py`, not just code volume

## Success criteria

The SDK extraction is successful if it:

- reduces semantic complexity in `main.py`
- makes tests target operations directly instead of shell plumbing
- creates reusable seams for scenario/workspace builders
- preserves current CLI behavior while simplifying internals
