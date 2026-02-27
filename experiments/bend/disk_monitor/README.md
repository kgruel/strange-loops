# Disk Monitor — Witness/Compute Split

Separates the **witness layer** (I/O boundary) from the **compute core**
(interaction net) into distinct programs connected by a pipe.

## What this proves

The `.loop` file entangles both sides:

```
source "df -h"                ← witness (I/O)
parse { ... }                 ← witness (raw → structured)
fold { mounts "by" "mount" }  ← compute (fold rule)
boundary when="disk.complete" ← compute (termination)
```

We split at the boundary. The witness observes the world and emits integer
facts. The compute core folds them on interaction combinators and emits a
tick. Same result, different substrates, connected by a pipe.

```
bash witness.sh | bend run-c compute.bend
```

## Files

| File | Layer | What it does |
|------|-------|-------------|
| `witness.sh` | Witness (I/O) | Runs `df -h`, emits `kind mount_id pct` per line |
| `compute.bend` | Compute (interaction net) | Reads stdin, folds, boundary check, emits tick |
| `reference.py` | Compute (Python) | Same fold logic, same stdin format, for verification |

## Wire format

```
1 1 31      # kind=1 (data), mount_id=1 (/), pct=31
1 2 11      # kind=1 (data), mount_id=2 (VM), pct=11
1 3 35      # ...
1 4 88
1 5 3
2 0 0       # kind=2 (boundary signal)
```

The witness layer owns the mount ID mapping — it translates world knowledge
(path strings) into integers the compute core can fold.

## Running

```bash
# End-to-end pipe — live data through interaction net
bash witness.sh | bend run-c compute.bend

# Same pipe through Python reference
bash witness.sh | python3 reference.py

# Verify both substrates match
BEND=$(bash witness.sh | bend run-c compute.bend 2>&1 | head -1)
PY=$(bash witness.sh | python3 reference.py)
[ "$BEND" = "$PY" ] && echo "MATCH: $BEND" || echo "MISMATCH: bend=$BEND py=$PY"
```

## What the Bend program does

1. **IO loop** — reads lines from stdin via `IO/input()` (requires `run-c`)
2. **Parse** — `String/split` on space, `parse_u24` (fold over chars)
3. **Route** — kind=1 folds into state map, kind=2 stops
4. **Fold** — `state[mount_id] = pct` (Map upsert)
5. **Boundary** — `Map/contains` for all 5 mount IDs
6. **Tick** — `max(pct)` across all mounts, printed to stdout
