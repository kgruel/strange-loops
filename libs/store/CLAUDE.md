# store — maintenance operations

Slice, merge, search, transport for vertex store databases. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  store (maintenance)
Fact, Spec        SqliteStore writes    slice/merge/search reads
```

Below: `libs/engine/` provides `SqliteStore` (write path) and `StoreReader` (read path). This lib operates on the same SQLite databases but for bulk maintenance — extracting subsets, combining stores, cross-DB queries.

---

## Level 0 — Slice and merge

**Trigger**: I need to extract a subset of a store or combine two stores.

```python
from store import slice_store, merge_store

# Extract decisions from the last week into a standalone store
result = slice_store(
    source=Path("data/project.db"),
    target=Path("data/decisions-week.db"),
    kinds=["decision"],
    since=datetime(2025, 2, 22),
)
# SliceResult(facts=12, ticks=0, size_bytes=8192)

# Merge another store into ours (dedup on ULID)
result = merge_store(
    target=Path("data/project.db"),
    source=Path("data/imported.db"),
)
# MergeResult(facts_added=5, facts_skipped=3, ticks_added=2, ticks_skipped=0)
```

**Slice filters**: `since`, `before` (time), `kinds` (exact + prefix match), `observers`, `origins`. Ticks filtered by time only. Target must not exist (no accidental overwrite).

**Merge dedup**: `INSERT OR IGNORE` on ULID primary key. Same fact across stores has the same ULID — globally unique IDs make dedup trivial. `dry_run=True` computes counts without committing.

---

## Level 1 — Understand the schema

**Trigger**: I need to know how this differs from engine's SqliteStore.

| Concern | engine.SqliteStore | store |
|---------|-------------------|-------|
| PK | `rowid INTEGER` (auto-increment) | `id TEXT DEFAULT (ulid())` |
| Purpose | Runtime append-only writes | Bulk maintenance operations |
| Operations | append, since, between | slice, merge, search, transport |

The ULID schema is what makes cross-DB operations work — same fact in two stores has the same ID, so merge is just `INSERT OR IGNORE`.

```sql
facts(id TEXT PK DEFAULT (ulid()), kind, ts, observer, origin, payload CHECK json_valid)
ticks(id TEXT PK DEFAULT (ulid()), name, ts, since, origin, payload CHECK json_valid)
```

Internally, `_conn.py` handles: `sqlite-ulid` extension loading, schema creation, WAL mode, read-only URI connections. All cross-DB work uses `ATTACH DATABASE` (no Python round-trip).

## Build & test

```bash
uv run --package store pytest libs/store/tests
```
