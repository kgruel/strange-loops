# Ideas / Possible Additions

## Thin CLI Harness

The render layer replaces ev for interactive use cases by dissolving the problem ev solved (mediating between domain logic and output context). But CLI tools still need:

1. Arg parsing
2. Mode detection (TTY? `--json`? `--follow`?)
3. Run the operation
4. Route: interactive → RenderApp, batch → `json.dumps` to stdout

The insight: operations are just `async (args) → data`. The "framework" is the mode decision, not a protocol. Maybe 30 lines, not a library.

```
Operation: async (args) → data
    ↓
Mode decision (TTY? --json? --follow?)
    ↓
Interactive: RenderApp(data stream) → terminal
Batch: json.dumps(data) → stdout
```

Open questions:
- Does the operation need to know its mode? (Probably not — it yields data, consumer decides.)
- Streaming ops (logs follow) vs batch ops (status check) — same harness or two patterns?
- Where does host resolution / SSH config live if not in ev-toolkit?

## ev Dissolution

ev's three concepts mapped to simpler equivalents:
- `Event` → app state mutation in `update()`
- `Result` → not needed for interactive; `json.dumps(data)` for batch
- `Emitter` protocol → not needed; no indirection between domain and presentation in a TUI

The authority model ("automation ignores Events, uses Result alone") still holds — it's just that Result is literally "print the data dict as JSON." No ceremony needed.

## Render Layer as the Interactive Backend

The render layer (buffer + diff + components + app lifecycle) is the hard part of CLI tooling. Everything else is trivial:
- Batch output: `json.dumps`
- Arg parsing: `argparse`
- Mode detection: `sys.stdout.isatty()`
- Graceful shutdown: `asyncio.CancelledError`

The framework/ layer (EventStore, Projections, Signals) is useful when you have complex derived state from streaming events (dashboards, monitors). Not needed for simple tools.
