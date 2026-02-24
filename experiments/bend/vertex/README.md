# Vertex-as-Bend (feeds) — persistence experiment

This folder is a small, hand-written Bend program that mirrors the `feeds.vertex`
fold shape and (approximately) its witness input: a stream of link URLs, with
occasional boundary markers.

The goal of this experiment is to make the vertex **persistent**, i.e. connect
the end back to the beginning, implementing the vertex clause:

```kdl
store "./data/feeds.db"
```

## Files

- `feeds.vertex`: the motivating Vertex program (copied from `apps/reader/loops/feeds.vertex`).
- `feeds.bend`: one-shot version (no persistence).
- `feeds_persistent.bend`: persistent version (reads/writes `./data/feeds.db`).
- `reference.py`: one-shot Python reference.
- `reference_persistent.py`: persistent Python reference (same state format as Bend).
- `witness.sh`: thin witness that emits URLs + comment boundary markers.

## Bend1 persistence: what works

Bend1 has file IO builtins:

- `IO/FS/read_file(path)` → `IO(Result(List(u24), u24))`
- `IO/FS/write_file(path, bytes)` → `IO(Result(None, u24))`
- `IO/FS/open`, `IO/FS/read_line`, `IO/FS/close`

`feeds_persistent.bend` uses these to:

1. Load previous state from `./data/feeds.db`.
2. Rebuild the membership structure for deduplication.
3. Process stdin lines, counting **new** unique links.
4. Write updated state back to `./data/feeds.db`.

The state file format is intentionally simple:

- One **u24 hash** (base-10) per line.
- The hash matches the Bend implementation: `acc = acc * 31 + char`, wrapping in `u24`.

## Bend1 gotchas (hit while building this)

- `IO/FS/read_line` is implemented via `seek` backtracking; it fails on non-seekable
  inputs like pipes/stdin in `bash witness.sh | ...`. The Bend program uses
  `IO/FS/read_to_end(IO/FS/STDIN)` and does its own line scanning instead.
- `String/split` currently returns each substring **reversed** (e.g. `"ab\ncd"` → `"ba"`, `"dc"`),
  so parsing newline-delimited state by splitting strings produces wrong results unless you
  reverse each piece. This experiment avoids `String/split` for parsing state and stdin.

## The wall: Map serialization / iteration

Bend's built-in `Map(T)` is usable for membership (`Map/contains`) and updates
(`Map/set`), but there is no supported way to iterate keys/entries (no
`Map/entries`, no `Map/to_list`, no fold over nodes).

That means:

- You can *use* a `Map` during computation,
- but you can't *serialize* it, because you can't enumerate its contents.

### Workaround implemented here

Maintain a parallel `List(u24)` of keys (hashes):

- Persist the **list** to disk (one hash per line).
- On startup, rebuild a `Map(u24)` by folding over the list and inserting keys.

This is why `feeds_persistent.bend` persists hashes rather than trying to dump
the `Map` itself.

## Bend2 note (what would change)

If Bend grows *any* of the following, the workaround goes away:

- `Map/entries` (or a generic iterator/fold over `Map`),
- a standard `Serialize`/`Deserialize` derivation for built-in structures,
- a `Map`→`List` conversion primitive.

## Run

```bash
cd experiments/bend/vertex

# First run — no state file exists
bash witness.sh | bend run-c feeds_persistent.bend

# Second run — should report 0 new items
bash witness.sh | bend run-c feeds_persistent.bend

# Python reference should match (new, total)
bash witness.sh | python3 reference_persistent.py
```

Note: `./data/` must already exist; Bend1 doesn't provide a `mkdir` builtin.
