---
status: completed
updated: 2026-01-03
---

# Event.topic Property

Bring the `Event.topic` property from ev-llm-experiment into ev core, with documentation updates.

## Origin

Developed in `~/Code/ev-llm-experiment` as part of LLM-first docstrings exploration. The experiment tested whether `Event.topic` and structured docstrings reduce agent cold-start tax. While the full LLM-first docstrings experiment had mixed results, the architectural work—specifically `Event.topic` and the "two-lane" concept—is sound and valuable independently.

## The Problem: Asymmetry

ev has two conventions for "subtyped" events:

| Event Type | Kind | Subtype Location |
|------------|------|------------------|
| Artifact | `"artifact"` | `data["type"]` |
| Signal | `"log"` | `data["signal"]` |

This asymmetry complicates tooling:
- Artifacts: identified by `event.data.get("type")`
- Signals: identified by `event.signal_name` (which reads `data["signal"]`)

Two patterns instead of one queryable surface.

## The Solution: Event.topic

A canonical namespaced identifier that unifies the asymmetry:

```python
@property
def topic(self) -> str:
    """Canonical namespaced identifier for linting/manifest/tooling.

    Returns a stable string that uniquely identifies the event type:
    - artifact:<type> for artifact events (e.g., "artifact:deployment_record")
    - signal:<name> for signal events (e.g., "signal:stack_status")
    - <kind> for other events (e.g., "log", "progress", "metric", "input")

    This is what linters and tooling operate on, not factory names.
    """
    if self.kind == "artifact":
        return f"artifact:{self.data.get('type', 'unknown')}"
    if self.is_signal:
        return f"signal:{self.signal_name}"
    return self.kind
```

| Event | Topic |
|-------|-------|
| `Event.artifact("deployment_record", ...)` | `artifact:deployment_record` |
| `Event.log_signal("stack_status", ...)` | `signal:stack_status` |
| `Event.log("message")` | `log` |
| `Event.progress(...)` | `progress` |
| `Event.metric(...)` | `metric` |
| `Event.input(...)` | `input` |

## Design Decision: Path A

We chose **Path A** (add `Event.topic`) over **Path B** (make signal a 6th EventKind).

**Rationale:**
1. **Preserves reversibility** — primitives stay frozen
2. **Localizes asymmetry** — `topic` becomes the single canonical surface
3. **No breaking change** — additive property
4. **Solves tooling need** — linting, manifests, filtering

**When Path B becomes justified:**
- Multiple emitters all special-case signals and the compound predicate becomes a footgun
- Signals need distinct lifecycle/policies that can't be implemented as "log subtype"
- Third-party emitters mis-implement the convention

## Two-Lane Model

The `log` kind serves two distinct purposes:

**Lane 1: Narrative Logs** — Human-first prose
```python
Event.log("Connecting to server...")
Event.log("Retrying in 5 seconds", level="warn")
```

**Lane 2: Signals** — Structured observations
```python
Event.log_signal("stack_status", stack="media", healthy=True)
Event.log_signal("connection_established", host="db.local")
```

Emitters render these distinctly:
- Narrative: level-based styling, prose message
- Signals: structured `name key=value` format (already implemented in v0.5.0)

## Insights from ev-llm-experiment

From the implementation log:

1. **Rich markup interpretation** — Test values like `db.local` trigger Rich's automatic styling. Use plain test values (`myhost`) to avoid false positives.

2. **Signal attribute ordering** — `event.data.items()` preserves insertion order (Python 3.7+), but dict construction order might not match user expectations. Document this.

3. **Branch coverage precision** — 100% coverage requirement caught real gaps (e.g., "signal without attributes" test written for PlainEmitter but forgotten for RichEmitter).

4. **Topic is for tooling, not automation** — Aligns with authority model: automation depends on Result, not on parsing topics.

## Deliverables

### 1. Event.topic Property

Add to `src/ev/types.py`:
- `topic` property (~15 lines)
- Tests in `tests/test_types.py`

### 2. Documentation Updates

**Update `docs/concept/signal.md`:**
- Add "Two Lanes Within Log" section (from ev-llm-experiment)
- Add signal naming conventions
- Add signal attribute guidelines
- Add "Four Primitives First" rule

**Update `docs/concept/log.md`:**
- Reference two-lane model
- Distinguish narrative logs from signals

**Add topic examples to relevant docs:**
- `docs/concept/artifact.md` — mention `artifact:<type>` topic
- Pattern docs where filtering by topic would be useful

### 3. Consider Emitter Signal Format

Currently (v0.5.0): `signal_name key=value`
ev-llm-experiment: `[signal:name] key=value`

Decision: Keep current format. The `[signal:...]` prefix is verbose and the current format is cleaner. Topic is for programmatic access, not visual rendering.

## Test Requirements

```python
class TestEventTopic:
    def test_log_topic(self):
        event = Event.log("message")
        assert event.topic == "log"

    def test_signal_topic(self):
        event = Event.log_signal("stack_status", stack="media")
        assert event.topic == "signal:stack_status"

    def test_artifact_topic(self):
        event = Event.artifact("deployment_record", id="123")
        assert event.topic == "artifact:deployment_record"

    def test_artifact_without_type_topic(self):
        # Edge case: raw Event with kind=artifact but no type
        event = Event(kind="artifact", data={})
        assert event.topic == "artifact:unknown"

    def test_progress_topic(self):
        event = Event.progress("working", percent=50)
        assert event.topic == "progress"

    def test_metric_topic(self):
        event = Event.metric("duration", 2.5)
        assert event.topic == "metric"

    def test_input_topic(self):
        event = Event.input("Continue?", response="yes")
        assert event.topic == "input"
```

## Execution Plan

1. **Implement Event.topic** — Add property and tests
2. **Update signal.md** — Add two-lane model, naming conventions, guidelines
3. **Update log.md** — Reference two-lane model
4. **Sweep other docs** — Add topic mentions where useful
5. **Verify** — pytest, ruff, coverage
6. **Version bump** — 0.6.0 (feature addition)

## Philosophy Check

**ev's design rule:** Only add a primitive if a renderer capability cannot be reliably implemented without it.

`Event.topic` is:
- Not a new primitive (property on existing Event)
- Additive (no breaking changes)
- Solves tooling need (unified queryable surface)
- Preserves reversibility (can deprecate if Path B ever makes sense)

**Verdict:** Safe addition, aligns with philosophy.

## References

- `~/Code/ev-llm-experiment/docs/dev-log/reference/llm-first-docstrings.md` — Full design context
- `~/Code/ev-llm-experiment/docs/dev-log/2026-01-03-event-topic-implementation.md` — Implementation notes
- `~/Code/ev-llm-experiment/docs/concept/signal.md` — Two-lane model source
