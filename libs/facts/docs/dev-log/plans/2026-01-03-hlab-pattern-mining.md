---
status: completed
updated: 2026-01-03
---

# hlab Pattern Mining

Mining ~/Code/gruel.network/cli/hlab for patterns that could inform ev design.

## Exploration Method

Three parallel exploration agents analyzed hlab from different angles:
1. Output structure & event patterns
2. Command flow & result handling
3. Progress & status communication

## Key Findings

### What hlab Validates

hlab is a production CLI using ev v0.6.0. The exploration confirms:

1. **ev primitives are sufficient** — hlab doesn't need additional event kinds
2. **Signal convention works** — `domain.subject` naming is clear and extensible
3. **topic property is useful** — enables routing without parsing data
4. **Binary Result + signal nuance** — partial success is expressible
5. **Emitter protocol is flexible** — batch and live implementations coexist

### Patterns Worth Documenting

| Pattern | Status | Recommendation |
|---------|--------|----------------|
| Signal naming (`domain.subject`) | Already in signal.md | No change needed |
| TypedDict schemas for signals | Not documented | Add to patterns/ |
| KNOWN_TOPICS registry | Not documented | Add to patterns/ |
| Stage progression lifecycle | Not documented | Add to patterns/ |
| View functions (state→renderable) | Not documented | Rich-specific, add to live-emitter.md |
| Ephemeral vs durable signals | Not documented | Add to signal.md or patterns/ |

### Patterns That Are Application-Specific

These patterns work for hlab but shouldn't be formalized in ev:

- **CommandContext implementation** — already documented in patterns/command-context.md
- **4-stage deploy pipeline** — application logic, not ev concern
- **Background refresh thread** — Rich Live implementation detail
- **Verbosity levels** — CLI framework concern (Cappa/Click)

## Recommendations

### Don't Add to ev Core

The exploration revealed no missing primitives. hlab builds everything it needs from:
- Event (5 kinds)
- log_signal() factory
- topic property
- Result (ok/error + data/meta)
- Emitter protocol

### Add Documentation ✓

1. **patterns/signal-lifecycle.md** — Stage progression pattern (started/completed/failed) ✓
2. **patterns/topic-registry.md** — KNOWN_TOPICS pattern for routing ✓
3. **Enhance live-emitter.md** — Add view functions pattern ✓

### Consider for Future

1. **`durable` flag on events?** — Would help emitters decide what to persist vs show live. But the ephemeral/durable distinction is working fine as convention.

2. **Stage helpers?** — `Event.stage_started()`, `Event.stage_completed()`. But these are just `log_signal` with naming convention. Better to document than add API surface.

## Captured Reference

Detailed patterns captured in: `docs/dev-log/reference/hlab-patterns.md`

This is a living document of patterns extracted from hlab for reference when building emitters or designing CLI output.

## ev-toolkit Discovery

Also explored `~/Code/ev-toolkit` — the companion package for common emitter patterns.

**Key insight:** The layering is intentional:
- **ev core** = frozen contract (Event, Result, Emitter protocol)
- **ev-toolkit** = evolving convenience (wrappers, helpers, recipes)

Toolkit provides:
- Emitter wrappers: QuietEmitter, FilterEmitter, TimingEmitter, CountingEmitter
- `get_emitter()` for CLI flag → emitter selection
- Copy-paste recipes: ProgressTracker, VerbosityFilter, BatchCollector, signal test helpers

This confirms: patterns belong in toolkit or docs, not ev core.

## Conclusion

hlab validates ev's minimal design. The patterns hlab uses are conventions on top of ev primitives, not missing features. ev-toolkit provides the convenience layer for common patterns. The right path forward is documentation, not API additions.
