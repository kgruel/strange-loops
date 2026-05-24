# Rung 09 — Store Maintenance & Transport

> **What you'll learn:** The SQLite schema underlying every vertex store; how to slice, merge, compact, receive, push, and pull stores; the Transport protocol and what LocalTransport does; and when the CLI's `loops store` command is the right tool vs the `store` library.
> **Prerequisites:** [Rung 03 — Persistence & Replay](03-persistence-and-replay.md), [Rung 08 — Sources & Cadence](08-sources-and-cadence.md)
> **Time:** ~20 min

Every vertex with a `store` declaration writes facts and ticks to a SQLite database. The `libs/store` library provides bulk maintenance operations on those databases — operations that are too heavy for the runtime append path but necessary for backup, sharing, archival, and cross-machine sync.

---

## The schema

All vertex stores share the same schema:

```sql
facts(
  id      TEXT NOT NULL PRIMARY KEY,   -- ULID, time-sortable, globally unique
  kind    TEXT,
  ts      REAL,                        -- epoch seconds (float)
  observer TEXT,
  origin  TEXT,
  payload TEXT CHECK (json_valid(payload))
)

ticks(
  id      TEXT NOT NULL PRIMARY KEY,   -- ULID
  name    TEXT,
  ts      REAL,
  since   REAL,                        -- tick.since: start of the period this tick summarizes
  origin  TEXT,
  payload TEXT CHECK (json_valid(payload))
)
```

Both tables use SQLite WAL mode for concurrent reads. All writers supply the `id` (ULID) explicitly — there is no SQL-level `DEFAULT` function. ULIDs are generated Python-side via `python-ulid`.

**Why ULIDs matter for maintenance.** A ULID is a 26-character time-sortable globally-unique identifier. Because the same fact has the same ULID everywhere, cross-store merge is a trivial `INSERT OR IGNORE` on the primary key. `ORDER BY id` across merged stores yields chronological interleaving because the timestamp prefix is embedded in the ID.

---

## `loops store` — the CLI view

Before reaching for the library, check whether `loops store` covers your need:

```bash
loops store project                  # dashboard: summary + recent facts + ticks
loops store data/project.db          # same, from a file path
loops store project.vertex           # same, from a .vertex file path
loops store project -i               # interactive TUI explorer
loops store project --live           # re-render every 2 seconds
```

`loops store` is a read-only inspector — it calls `StoreReader` from `engine` and renders via the `store` lens. It shows counts, recent facts, and tick history. It does not slice, merge, or modify anything.

Use `libs/store` directly (or via Python) when you need to extract a subset, combine stores, or move data between machines.

---

## The `store` library

```python
from store import (
    slice_store, merge_store, compact_store,
    receive_store, push_store, pull_store,
    Transport, LocalTransport,
)
```

All operations are **stateless** (no connection pools, no cursors) and return **frozen result dataclasses** with counts.

### Slice — extract a subset

Extract matching facts and ticks from a source database into a new target database. The source is untouched.

```python
from pathlib import Path
from datetime import datetime
from store import slice_store

result = slice_store(
    source=Path("data/project.db"),
    target=Path("data/project-decisions-week.db"),
    kinds=["decision"],
    since=datetime(2026, 5, 17),
)
# SliceResult(facts=12, ticks=0, size_bytes=8192)
```

**Slice filters** (all optional, combined with AND):
- `since` / `before` — time window (Python `datetime` objects)
- `kinds` — list of kind strings; prefix match applies (e.g., `["thread"]` matches `thread` and `thread.close`)
- `observers` — list of observer strings
- `origins` — list of origin strings

**Target must not exist.** If it does, `slice_store` raises `FileExistsError`. This is intentional — no silent overwrites.

Slice uses `ATTACH DATABASE` + `INSERT...SELECT` entirely in SQLite — no Python-side row iteration. Fast on large stores.

### Merge — combine two stores

Merge facts from a source database into an existing target. Dedup on ULID primary key via `INSERT OR IGNORE`. Idempotent: merging the same source twice produces the same result.

```python
from store import merge_store

result = merge_store(
    target=Path("data/project.db"),
    source=Path("data/imported.db"),
)
# MergeResult(facts_added=5, facts_skipped=3, ticks_added=2, ticks_skipped=0)

# Dry run — count without committing
result = merge_store(
    target=Path("data/project.db"),
    source=Path("data/imported.db"),
    dry_run=True,
)
```

`dry_run=True` uses a SQLite `SAVEPOINT` internally — it computes the counts without leaving any changes in the target.

### Compact — reclaim space

VACUUM + PRAGMA optimize. Returns before/after byte counts.

```python
from store import compact_store

result = compact_store(Path("data/project.db"))
# CompactResult(before_bytes=16384, after_bytes=8192, saved_bytes=8192)
```

Run after large merges or after many ticks have accumulated. The store is an append-only log — deleted rows only exist via SQLite's WAL pages, not as actual deletions — so VACUUM can reclaim significant space on long-lived stores.

### Receive — create-or-merge

Validates the incoming file is a real SQLite database (checks the magic bytes), then either copies it (if target doesn't exist) or merges it (if target exists).

```python
from store import receive_store

result = receive_store(
    target=Path("data/project.db"),
    source=Path("/tmp/incoming.db"),
)
# ReceiveResult(status="created", facts=5, ticks=2)  # new store
# ReceiveResult(status="merged",  facts=3, ticks=1)  # merged into existing
```

`receive_store` is the safe inbound endpoint — it validates before touching anything. Use it as the destination side of any transport operation.

---

## Transport — moving stores between locations

The `Transport` protocol is a two-method interface:

```python
class Transport(Protocol):
    def push(self, local_path: Path, *, remote_path: Path) -> None: ...
    def pull(self, remote_path: Path, *, local_path: Path) -> None: ...
```

`LocalTransport` is the built-in implementation for same-machine operations. Its `push` calls `receive_store`; its `pull` copies the file.

```python
from store import push_store, pull_store, LocalTransport

transport = LocalTransport()

# Push: slice local → transport.push → remote receive
result = push_store(
    source=Path("data/local.db"),
    transport=transport,
    remote_path=Path("data/remote.db"),
    since=datetime(2026, 5, 17),      # optional: push only recent facts
    kinds=["decision", "thread"],     # optional: filter by kind
)
# PushResult(sliced_facts=5, sliced_ticks=2, receive=ReceiveResult(...))

# Pull: transport.pull → slice → local receive
result = pull_store(
    target=Path("data/local.db"),
    transport=transport,
    remote_path=Path("data/remote.db"),
)
# PullResult(sliced_facts=5, sliced_ticks=2, receive=ReceiveResult(...))
```

`push_store` and `pull_store` accept the same `since`, `before`, `kinds` filters as `slice_store`. Cursor tracking (remembering the last-pushed position) is the caller's responsibility — `libs/store` is stateless.

SSH transport is a future phase. Implementing a custom transport means satisfying the two-method protocol.

---

## Key invariants

- **Slice creates new files.** Never modifies the source.
- **Merge is idempotent.** ULID dedup means running merge twice gives the same result.
- **Receive validates before touching.** Invalid SQLite bytes = rejection before any write.
- **All operations are stateless.** No connection pools. Call one function, get one result.
- **All results are frozen dataclasses.** Check the returned counts — they are the verification.

---

## When to use each operation

| Need | Operation |
|------|-----------|
| Extract a time window or kind subset | `slice_store` |
| Combine facts from two stores | `merge_store` |
| Reclaim disk space after heavy use | `compact_store` |
| Accept an incoming database safely | `receive_store` |
| Move a slice from local to remote | `push_store` |
| Bring a remote slice to local | `pull_store` |
| Inspect a store interactively | `loops store project -i` |
| View recent activity | `loops store project` |

---

**Next:** [Rung 10 — Identity & Federation](10-identity-and-federation.md)
**See also:** `libs/store/CLAUDE.md` · `libs/engine/CLAUDE.md` (Level 2 — Persist) · [deep dive: PERSISTENCE](../PERSISTENCE.md) · [CLI cheatsheet](../CLI-CHEATSHEET.md) · [guide index](README.md)
