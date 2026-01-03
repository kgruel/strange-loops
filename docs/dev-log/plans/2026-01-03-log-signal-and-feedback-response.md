---
status: completed
updated: 2026-01-03
---

# Log Signal and Feedback Response

Address critical feedback on ev's design, primarily by introducing structured signals within the log primitive.

## Background

External review identified several limitations. After discussion, we resolved each point and identified one significant enhancement: the `log_signal` convention for structured domain observations.

### Criticisms and Resolutions

| # | Criticism | Resolution |
|---|-----------|------------|
| 1 | Python 3.13+ requirement limits adoption | Lower to >=3.11 (no 3.13 features used) |
| 2 | Rich Live displays not possible | Already documented in `docs/patterns/live-emitter.md`; clarify reference emitters are minimal |
| 3 | Closed event kinds prevent extensibility | Add `log_signal` convention (see below) |
| 4 | Input handling requires manual event emission | Intentional; document rationale |
| 5 | Stdlib logging bypassed | Add logging bridge pattern doc |
| 6 | Immutability overhead | No action (2µs/event is fine for CLI) |

### Why log_signal, Not a 6th Primitive

We considered adding `signal` as a new EventKind. Rejected because:

- Primitives should stay frozen ("black-style minimal")
- Signals and narrative logs share the property of being transient information
- Convention-based extension is reversible; new primitives are not
- The design rule ("add primitive only if renderer can't work without it") is satisfied by reserved key

If log_signal proves awkward in practice, we can add Signal as a primitive later.

## The log_signal Design

### Two Lanes Within Log

**Lane 1: Narrative**
- Human-first prose
- May be suppressed freely (`--quiet`)
- Not stable for parsing (wording can change)
- `data` optional and informational only

**Lane 2: Signal (structured observation)**
- Machine-meaningful, stable identifiers
- `data["signal"]` contains the signal name
- Rest of `data` contains structured attributes
- `message` optional and non-authoritative (display-only)

### Reserved Key Convention

```python
Event.log_signal("stack_status", stack="media", healthy=True)
# Produces:
# Event(kind="log", data={"signal": "stack_status", "stack": "media", "healthy": True})
```

Renderer detection: `"signal" in event.data`

### Signal Naming Rules

- Lowercase snake_case: `connection_established`
- Names are stable identifiers, not sentences
- Scope prefix if needed: `deploy.stack_status`
- Versioning only if truly breaking: `stack_status_v2` (rare)

### Signal Attribute Rules

- Values must be JSON-serializable
- Avoid deep nesting
- No blobs (if it's big, it's an artifact)
- No numbers-that-should-be-metrics

Examples:
- `healthy=True` — state fact
- `stack="media"` — identifier
- `attempt=2` — counter (if not a metric)
- `duration=2.3` — use metric instead
- `path="/tmp/out.txt"` — use artifact if it was produced
- `percent=50` — use progress instead

### Four Primitives First Rule

Before using log_signal, check:
- Is it a durable output? → `artifact`
- Is it a number you'd graph/compare? → `metric`
- Is it advancement toward completion? → `progress`
- Is it a human decision? → `input`

Only if none apply → `log_signal`

## Implementation Tasks

### 1. Python Version (quick)

- [ ] Lower `requires-python` to `">=3.11"` in pyproject.toml
- [ ] Update `tool.ruff.target-version` to `"py311"`
- [ ] Update `tool.ty.environment.python-version` to `"3.11"`

### 2. log_signal Factory

- [ ] Add `Event.log_signal(name: str, *, level: EventLevel = "info", message: str = "", ts: float | None = None, **data) -> Self`
- [ ] Validate `name` is not empty
- [ ] Raise `ValueError` if `signal` passed as kwarg (reserved)
- [ ] Add tests for factory
- [ ] Add tests for reserved key protection

### 3. Documentation: Signal Concept

Create `docs/concept/signal.md`:
- [ ] Two-lane explanation (narrative vs signal)
- [ ] Signal naming conventions
- [ ] Attribute guidelines
- [ ] Four primitives first rule
- [ ] Renderer treatment guidelines
- [ ] Examples (good and bad)

### 4. Documentation: Update Existing

- [ ] `docs/concept/log.md` — add two-lane description, link to signal.md
- [ ] `docs/concept/README.md` — add signal to the concept index
- [ ] `docs/patterns/live-emitter.md` — update example from artifact to log_signal
- [ ] README or docs intro — clarify reference emitters are minimal examples

### 5. Documentation: New Patterns

- [ ] Create `docs/patterns/logging-bridge.md` — stdlib logging → ev bridge
- [ ] Update `docs/concept/input.md` — document "recording only" rationale

### 6. Optional: Reference Emitter Polish

- [ ] Consider terse signal formatting in PlainEmitter
- [ ] Consider signal grouping in RichEmitter
- [ ] Not required for v1

## Design Decisions Captured

Document in `docs/design-decisions.md` or similar:
- Why log_signal instead of Signal primitive
- The "four primitives first" rule
- Signal naming conventions rationale

## Testing Strategy

- Unit tests for `Event.log_signal()` factory
- Test reserved key protection (`signal` kwarg raises)
- Test that signals serialize correctly via `to_dict()` / `from_dict()`
- Existing emitter tests should pass (signals are just logs)

## Success Criteria

- Python 3.11+ users can install ev
- Developers can emit structured domain observations without abusing artifact
- Renderers can reliably distinguish narrative from signal
- Documentation clearly explains the two-lane model
- Live-emitter pattern uses log_signal (not artifact) for transient status
