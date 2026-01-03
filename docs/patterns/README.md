# Emitter Patterns

Patterns for building production emitters with ev.

## Core Understanding

**[Domain Emitters](domain-emitters.md)** — You'll write your own emitters. Reference emitters are examples, not building blocks.

**[Emitter Archetypes](emitter-archetypes.md)** — Streaming vs batch: when to write output, and where.

## Common Patterns

**[Aggregating Emitter](aggregating-emitter.md)** — Wrap an emitter to count or accumulate while delegating rendering.

**[Live Emitter](live-emitter.md)** — Integrate Rich Live displays with ev.

## Quick Reference

| Pattern | Use When |
|---------|----------|
| Domain emitter | Always (for production) |
| Streaming archetype | Long ops, need live feedback |
| Batch archetype | Need composed output (tables, trees) |
| Aggregating wrapper | Counting across events while delegating |
| Live wrapper | Rich Live integration |

## Related Docs

- [artifact.md](../concept/artifact.md) — The `type` convention for event discrimination
- [Emitter protocol](../../src/ev/emitter.py) — The minimal interface
