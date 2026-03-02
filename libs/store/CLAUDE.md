# libs/store

Store operations for vertex store databases.

## What this lib does

Maintenance operations on the facts/ticks SQLite schema:
- **slice** — filtered export by time/kind/observer/origin
- **merge** — combine stores with ULID-based dedup (INSERT OR IGNORE)
- **search** — FTS5 over fact payloads (phase 2)
- **transport** — push/pull between stores (phase 3)

## Schema

ULID primary keys via `sqlite-ulid` extension. Payload enforced as valid JSON.

```sql
facts(id TEXT PK DEFAULT (ulid()), kind, ts, observer, origin, payload CHECK json_valid)
ticks(id TEXT PK DEFAULT (ulid()), name, ts, since, origin, payload CHECK json_valid)
```

## Key patterns

- `_conn.py` is internal — handles extension loading, schema creation, WAL mode
- Public API is just the operation functions: `slice_store`, `merge_store`
- Uses ATTACH DATABASE for cross-DB operations (no Python round-trip)
- Merge dedup is INSERT OR IGNORE on ULID — globally unique IDs make this trivial
- Depends on engine (for Tick) and sqlite-ulid (for ULID generation)

## Test

```bash
uv run --package store pytest libs/store/tests
```
