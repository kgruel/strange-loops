# metric

*A quantitative fact about a CLI run in machine-usable form.*

## What It Represents

A metric is a number with context — a quantitative observation about the run that has meaning beyond presentation.

Typical examples:
- Duration
- Count
- Size (bytes)
- Retries
- Failures / successes
- Resources processed
- Warnings encountered

Things you otherwise end up:
- Printing in prose
- Burying in logs
- Recomputing later
- Losing in JSON mode

## What Metric Events Look Like

Minimal structure: `name`, `value`, optional `unit`.

**Duration metric:**
```python
Event(
    kind="metric",
    message="Backup duration",
    data={
        "name": "duration",
        "value": 12.4,
        "unit": "seconds"
    }
)
```

**Count metric:**
```python
Event(
    kind="metric",
    message="Services restarted",
    data={
        "name": "services",
        "value": 8
    }
)
```

**Size metric (no message needed):**
```python
Event(
    kind="metric",
    data={
        "name": "bytes_written",
        "value": 18374629
    }
)
```

That's it. Name, value, optional unit.

## Metric vs Progress

This is the key distinction:

| Aspect | Progress | Metric |
|--------|----------|--------|
| Question answered | "Are we getting there?" | "What did it cost?" |
| Time-indexed | Yes | Sometimes |
| Ongoing | Yes | Usually no |
| Indicates "how far" | Yes | No |
| Indicates "how much" | No | Yes |
| Changes over time | Yes | No (usually) |

**Progress** is about the journey.
**Metric** is about the receipt.

They complement each other.

## Why Not Just `log`?

A log message like:

```
"Processed 512 files in 12 seconds"
```

Looks human-friendly… and is machine-hostile.

You can't:
- Chart it
- Compare runs
- Alert on it
- Extract it reliably

Metrics give structure where prose gives ambiguity.

## Why Not `Result.meta`?

You might put metrics in `Result.meta` or `Result.data`. That works for final summaries — but fails for:

- Streaming metrics (emitted during the run)
- Partial failures
- Multiple phases
- Long-running tasks
- CI observability

Metrics deserve to exist independently of the final outcome.

## What Metrics Unlock

### 1. Consistent Summaries

Renderers can:
- Auto-group metrics
- Format units
- Hide/show based on verbosity
- Display compact "stats" panels

Without every command hand-crafting summaries.

### 2. Automation & CI Value

Automation can:
- Fail builds if duration > threshold
- Compare run-to-run changes
- Collect stats across tools

All without scraping logs.

### 3. UX Polish Without Domain Work

A Rich renderer might:
- Show metrics at the end in a clean block
- Highlight regressions
- Collapse them by default

A Plain renderer might:
- Print one-line summaries

Same facts. Different views.

### 4. Testing Without Guesswork

Tests can assert:
- "duration metric exists"
- "processed count == expected"
- "retry count == 0"

Instead of brittle text matching.

## Metric in Non-Interactive & JSON Modes

Metrics shine here.

In CI:
- Progress is noise
- Input doesn't exist
- Artifacts may be secondary

Metrics + Result are often the entire value of the run.

## Boundaries

To keep it minimal and safe:

- ❌ No aggregation logic
- ❌ No thresholds
- ❌ No alerting
- ❌ No time-series storage
- ❌ No cross-run comparison

It records facts, not analysis.

## Why It Earns Its Place

Ask: *If we remove metric as a primitive, can renderers and automation still do the right thing reliably?*

The answer is **no**:
- Metrics get buried in prose
- Structure is lost
- UX becomes inconsistent
- Automation requires parsing

So metric earns its slot.

## The Complete System

Five primitives that cover the entire lifecycle of a run:

| Primitive | Answers |
|-----------|---------|
| `input` | Why behavior diverged |
| `progress` | How work advanced |
| `artifact` | What durable outputs exist |
| `metric` | What it cost / how much happened |
| `log` | Everything else |

Plus `Result`: What was the outcome?

This is the smallest set that tells the full story of a run.
