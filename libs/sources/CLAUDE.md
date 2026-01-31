# CLAUDE.md — sources

Ingress adapters. Answers: **how does external data enter the system?**

## Build & Test

```bash
uv run --package sources pytest libs/sources/tests
```

## Not Atoms

Sources are infrastructure at the ingress boundary — adapters that convert
external signals into Facts. They don't appear in the fundamental model.
Facts flow in, the system doesn't care where they came from.

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Source` | dataclass | runs shell commands, emits output as Facts |
| `SourceProtocol` | Protocol | interface for sources (observer + stream) |
| `CommandSource` | alias | deprecated alias for Source |
| `Runner` | class | orchestrates sources feeding into a Vertex |

## Key Types

### SourceProtocol
```python
class SourceProtocol(Protocol):
    @property
    def observer(self) -> str: ...

    async def stream(self) -> AsyncIterator[Fact]: ...
```

### Source
```python
source = Source(
    command='echo "hello"',      # Shell command to run
    kind="greeting",             # Fact kind for output
    observer="echo-source",      # Identity for produced facts
    every=1.0,                   # Re-run interval (None = once)
    format="lines",              # lines | json | blob
)

async for fact in source.stream():
    print(fact)  # Fact(kind="greeting", payload={"line": "hello"}, ...)
```

### Format Options

- **lines**: each stdout line becomes a Fact with `payload={"line": ...}` (default)
- **json**: parse stdout as JSON, emit single Fact with parsed payload
- **blob**: entire stdout as single Fact with `payload={"text": ...}`

### Runner
```python
runner = Runner(vertex)
runner.add(source1)
runner.add(source2)

async for tick in runner.run():
    print(tick)  # Ticks from vertex boundaries
```

## Invariants

- Sources produce Facts — the only output type.
- Source with `format="lines"` emits one Fact per stdout line.
- Source with `format="json"` parses stdout and emits one Fact.
- Source with `format="blob"` emits one Fact with entire stdout.
- Errors become Facts with `kind="source.error"` — never raised.
- Runner spawns one task per source — sources run concurrently.
- Runner yields Ticks as vertex boundaries fire.
- `every=None` means run once. `every=float` means re-run after delay.
- Sources are stateless — all state lives in Vertex folds.

## Error Handling

Errors become facts, not exceptions:

```python
# Command failure (non-zero exit)
Fact(kind="source.error", payload={
    "command": "...",
    "returncode": 1,
    "stderr": "..."
})

# JSON parse failure
Fact(kind="source.error", payload={
    "command": "...",
    "error": "JSON decode error: ...",
    "error_type": "JSONDecodeError"
})

# Python exception
Fact(kind="source.error", payload={
    "command": "...",
    "error": "...",
    "error_type": "ValueError"
})
```

## Pipeline Role

```
External World
  │
  ├── Source ──→ command output ──→ Fact
  │              (lines/json/blob)
  │
  ▼
Runner
  │
  ├── task per source
  ├── source.stream() ──→ vertex.receive(fact)
  │
  ▼
Vertex
  │
  └── boundary fires ──→ Tick ──→ yielded from runner.run()
```

## Source Layout

```
src/sources/
  __init__.py      # Public exports
  protocol.py      # SourceProtocol
  source.py        # Source (main implementation)
  runner.py        # Runner
tests/
  test_source.py   # Source tests
  test_runner.py   # Runner + integration tests
```
