# Loops CLI Reference

> Auto-generated from golden test fixtures. Do not edit by hand.
> Rendered at zoom level: **SUMMARY**, width: 80

## `fold`

Folded state — decisions, threads, tasks, changes.

```
Decisions (2):
  Use SQLite for persistence: Chose SQLite over filesystem for atomic writes …
  KDL for config format: KDL is human-friendly and supports nested structure.

Threads (2):
  vertex-routing: active
  tick-nesting: exploring

Tasks (2):
  implement fold: in-progress
  add observer field: done

Changes (2):
  Added boundary detection to Spec: libs/atoms/src/atoms/spec.py
  Refactored tick emission: libs/engine/src/engine/temporal.py
```

## `stream`

Event stream — chronological facts.

```
2025-01-15:
  10:00 [decision] Use SQLite for persistence: Chose SQLite over filesystem for
  09:30 [task] implement fold: Wire up Spec.apply.

2025-01-14:
  16:00 [change] Added boundary detection
  15:00 [thread] vertex-routing
```

## `store`

Store inspection — ticks, facts, freshness.

```
disk     ▁▂▃▅▇█▅▃     20    5m ago  /dev/sda1
memory   ▁▃▅▇     22    5m ago  {'used_mb': 4096, 'total_mb': 16384}
```

## `start`

Run vertex and display tick results.

```
  [disk] fs, pct, mount
  [memory] used_mb, total_mb, free_mb
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

## `test`

Test parse pipeline with sample input.

```
  fs: /dev/disk1
  fs: /dev/disk2
  fs: /dev/disk3

--- 3 parsed, 1 skipped ---
```

## `ls`

List population entries.

```
kind     feed_url
disk     file:///var/log/disk.csv
memory   file:///var/log/mem.csv
network  https://monitor.local/net
```

## `run (facts)`

Stream facts from a running loop.

```
  [disk] fs=/dev/sda1, pct=42%, mount=/
  [memory] used_mb=4096, total_mb=16384

--- 2 facts ---
```

## `run (ticks)`

Stream ticks from a running vertex.

```
  [2023-11-14T22:13:20+00:00] tick: disk (3 keys)
  [2023-11-14T22:14:20+00:00] tick: memory (2 keys)

--- 2 ticks ---
```

