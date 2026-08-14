# Read and Query Operations in Loops

The `libs/client` library provides headless, non-destructive read operations over Loops artifacts. It operates uniformly over `.vertex` declarations, standalone `.jsonl` append-logs, `.db` SQLite stores, and multi-store aggregate compositions (`combine`, `discover`).

All reads are point-in-time consistent and automatically verify derived index agreement via non-blocking preflight recovery.

---

## 1. API Reference Overview

```python
from client import (
    read_summary,
    read_facts,
    read_state,
    read_ticks,
    read_fact_by_id,
    search_facts,
    resolve_entity,
    read_timeline,
    sync_target,
)
```

| Operation | Purpose | Return Model |
| :--- | :--- | :--- |
| **`read_summary`** | Domain-neutral inventory of facts, ticks, kinds, and storage agreement. | `ReadSummary` |
| **`read_facts`** | Bounded witness-axis pagination with filtering and bidirectional cursors. | `FactPageResult` |
| **`read_state`** | Reconstructed fold state across declared vertex sections. | `FoldStateResult` |
| **`read_ticks`** | Chronological tick seals and cadence boundaries. | `list[dict[str, Any]]` |
| **`read_fact_by_id`** | Point lookup of a fact by canonical ULID or unambiguous prefix. | `dict[str, Any] \| None` |
| **`search_facts`** | Full-text search (FTS5) queries over payload contents. | `SearchResult` |
| **`resolve_entity`** | Resolves a domain fold-key (e.g. `task_id="T-100"`) to its canonical fact ULID. | `str \| None` |
| **`read_timeline`** | Interleaved chronological stream of facts and tick anchors. | `TimelineResult` |
| **`sync_target`** | Synchronizes derived SQLite indices and FTS tables from canonical logs. | `SyncResult` |

---

## 2. Operation Details & Examples

### `read_summary(target)`
Returns high-level storage metrics, kind distribution, attestation counts, and index agreement:

```python
from client import read_summary

summary = read_summary("project.vertex")
print(f"Total facts: {summary.fact_total}, Total ticks: {summary.tick_total}")
print(f"Attestations: {summary.signed_count} signed, {summary.unsigned_count} unsigned")
print(f"Agreement: {summary.agreement}")
for kind, stats in summary.kinds.items():
    print(f"  - {kind}: {stats['count']} events (latest: {stats['latest']})")
```

---

### `read_facts(target, ...)`
Queries facts using stable witness cursors (`WitnessPosition`):

```python
from client import read_facts

# Read first page (newest first)
page1 = read_facts("project.vertex", limit=20, kind="task", order="newest")
for fact in page1.items:
    print(f"[{fact['id']}] {fact['kind']} by {fact['observer']}: {fact['payload']}")

# Read next page using cursor
if page1.next_cursor:
    page2 = read_facts("project.vertex", limit=20, kind="task", before=page1.next_cursor, order="newest")
```

#### Pagination Cursor Rules
* **`order="newest"` (default, descending `rowid`)**: Pass the cursor to `before=cursor` to fetch older rows.
* **`order="oldest"` (ascending `rowid`)**: Pass the cursor to `after=cursor` to fetch newer rows.

---

### `read_state(target, *, kind=None)`
Replays the declared vertex folds into live materialized state:

```python
from client import read_state

state = read_state("project.vertex")
for kind, section in state.sections.items():
    print(f"Section: {kind} ({section['count']} items)")
    for item in section["items"]:
        print(f"  - {item['payload']}")
```

---

### `search_facts(target, query, *, kind=None, limit=50)`
Performs indexed full-text search against observation payloads:

```python
from client import search_facts

results = search_facts("project.vertex", query="architecture refactor", limit=10)
for match in results.matches:
    print(f"[{match.id}] (rank {match.rank:.2f}) {match.kind}: {match.payload}")
```

---

### `resolve_entity(target, kind, key, value)`
Resolves a domain entity fold-key to its canonical fact ULID:

```python
from client import resolve_entity

fact_id = resolve_entity("project.vertex", kind="task", key="task_id", value="TASK-42")
if fact_id:
    print(f"Entity TASK-42 is rooted in fact {fact_id}")
```

---

### `read_timeline(target, *, start_ts=None, end_ts=None, limit=100)`
Reads an interleaved, chronological stream of both facts and sealed ticks:

```python
from client import read_timeline

timeline = read_timeline("project.vertex", start_ts=1700000000.0, limit=50)
for event in timeline.events:
    if event.event_type == "fact":
        print(f"[FACT] {event.kind_or_name} by {event.observer}: {event.payload}")
    elif event.event_type == "tick":
        print(f"[TICK] {event.kind_or_name} sealed at {event.ts}")
```

---

### `sync_target(target)`
Synchronizes derived SQLite indices and FTS5 search tables:

```python
from client import sync_target

sync = sync_target("project.vertex")
print(f"Index status: {sync.status}, indexed {sync.indexed_facts} facts in {sync.duration_ms:.2f}ms")
```

---

### `read_ticks(target, *, name=None)` & `read_fact_by_id(target, fact_id)`
```python
from client import read_ticks, read_fact_by_id

# Retrieve all ticks or filter by cadence mark name
ticks = read_ticks("project.vertex", name="daily")

# Retrieve fact by full ULID or unique prefix
fact = read_fact_by_id("project.vertex", "01M01...")
```

---

## 3. Aggregate Vertices (`combine` & `discover`)

When target is a composite aggregate vertex (declaring `combine { ... }` or `discover { ... }`), all read operations transparently resolve member stores and merge them point-in-time:

* **Summary**: Merges fact/tick counts across all discovered member stores.
* **Facts & Search**: Merges facts across member stores with provenance labels.
* **State**: Folds member streams according to the aggregate's declaration.

---

## 4. Result Models

| Model | Schema | Key Fields |
| :--- | :--- | :--- |
| **`ReadSummary`** | `loops.cli/read-summary/v1` | `fact_total`, `tick_total`, `latest_ts`, `kinds`, `agreement`, `unfolded_kinds`, `signed_count`, `unsigned_count` |
| **`FactPageResult`** | `loops.cli/facts-page/v1` | `items`, `next_cursor`, `truncated`, `order` |
| **`FoldStateResult`** | `loops.cli/fold-state/v1` | `vertex_name`, `generation`, `sections` |
| **`SearchResult`** | `loops.cli/search-result/v1` | `query`, `matches: list[SearchResultItem]`, `total_matches` |
| **`TimelineResult`** | `loops.cli/timeline-result/v1` | `events: list[TimelineEvent]`, `start_ts`, `end_ts`, `total_events` |
| **`SyncResult`** | `loops.cli/sync-result/v1` | `target_path`, `status`, `indexed_facts`, `agreement`, `duration_ms` |
