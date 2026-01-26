# progress

*Time-indexed measurements of ongoing work, emitted as facts and interpreted by renderers.*

## What It Represents

A measurement of how far along work is at a point in time:

```python
Event(
    kind="progress",
    message="Downloading images",
    data={
        "current": 37,
        "total": 100
    }
)
```

Or a step-based variant:

```python
Event(
    kind="progress",
    message="Running migrations",
    data={
        "current": 3,
        "total": 10,
        "unit": "migrations"
    }
)
```

These events say:
- Work is ongoing
- Here is how far along we are right now

They do NOT say:
- Show a spinner
- Redraw the screen
- Overwrite the last line

That's renderer territory.

## Progress vs Input: The Crucial Difference

Both are modeled as facts. Both are renderer-agnostic, serializable, replayable. But they mean different things:

| Aspect | Input | Progress |
|--------|-------|----------|
| Nature | Decision | Measurement |
| Affects behavior | Yes | No |
| Branching logic | Yes | No |
| Required for correctness | Often | No |
| Required for UX | Yes | Yes |
| Replay meaning | Decision replay | Timeline replay |

**Input** captures a human decision point — a branch in behavior, a consent, a choice that affects outcome. Once it happens, it is historical and immutable.

**Progress** captures a measurement over time — how far along something is, how much work remains, that time is passing. Progress does not affect behavior. It only affects perception.

Put simply:
- Progress tells you *how* the sausage was made
- Input tells you *why* it ended up the way it did

## What It Is NOT

Most CLIs treat progress as rendering instructions:
- "draw a spinner"
- "update a bar"
- "print dots"

Those are rendering strategies, not facts.

The fact is:
- 37% complete
- step 3 of 10
- copying file X of Y
- task A finished, task B started

If you don't record that fact:
- JSON output has nothing meaningful
- Plain mode degrades poorly
- Logs become unstructured noise
- Renderers can't adapt intelligently

## How Renderers Interpret Progress Facts

Different renderers make different choices from the same facts:

| Renderer | Behavior |
|----------|----------|
| Rich | Animated progress bar, nested task trees, spinners with ETA |
| Plain | Occasional text updates, "step 3/10", or nothing at all |
| JSON | Emit JSONL events, or ignore intermediate progress, or summarize in result meta |
| Audit | Timestamped progress entries |

The domain logic doesn't care which renderer is active.

## Progress and Non-Interactive Runs

In non-interactive mode, progress facts can still be emitted:
- Renderer may suppress visual updates
- JSON mode may still record them
- Metrics like duration are still computable

The fact stream stays the same regardless of output mode.

## Why It Earns Its Place

You could technically shove progress into `log` events. But that breaks composability:
- Renderers can't reliably detect "this is progress"
- ETA calculations become impossible
- Deduplication/throttling is harder
- Nested progress becomes guesswork

So `progress` gets a dedicated kind.

### The Mental Test

Ask: *If I replayed this run without a UI, would this information still be meaningful?*

- Input? Yes.
- Progress? Yes.
- Spinner glyphs? No.

That's the line.

## Minimal by Design

To avoid scope creep, progress events in v1 are:
- **Stateless** — no "start/stop" lifecycle
- **No hierarchy** — no nested task trees in the contract
- **No cancellation semantics** — just measurements

Just: "here's how far along we are right now."

Everything else is derived by renderers.

## Recommended Data Fields

Progress events use `Event.data` for structured information. These fields are conventions, not requirements:

| Field | Type | Description |
|-------|------|-------------|
| `current` | int/float | Current value |
| `total` | int/float | Total value (for percentage calculation) |
| `unit` | str | What's being counted ("files", "bytes", etc.) |
| `phase` | str | Named phase identifier |
| `status` | str | "running" / "ok" / "error" |

### Examples

**Percentage progress:**
```python
Event.progress("Downloading", current=37, total=100, unit="files")
```

**Phase transitions:**
```python
Event.progress("Build complete", phase="build", status="ok")
```

**Indeterminate (spinner-worthy):**
```python
Event.progress("Scanning repository", phase="scan", status="running")
```

These are conventions in `Event.data`, not enforced by facts.

### Hierarchical Progress

For nested task trees (GitHub Actions-style workflows), see the `ProgressTree` pattern in ev-toolkit. This keeps facts' core minimal while providing a blessed pattern for complex workflows.
