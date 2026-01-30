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
| `Source` | Protocol | stream of Facts from external world |
| `CommandSource` | dataclass | runs shell commands, emits stdout lines as Facts |
| `Runner` | class | orchestrates sources feeding into a Vertex |

## Key Types

### Source Protocol
```python
class Source(Protocol):
    @property
    def observer(self) -> str: ...

    async def stream(self) -> AsyncIterator[Fact]: ...
```

### CommandSource
```python
source = CommandSource(
    command='echo "hello"',      # Shell command to run
    kind="greeting",             # Fact kind for stdout lines
    observer="echo-source",      # Identity for produced facts
    interval=1.0,                # Re-run interval (None = once)
)

async for fact in source.stream():
    print(fact)  # Fact(kind="greeting", payload={"line": "hello"}, ...)
```

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
- CommandSource emits one Fact per stdout line with `payload={"line": ...}`.
- Errors become Facts with `kind="source.error"` — never raised.
- Runner spawns one task per source — sources run concurrently.
- Runner yields Ticks as vertex boundaries fire.
- `interval=None` means run once. `interval=float` means re-run after delay.
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
  ├── CommandSource ──→ stdout lines ──→ Fact
  ├── (future: FileSource, HTTPSource, etc.)
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
  protocol.py      # Source protocol
  command.py       # CommandSource
  runner.py        # Runner
tests/
  test_command.py  # CommandSource tests
  test_runner.py   # Runner + integration tests
```
