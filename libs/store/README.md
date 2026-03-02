# store

Store operations for vertex store databases — slice, merge, search, transport.

`engine.SqliteStore` writes facts at runtime. This library maintains them.

## Schema

ULID primary keys. Payload is always valid JSON, enforced on write.

```sql
facts(id TEXT PK, kind TEXT, ts REAL, observer TEXT, origin TEXT, payload TEXT)
ticks(id TEXT PK, name TEXT, ts REAL, since REAL, origin TEXT, payload TEXT)
```

## Phase 1 API

```python
from store import slice_store, merge_store

# Export filtered subset into a standalone store
result = slice_store(source, target, since=ts, kinds=["health"])

# Merge stores with ULID-based dedup
result = merge_store(target, source)
```

## Test

```bash
uv run --package store pytest libs/store/tests
```
