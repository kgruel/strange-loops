# Bend-Native Reader Experiment

Replicate the reader app's feed aggregation on interaction combinators.
Extends the witness/compute split from disk_monitor to RSS/Atom feeds.

## Architecture

```
feeds.list ──→ witness.sh ──→ pipe ──→ compute.bend
                  │                        │
            curl + yq                 fold/boundary/tick
            hash links to u24         on interaction combinators
            emit integer facts        emit unique item count
```

## Wire Format

```
1 feed_id link_hash   # item fact
2 feed_id item_count  # per-feed complete
3 0 0                 # global boundary (all feeds done)
```

All values are u24 integers. The witness owns the translation from
strings/URLs to integers — the compute core never sees text.

### Link Hashing

```bash
hash_link() {
  printf '%d' "0x$(md5 -qs "$1" | head -c 6)"
}
```

6 hex digits = 24 bits. For ~50 items per feed, collision probability < 0.01%.

### Feed ID Mapping

Line position in feeds.list → feed_id (1-indexed, header skipped).

## Fold Logic

- **kind=1:** Dedup by link_hash. `Map/contains` check before insert,
  increment counter only for genuinely new items.
- **kind=2:** Record feed_id as complete in feeds_done Map.
- **kind=3:** Stop reading, emit tick (unique item count).

## Running

```bash
cd experiments/bend/reader

# Witness only — see the integer fact stream
bash witness.sh

# Full pipe — Bend computes unique item count
bash witness.sh | bend run-c compute.bend

# Python reference — same computation
bash witness.sh | python3 reference.py

# Automated match
BEND=$(bash witness.sh | bend run-c compute.bend 2>&1 | head -1)
PY=$(bash witness.sh | python3 reference.py)
[ "$BEND" = "$PY" ] && echo "MATCH: $BEND" || echo "MISMATCH: bend=$BEND py=$PY"
```

## What Works

- Dedup-by-link via integer hashing — same result as Python
- Triple-route (item/feed-complete/boundary) in a single fold loop
- Per-feed completion tracking via second Map
- Counting unique insertions with Map/contains guard

## What Breaks

| Break | What | Why |
|-------|------|-----|
| **No string data** | Titles, descriptions, URLs lost after hashing | Bend Map keys are u24; content can't be stored |
| **No timestamps** | `updated "latest"` not implemented | Epoch seconds overflow u24 (minutes-since-epoch as future fix) |
| **No persistence** | No `store "./data/feeds.db"` equivalent | Bend has file IO but no SQLite; state lives only during execution |
| **Hash collisions** | 24-bit link hash has collision risk | Acceptable for <100 items, breaks at scale |
| **No error fold** | `source.error` handling not implemented | curl errors stay in witness layer |
| **No template instantiation** | Witness hardcodes feed list traversal | Bend can't do `from file` / template expansion |

## Reused from disk_monitor

- `parse_u24`, `list_get` — identical
- `fold_loop` IO monad structure — same recursive pattern
- `Map/contains` for dedup (was used for boundary checking)

## New Bend Code

- `fold_loop(items, count, feeds_done)` — three-argument fold state
- Triple-route via nested if/else (kind 1/2/3)
- Dedup-aware insertion with contains guard
- Per-feed completion tracking (second Map)
