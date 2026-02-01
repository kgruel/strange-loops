# Fold Expressiveness: Analysis and Recommendation

Research into the gap between declarative folds and custom Python folds.

---

## Current Declarative Folds

The DSL provides 8 fold primitives in `libs/data/src/data/fold.py`:

| Fold | Target Type | Operation | DSL Syntax |
|------|-------------|-----------|------------|
| `Latest` | float | Store event timestamp | `latest` |
| `Count` | int | Increment counter | `+1` |
| `Sum` | numeric | Add field to accumulator | `+ field` |
| `Collect` | list | Append to bounded list | `collect N` |
| `Upsert` | dict | Insert/update by key | `by field` |
| `TopN` | dict | Keep top N by field | — |
| `Min` | numeric | Track minimum | `min field` |
| `Max` | numeric | Track maximum | `max field` |

These cover basic accumulation patterns. The engine (`engine.py`) compiles them
to closures that mutate state in place.

---

## Custom Folds in Experiments

Analyzed 35+ custom fold functions across experiments. Complete catalog:

### Category A: Expressible with Current Primitives (13 folds)

These could be written declaratively but use Python for clarity or history:

| Fold | File | What It Does | Declarative Equivalent |
|------|------|--------------|----------------------|
| `heartbeat_fold` | cascade.py | Count +1 | `Count("count")` |
| `heartbeat_fold` | multi_source.py | Count +1 | `Count("count")` |
| `heartbeat_fold` | network_boundary.py | Count +1, latest ts | `Count + Latest` |
| `count_fold` | observer_flow.py | Return state + 1 | `Count` |
| `sum_fold` | observer_flow.py | Sum value field | `Sum("total", "value")` |
| `collect_fold` | observer_flow.py | Append payload | `Collect` |
| `batch_fold` | summary.py | Count +1 | `Count` |
| `count_fold` | nested_flow/viz.py | Return state + 1 | `Count` |
| `collect_fold` | nested_flow/viz.py | Keep last 10 | `Collect(10)` |
| `health_fold` (simple) | observe.py | Upsert status by container | `Upsert("statuses", "container")` |
| `ack_fold` | observe.py | Upsert by container | `Upsert` |
| `keys_fold` | observe.py | Collect last 20 | `Collect(20)` |
| `alert_fold` | alert_automation.py | Append to list | `Collect` |

**Pattern**: Many Python folds exist because the DSL wasn't available when
the experiment was written, or for pedagogical clarity.

### Category B: Missing Primitives (5 folds)

Operations that could be primitive but aren't:

| Fold | File | What It Does | Proposed Primitive |
|------|------|--------------|-------------------|
| `pulse_fold` | cadence_viz.py | Sliding window of intervals | `Window(N)` |
| `pulse_fold` | cadence_viz.py | Stddev of intervals (jitter) | `Stddev("jitter", "interval")` |
| `pulse_fold` | cadence_viz.py | Running average | `Avg("avg_rate", "interval")` |
| `selection_fold` | peer_focus.py | Toggle in set | `Toggle("items", "item")` |
| `focus_fold` | peer_focus.py | Replace entire state | `Replace` or `Latest` variant |

**Analysis**:
- **Window**: Different from `Collect` — maintains time-ordered buffer for rate/jitter
- **Stddev/Avg**: Statistical aggregations on windowed data
- **Toggle**: Bidirectional set operation (add if absent, remove if present)
- **Replace**: Overwrite state with payload (not just a field)

### Category C: Derived/Computed Metrics (6 folds)

Combine multiple fields or do arithmetic beyond single-field aggregation:

| Fold | File | What It Does | Why Not Declarative |
|------|------|--------------|---------------------|
| `breath_fold` | cadence_viz.py | avg_rate from windowed rates, drift from target | Arithmetic: `avg - constant` |
| `minute_fold` | cadence_viz.py | Variance, health score | Formula: `1.0 - rate_error - variance*10` |
| `summary_fold` | cascade.py | Sum from tick payload field | Cross-kind aggregation |
| `tick_summary_fold` | network_boundary.py | Count ticks, sum total | Multi-field derived |
| `health_summary_fold` | summary.py | Aggregate from tick payload | Tick-to-fact transformation |
| `review_summary_fold` | summary.py | Union of peers_seen | Set union from payload |

**Pattern**: These require access to computed intermediate values (avg, variance)
or constants (target rate, threshold). Not single-field operations.

### Category D: Stateful/Conditional Logic (6 folds)

Operations that need conditional branching or complex state transitions:

| Fold | File | What It Does | Why Not Declarative |
|------|------|--------------|---------------------|
| `incident_fold` | tick_since.py | Branch on payload._kind | Conditional routing |
| `counter_fold` | cells_vertex.py | Undo support (pop history) | Bidirectional mutation |
| `deploy_fold` | fleet.py | Track stage progression | Conditional field update |
| `collect_fold` | boundary.py | Nest under origin→kind | Dynamic key structure |
| `disk_fold` | alert_automation.py | Parse + upsert combined | Parsing logic |
| `load_fold` | multi_source.py | Parse load average | String parsing |

**Pattern**: Business logic that can't be expressed as data transformation.
Parsing, conditionals, undo, dynamic nesting.

### Category E: Domain/Infrastructure Logic (7 folds)

Pure domain logic that shouldn't be declarative:

| Fold | File | What It Does |
|------|------|--------------|
| `fold_disk` | system_health.py | Parse df output + upsert |
| `fold_proc` | system_health.py | Parse ps output + top-N |
| `parse_disk` | system_health_spec.py | Line parsing |
| `process_fold` | system_health_parse.py | Sort + trim to top-N |
| `health_fold` (complex) | network_observer.py | Track last_observer in payload |
| `connection_fold` | network_observer.py | Nested dict with metadata |
| `log_fold` | presentation/lens_code.py | Append + by_level counter |

**Pattern**: Parsing raw data, maintaining sorted structures, complex nesting.
These are inherently imperative.

---

## Quantified Breakdown

| Category | Count | Percentage | Recommendation |
|----------|-------|------------|----------------|
| A: Expressible Now | 13 | 35% | Migrate to declarative |
| B: Missing Primitives | 5 | 14% | **Consider adding** |
| C: Derived Metrics | 6 | 16% | Keep as Python |
| D: Stateful Logic | 6 | 16% | Keep as Python |
| E: Domain Logic | 7 | 19% | Keep as Python |

**Key Insight**: 35% of custom folds are already expressible declaratively.
Another 14% could be with 3-4 new primitives. The remaining 51% require Python
and should stay that way.

---

## Prior Art: How Others Handle This

### Apache Flink
- **Approach**: Rich built-in aggregations (sum, min, max, count) + window operators
- **Extension**: ProcessFunction for stateful computation, custom aggregators
- **Lesson**: Separates "what most people need" from "escape hatch for complex cases"

### Kafka Streams
- **Approach**: Built-in aggregations (count, reduce, aggregate) + state stores
- **Extension**: Processor API for arbitrary transformations
- **Lesson**: Two-tier model — high-level DSL, low-level Processor API

### ksqlDB
- **Approach**: SQL aggregates (SUM, AVG, COUNT, etc.) + UDAF for custom
- **Extension**: User-defined aggregate functions in Java
- **Lesson**: Declarative covers 80%, custom code for the rest

**Common Pattern**: All systems separate "common aggregations" from "custom logic"
with an explicit escape hatch. None try to make the declarative layer cover everything.

---

## Proposed New Primitives

Based on Category B analysis, consider adding:

### 1. `Avg` — Running Average
```python
@dataclass(frozen=True)
class Avg:
    target: str      # State field for the average
    field: str       # Payload field to average
    count: str       # State field for count (needed for incremental avg)
```

**Rationale**: Common in rate/latency tracking. Currently requires manual
sum/count and division.

### 2. `Window` — Sliding Window Buffer
```python
@dataclass(frozen=True)
class Window:
    target: str      # State field (list)
    field: str       # Payload field to collect
    size: int        # Window size
```

**Difference from Collect**: Window drops oldest when full (FIFO), not
just bounded append. Essential for rate/jitter calculation.

### 3. `Toggle` — Set Toggle
```python
@dataclass(frozen=True)
class Toggle:
    target: str      # State field (set)
    key: str         # Payload field for item
```

**Rationale**: Selection state in UIs. Add if absent, remove if present.

### 4. `Replace` — Overwrite State
```python
@dataclass(frozen=True)
class Replace:
    # No parameters — entire payload becomes state
    pass
```

**Rationale**: For focus/scroll where new value completely replaces old.
Currently: `return {"index": payload.get("index", 0)}` — could be `Replace`.

### Not Proposed

- **Stddev/Variance**: Too specialized. Keep as Python with Window providing the buffer.
- **Delta**: Requires previous value tracking, complicates state shape.
- **Conditional**: Opens Pandora's box. Stay in Python.

---

## Recommendation: Extend Conservatively

**Option A (Recommended)**: Add `Avg` and `Window`, keep the rest in Python.

**Rationale**:
1. These two cover the most common "almost declarative" cases
2. `Toggle` and `Replace` are UI-specific — smaller audience
3. Derived metrics (Category C) genuinely need Python
4. The escape hatch (custom fold function) is well-understood

### DSL Syntax If Extended

```
# Current
folds:
  +1 events
  + amount total
  by id items
  collect 10 history
  max value peak

# With Avg and Window
folds:
  avg interval rate         # Avg(target="rate", field="interval")
  window 10 interval        # Window(target="interval", field="interval", size=10)
```

### Migration Path

1. Add `Avg` and `Window` to `fold.py`
2. Add engine compilation in `engine.py`
3. Document in DSL spec
4. Migrate Category A folds to declarative (optional, not urgent)

---

## Summary

| Question | Answer |
|----------|--------|
| What percentage of custom folds could be declarative? | 35% now, 49% with 2 new primitives |
| Should we extend declarative folds? | Yes, conservatively: `Avg` and `Window` |
| Where's the boundary? | Statistical aggregation = declarative; Arithmetic/conditionals = Python |
| Is the escape hatch right? | Yes. Custom fold function is the intended path for complex cases |

The current design is sound. Declarative folds handle simple aggregation.
Python handles everything else. The gap is small and can be narrowed with
two primitives that have clear semantics.
