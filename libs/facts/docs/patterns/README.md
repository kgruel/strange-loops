# Emitter Patterns

Patterns for building production emitters with facts.

## Core Understanding

**[Domain Emitters](domain-emitters.md)** — You'll write your own emitters. Reference emitters are examples, not building blocks.

**[Emitter Archetypes](emitter-archetypes.md)** — Streaming vs batch: when to write output, and where.

## Common Patterns

**[Aggregating Emitter](aggregating-emitter.md)** — Wrap an emitter to count or accumulate while delegating rendering.

**[Live Emitter](live-emitter.md)** — Integrate Rich Live displays with facts. Includes view functions pattern.

**[Command Context](command-context.md)** — Single injection point for CLI commands, bundling config, emitters, and output.

**[Signal Lifecycle](signal-lifecycle.md)** — Structured signaling for multi-stage operations (started/completed/failed).

**[Topic Registry](topic-registry.md)** — Central registry of known signals for routing and validation.

## Quick Reference

| Pattern | Use When |
|---------|----------|
| Domain emitter | Always (for production) |
| Streaming archetype | Long ops, need live feedback |
| Batch archetype | Need composed output (tables, trees) |
| Aggregating wrapper | Counting across events while delegating |
| Live wrapper | Rich Live integration |
| View functions | Testable state→renderable transforms |
| Command context | CLI commands with multiple shared concerns |
| Signal lifecycle | Multi-stage operations with progress |
| Topic registry | 5+ signal types, need routing/validation |

## Related Docs

- [artifact.md](../concept/artifact.md) — The `type` convention for event discrimination
- [Emitter protocol](../../src/facts/emitter.py) — The minimal interface
