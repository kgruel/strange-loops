# Result

*The final, authoritative, renderer-agnostic verdict and payload of a CLI run.*

## What It Represents

A Result is the **contractual truth** of a CLI run — the one thing a consumer can rely on:

- In scripts
- In CI
- In tests
- In automation
- In renderers

Everything else (events) is supporting evidence.

## What It Is NOT

**❌ Not a log summary**

It isn't "a nice sentence at the end." It must be structured first, sentence second.

**❌ Not a stream**

It's one object, produced once, at end-of-run.

**❌ Not a dump of everything**

If Result becomes "every event but nested," you lose:
- Streaming value
- Clarity
- Stability
- Composability

**❌ Not a policy object**

Result should not contain:
- "should we show spinners"
- "color is enabled"
- "tty width"

That's renderer policy.

**❌ Not a UI description**

No Rich objects, markup, layouts, icons.

## Why Result Is Special

Events can be:
- Filtered
- Reordered (within reason)
- Suppressed in quiet mode
- Dropped in JSON mode (sometimes)

**Result must never be optional.**

If you only keep one thing, you keep Result.

Because Result is what makes:
- Exit codes predictable
- JSON output stable
- "Automation-friendly" actually true

## What Result Must Answer

1. Did it succeed?
2. How should the process exit?
3. What's the minimal human summary?
4. What structured data is the "output" of this command?
5. What minimal metadata helps interpret the output?

## Creating Results

Use factory methods (preferred):

```python
Result.ok("3/3 healthy", data={"stacks": [...]})
Result.error("Connection failed", code=2, data={"host": "media"})
```

Or the raw constructor (escape hatch):

```python
Result(status="ok", summary="Done")
Result(status="error", code=1, summary="Failed")
```

### Invariants

Results enforce status/code consistency:
- `status="ok"` requires `code=0`
- `status="error"` requires `code != 0` (default: 1)

```python
Result.ok("Done")              # code=0 automatically
Result.error("Failed")         # code=1 by default
Result.error("Failed", code=2) # custom error code
```

### Helper Properties

```python
if result.is_ok:
    print("Success!")
if result.is_error:
    print(f"Failed with code {result.code}")
```

## The Minimal Fields (v1)

Black-style minimal — the absolute minimum:

```python
Result(
    status="ok",              # ok | error (use Result.ok() / Result.error())
    code=0,                   # exit code (enforced by invariants)
    summary="3/3 healthy",    # short human sentence
    data={...},               # structured payload
    meta={...},               # optional boring facts
)
```

**`data` is the extensibility valve.** You do NOT add new top-level fields lightly.

### status vs code

Why both?

| Field | Consumer | Purpose |
|-------|----------|---------|
| `status` | Renderers, logic | Semantic meaning |
| `code` | Shells, CI | Unix exit semantics |

`status` drives meaning; `code` drives exit behavior.

### summary

Exists because:
- Humans need a one-line truth
- JSON consumers often want a human-readable message
- Renderers need a default headline

But summary must be treated as **stable intent, not stable phrasing**.

**Rule: Never put parseable values in summary.**

### data

The structured "return value" of the command:
- The thing JSON mode prints
- The thing tests assert on
- Domain output, not event history

Examples:
- Inventory lists
- Health check findings
- IDs of created resources
- Computed config

**Important boundary:** `data` should be domain output, not event history. If the user wants the "transcript," that's events.

### meta

Cross-cutting facts that are useful but not core output:
- Duration
- Counts
- Timing
- Run ID
- Host
- Versions

This prevents people from jamming metadata into logs.

**Rule: `meta` is for interpretation, not for primary results.**

## Result and Events: How They Relate

Think of **Events as the run's story**.
Think of **Result as the run's verdict**.

### Allowed Duplication

Result can repeat a small amount of info for convenience:
- Final duration
- Counts
- Top-level artifact references (optional)

But it should never embed the entire event stream.

**Rule: Results may summarize; they may not transcript.**

## Error Modeling

Keep it minimal. Instead of adding `error_message`, `error_code`, `stacktrace`, `hint` as top-level fields, keep errors in `data`:

```python
Result.error(
    "Version mismatch",
    data={
        "error": {
            "code": "VERSION_MISMATCH",
            "message": "Expected 2.0.0, found 1.8.3",
            "hint": "Run 'update' to upgrade",
            "details": {...}
        }
    }
)
```

You don't explode the top-level schema.

**Hard rule: Stack traces are not Result — they are debug logs or artifacts.**

## The "changed" Question

In ops/infra contexts, `changed` is central. Two options:

**Option A (Black-style minimal):** Convention, not primitive
```python
data={"changed": True, "effects": [...]}
```

**Option B:** Reserved top-level field (if this becomes ops-focused)

Either is defensible. If you want maximum minimality, treat it as a convention and freeze that decision early.

## Guardrails

These rules prevent Result from becoming garbage:

### Rule 1: Result must be serializable

No objects, no bytes, no Rich, no exceptions.

### Rule 2: Result must be stable

No "sometimes dict, sometimes list, sometimes string" at top level. Always the envelope.

### Rule 3: Result must be authoritative

If something matters to automation, it must appear in Result (typically in `data`).

### Rule 4: Result must be minimal

If a field can live in `data` or `meta`, it does. Top-level is sacred.

### Rule 5: Result must not include the transcript

No event list nested inside it.

## Why This Works

When Result is clean:
- Logs can be noisy and still safe
- Progress can be optional
- Artifacts can stream
- Metrics can accumulate
- JSON output stays coherent
- Rich output stays beautiful

**Result is what keeps the contract from becoming "just a fancy printer."**

## The Complete Picture

```
Events (streaming)          Result (final)
─────────────────          ──────────────
log      → narrative       status  → did it work?
progress → advancement     code    → exit behavior
artifact → outputs         summary → human headline
metric   → measurements    data    → structured payload
input    → decisions       meta    → interpretation context
```

Events are the story. Result is the verdict.
