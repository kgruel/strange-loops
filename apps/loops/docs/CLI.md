# Loops CLI Reference

> Auto-generated from golden test fixtures. Do not edit by hand.
> Rendered at zoom level: **SUMMARY**, width: 80

## `fold`

Folded state — decisions, threads, tasks, changes.

```
Decisions (2):
  Use SQLite for persistence [Jan 15]: Chose SQLite over filesystem f… [+34c]
  KDL for config format [Jan 14]: KDL is human-friendly and supports … [+16c]

Threads (2):
  vertex-routing [Jan 15]: active
  tick-nesting [Jan 14]: exploring

Tasks (2):
  implement fold [Jan 15]: in-progress
  add observer field [Jan 14]: done

Changes (2):
  Added boundary detection to Spec [Jan 15]: libs/atoms/src/atoms/spe… [+3c]
  Refactored tick emission [Jan 15]: libs/engine/src/engine/temporal.… [+1c]
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

## `ls`

List population entries.

```
kind     feed_url
disk     file:///var/log/disk.csv
memory   file:///var/log/mem.csv
network  https://monitor.local/net
```

## `run (ticks)`

Run a .vertex file — one-shot sync.

```
  [2023-11-14T22:13:20+00:00] tick: disk (3 keys)
  [2023-11-14T22:14:20+00:00] tick: memory (2 keys)

--- 2 ticks ---
```

