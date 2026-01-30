# sources — Handoff

## 2026-01-30
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
- **MVP scope** — Protocol + CommandSource + Runner. No .loop files, no folder watching.
- **Error handling** — Errors become facts, not exceptions. Runner continues on source errors.

## Open
- **Additional sources** — FileSource (watch file changes), HTTPSource (poll endpoints),
  StdinSource (interactive input) — deferred until patterns emerge from usage.
- **Backpressure** — Runner currently unbounded. May need queue limits for high-volume sources.
- **Graceful shutdown** — `stop()` cancels tasks but doesn't drain. Consider drain mode.
