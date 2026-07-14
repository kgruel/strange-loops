# Loops CLI Reference

> Auto-generated from golden test fixtures. Do not edit by hand.
> Rendered at zoom level: **SUMMARY**, width: 80

## `fold`

Folded state — decisions, threads, tasks, changes.

```
╭─ session · fold ─────────────────────────────────────────────────────────────╮
│ 8 keys · 4 kinds · 8 facts                                                   │
│ updated Jan 15                                                               │
╰──────────────────────────────────────────────────────────────────────────────╯
Decisions (2):
  │ Jan 15  Use SQLite for persistence
            Chose SQLite over filesystem for atomic writes and query support.
  │ Jan 14  KDL for config format
            KDL is human-friendly and supports nested structure.

Threads (2):
  │ Jan 15  vertex-routing  active
  │ Jan 14  tick-nesting    exploring

Tasks (2):
  │ Jan 15  implement fold      in-progress
  │ Jan 14  add observer field  done

Changes (2):
  │ Jan 15  Added boundary detection to Spec  libs/atoms/src/atoms/spec.py
  │ Jan 15  Refactored tick emission          libs/engine/src/engine/temporal.py
rail  ◆ high  │ mid  · tail  ⊘ stale
```

## `stream`

Event stream — chronological facts.

```
╭─ session · stream ───────────────────────────────────────────────────────────╮
│ 4 facts                                                                      │
│ 2025-01-14 → 2025-01-15 · updated Jan 15                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
2025-01-15:
  10:00 [decision] Use SQLite for persistence: Chose SQLite over filesystem for…
  09:30 [task] implement fold: Wire up Spec.apply.

2025-01-14:
  16:00 [change] Added boundary detection
  15:00 [thread] vertex-routing
```

## `store`

Store inspection — ticks, facts, freshness.

```
disk     ▁▂▃▅▇█▅▃     20        5m  /dev/sda1
memory   ▁▃▅▇     22        5m  {'used_mb': 4096, 'total_mb': 16384}
```

## `compile (loop)`

Compiled .loop source structure.

```
Source: disk.loop
  command: df -h
  kind: disk
  observer: system-monitor
  cadence: always
  format: columns
  parse: 3 ops
```

## `compile (vertex)`

Compiled .vertex structure.

```
Vertex: system-monitor
  store: system.db
  discover: ./loops/
  emit: True

Loops (2):

  disk:
    state_fields: ['fs', 'pct', 'mount']
    folds: 2
    boundary: {'kind': 'threshold', 'field': 'pct', 'value': '90%'}

  memory:
    state_fields: ['used_mb', 'total_mb']
    folds: 1

Routes:
  disk -> disk
  memory -> memory
```

## `validate`

Validate .loop and .vertex files.

```
✓ loops/disk.loop
✓ loops/memory.loop
✗ loops/broken.loop: Parse error: unexpected token 'foo' at line 3
```

## `test (--input)`

Test parse pipeline with sample input.

```
  fs: /dev/disk1
  fs: /dev/disk2
  fs: /dev/disk3

--- 3 parsed, 1 skipped ---
```

## `test (run)`

Run a .loop file — preview facts, no persistence.

```
  [disk] fs=/dev/sda1, pct=42%, mount=/
  [memory] used_mb=4096, total_mb=16384

--- 2 facts ---
```

## `run (ticks)`

Run a .vertex file — one-shot sync.

```
  [2023-11-14T22:13:20+00:00] tick: disk (3 keys)
  [2023-11-14T22:14:20+00:00] tick: memory (2 keys)

--- 2 ticks ---
```

