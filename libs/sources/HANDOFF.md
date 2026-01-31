# sources — Handoff

## 2026-01-30 (refactor)
Simplified model: CommandSource → Source, interval → every, added format parameter.

**(A) Source Rename** — `CommandSource` renamed to `Source`. The shell is the universal
adapter — Source doesn't need to know about HTTP, files, or APIs. `CommandSource` kept
as deprecated alias for backwards compatibility.

**(B) interval → every** — Renamed for clarity and DSL alignment (`every=1.0` reads
naturally). Semantics unchanged: `every=None` means run once, `every=float` means
re-run after delay.

**(C) format Parameter** — Controls how stdout is interpreted:
- `lines` (default): each stdout line becomes a Fact
- `json`: parse stdout as JSON, emit single Fact with parsed payload
- `blob`: entire stdout as single Fact with `{"text": ...}` payload

**(D) Protocol Rename** — `Source` protocol renamed to `SourceProtocol` to avoid
collision with the concrete `Source` class.

## 2026-01-30 (initial)
Initial MVP: Source protocol + CommandSource + Runner.

**(A) Source Protocol** — Minimal protocol: `observer` property and `stream()` async iterator.
Sources produce Facts from external signals. Not atoms — infrastructure at ingress boundary.

**(B) CommandSource** — Runs shell commands via `asyncio.create_subprocess_shell`.
Each stdout line becomes a `Fact(kind, payload={"line": ...})`. Supports `interval`
for repeated runs. Errors become `source.error` facts (never raised).

**(C) Runner** — Orchestrates sources feeding into a Vertex. Spawns task per source,
consumes stream, routes facts through `vertex.receive()`. Yields Ticks as boundaries fire.

**(D) Vertex.ingest()** — Convenience method added to ticks lib. Creates Fact from
raw kind/payload/observer and calls `receive()`. Useful for bridges with raw data.

## Closed
- **MVP scope** — Protocol + Source + Runner. No .loop files, no folder watching.
- **Error handling** — Errors become facts, not exceptions. Runner continues on source errors.
- **Naming** — Source is the bridge. Shell is the universal adapter.

## Open
- **Additional sources** — FileSource (watch file changes), HTTPSource (poll endpoints),
  StdinSource (interactive input) — deferred until patterns emerge from usage.
- **Backpressure** — Runner currently unbounded. May need queue limits for high-volume sources.
- **Graceful shutdown** — `stop()` cancels tasks but doesn't drain. Consider drain mode.
- **JSON array handling** — format=json with array output may need wrapping for Fact payload.
