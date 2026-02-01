# CADENCE.md

Design document: separating Cadence from Source.

## The Insight

A Source has two concerns:
1. **What** to observe (command, API, stream, nothing)
2. **When** to observe (interval, event, boundary)

Currently these are coupled — Source has `every` baked in. This design separates them.

## The Split

| Concept | Answers | Examples |
|---------|---------|----------|
| **Source** | What to observe | `df -h`, HTTP endpoint, file, stream, nothing |
| **Cadence** | When to observe | `every 10s`, `on: minute`, `on: deploy.complete` |

A `.loop` file becomes: **Cadence + Source + Parse → Facts**

## Timer as Fact

A timer is a loop with cadence but no source:

```yaml
# minute.loop
every: 60s
kind: minute
# no source — emits time-shaped facts
```

This produces `minute` facts. Other loops trigger on them:

```yaml
# disk.loop
on: minute
command: df -h
parse: ...
```

**The clock is just another fact source.** No special timer handling needed.

## Event-Driven Sources

Generalize `on:` to any fact kind:

```yaml
# smoke_tests.loop
on: deploy.complete
command: ./run-smoke-tests.sh
parse: ...
```

Sources don't poll — they react. The runtime unifies around one pattern:
receive fact → maybe trigger source → route → fold → maybe tick.

## Semantic Cadence

Cadence can be complex — a full loop with its own logic:

```yaml
# business_hours.loop
every: 1m
fold: track hour/day
boundary: when entering/leaving 9am-5pm M-F
kind: business_hours.transition
```

This emits facts at semantic boundaries, not fixed intervals. Other loops trigger on that:

```yaml
on: business_hours.transition
command: ./check-trading-systems.sh
```

Cadence is loops all the way down.

## Runtime Simplification

**Before:** Each source has its own timer. Runtime manages N async loops.

```
Source 1 (timer) ──→ facts ──┐
Source 2 (timer) ──→ facts ──┼──→ Vertex
Source 3 (timer) ──→ facts ──┘
```

**After:** One fact stream. Sources execute when triggered.

```
Timer loop ──→ tick facts ──┐
                            ├──→ Trigger sources ──→ Vertex
Other ticks ────────────────┘
```

The runtime is uniform: receive → route → fold. No special timer management.

## Syntax (Proposed)

```yaml
# Simple interval (sugar for timer + source)
every: 10s
command: df -h

# Explicit trigger
on: minute
command: df -h

# Pure timer (no source)
every: 60s
kind: minute

# Complex cadence (full loop)
on: second
fold: count ticks
boundary: when count = 60
kind: minute
```

## Open Questions

1. **Sugar vs explicit:** Should `every: 10s` automatically create a timer, or require explicit timer loop?

2. **Multiple triggers:** Can a source have multiple `on:` triggers? `on: [minute, deploy.complete]`?

3. **Feedback loops:** A → B → A is possible. Is this a bug or a feature (control systems)?

4. **Backpressure:** If trigger fires faster than source executes, queue or drop?

## Status

**Conceptual.** Discussed 2026-01-31. Next: experiment to prove the pattern, then DSL/runtime changes.
