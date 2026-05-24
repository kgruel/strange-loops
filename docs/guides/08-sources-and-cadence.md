# Rung 08 — Sources & Cadence

> **What you'll learn:** How `.loop` files declare an ingestion pipeline; how cadence gating decides when a source runs; the authoring toolchain (`validate`, `compile`, `test`); and how to manage template populations with `ls`, `add`, `rm`.
> **Prerequisites:** [Rung 07 — Reading Deeply: zoom, keys & lenses](07-reading-and-lenses.md)
> **Time:** ~20 min

Most vertex data comes from external systems — RSS feeds, shell commands, APIs, log files. A `.loop` file declares the pipeline that turns raw output into Facts. `loops sync` runs those pipelines; cadence gating decides *when* each source actually executes.

---

## The `.loop` file

A `.loop` file defines one source: a command to run, the kind of Fact it produces, how to parse the output, and when to run it. Fields are declared at the top level (not inside a block). KDL syntax:

```kdl
// reading/sources/feed.loop — fetch a JSON API, emit one "reading" fact per call
source "curl -sf 'https://api.example.com/v1/articles?limit=50'"
kind "reading"
observer "reading"
format "json"
every "1h"

parse {
  project {
    title    path="title"
    url      path="url"
    score    path="score"
    author   path="author"
  }
}
```

A more minimal example — just a shell command, no parse pipeline needed:

```kdl
// disk.loop — monitor disk usage
source "df -h"
kind "disk"
observer "disk-monitor"
every "5s"

parse {
  skip "^Filesystem"
  split
  pick 0 4 5 {
    names "fs" "pct" "mount"
  }
  transform "pct" {
    strip "%"
    coerce "int"
  }
}
```

The pipeline: `source` → stdout → `format` decoder → `parse` transforms → one Fact per row/item.

### The top-level fields

**`source`**: a shell string. Executed as-is; stdout becomes the parse input.

**`kind`**: the fact kind for output facts.

**`observer`**: who produced these observations (goes on each fact's `observer` field).

**`format`**: how to decode stdout before the parse pipeline. Values: `json`, `ndjson`, `lines`, `blob`. If omitted, defaults to `lines`.

**`parse {}`**: a sequence of transformation steps. Each step shapes or extracts from the decoded output. Steps run in order.

### Cadence declaration

Two cadence shapes, declared as top-level fields:

```kdl
every "30m"          // run if ≥ 30 minutes since last ok run (elapsed cadence)
on "deploy"          // run if any "deploy" fact arrived since last ok run (triggered)
on "deploy" "health" // multiple triggers — OR semantics: any satisfies
```

If neither `every` nor `on` is declared, the source is `always` — runs every time `loops sync` is invoked (for cursor-based or one-shot sources).

Duration formats: `30m`, `1h`, `24h`, `7d`, `5s`.

**Source vs Cadence is a deliberate separation.** The source declares *what* to do; cadence declares *when*. The executor evaluates cadence independently and can skip the source entirely without touching it. See [../CADENCE.md](../CADENCE.md) for the design rationale.

---

## `loops sync <vertex>` — running sources

```bash
loops sync project           # cadence-gated: run only stale sources
loops sync project --force   # bypass cadence: run all sources
loops sync project -f        # shorthand for --force
loops sync project --var ENDPOINT=https://staging.api.example.com
```

When `sync` runs:

1. For each source, evaluate its cadence predicate against the store.
2. Sources whose cadence is satisfied run; others are skipped.
3. After each source completes, the executor emits a `_sync.{kind}` fact with `status="ok"` (or `status="error"`).
4. After all sources complete, a final `_sync` summary fact is emitted.

The `_sync.{kind}` facts are what cadence reads on the *next* sync — they are the feedback loop. The `_sync` prefix separates source-lifecycle observations from domain facts.

### How cadence decides: `every` (elapsed mode)

`every "30m"` compiles to `Cadence.elapsed(kind, interval)` in the engine.

```
elapsed mode:
  last_ok = latest _sync.{kind} fact with status="ok"
  if no last_ok → run (never run before)
  if (now - last_ok.ts) >= interval → run
  else → skip
```

### How cadence decides: `on` (triggered mode)

`on "deploy"` compiles to `Cadence.triggered(trigger_kinds, source_kind)`.

```
triggered mode:
  last_ok = latest _sync.{source_kind} with status="ok"
  if no last_ok:
    if any trigger_kind fact exists → run
    else → skip
  if any trigger_kind fact arrived after last_ok.ts → run
  else → skip
```

This enables reactive pipelines: a `deploy` fact triggers re-evaluation of a health-check source without time-based polling.

### `--force` bypass

`--force` (or `-f`) bypasses all cadence predicates. Every source runs regardless of its last run time or trigger state. Use when you need a guaranteed refresh — initial setup, after infrastructure changes, debugging.

### `--var KEY=VALUE` overrides

Template variables in `.loop` files (referenced as `${VAR_NAME}`) can be overridden at sync time:

```bash
loops sync reading --var LIMIT=50 --var SINCE=2026-01-01
```

Multiple `--var` flags are accepted. Variables are passed through to the compiled source's template substitution before the command executes.

### Aggregation vertices

If the vertex has no own sources but has `combine {}` children, `loops sync` syncs each child independently and aggregates the results. This is how a top-level vertex (e.g., `comms`) delegates to `discord.vertex` and `native.vertex`.

---

## The authoring toolchain

When writing or modifying `.loop` files, three commands form the authoring loop:

### `loops validate [files...]`

Syntax check. Parses and validates `.loop` and `.vertex` files. Default: all in cwd.

```bash
loops validate                       # all .loop/.vertex in cwd
loops validate reading.loop          # one file
loops validate *.loop                # shell glob
```

Returns exit 0 on success, exit 1 if any file has errors. Output shows a checkmark or error per file.

### `loops compile <file>`

Show the compiled structure: what the engine will see after parsing. Reveals the full pipeline (command, kind, observer, cadence mode, parse steps) without running anything.

```bash
loops compile reading.loop           # show compiled loop structure
loops compile project.vertex         # show compiled vertex specs
```

Use this to verify that field extraction, cadence mode, and observer are resolved as expected before running.

### `loops test <file> [options]`

Run a `.loop` file and preview the facts it produces — no persistence. Two modes:

**Run mode** (no `--input`): executes the command and streams facts as they arrive.

```bash
loops test reading.loop              # execute command, show facts
loops test reading.loop --limit 5    # cap at 5 facts
loops test reading.loop -n 5         # shorthand
```

**Parse mode** (`--input FILE`): skips the command; feeds a file through the parse pipeline instead. Use this with captured output to iterate on the parse steps without re-running the command.

```bash
loops test reading.loop --input sample.xml     # parse pipeline only
loops test reading.loop -i sample.xml          # shorthand
```

Neither mode writes to a store. Facts are displayed and discarded.

---

## Template populations with `ls`, `add`, `rm`

Some sources are *template sources* — they run a parameterized command once per row in a `.list` file. A row might be `{name: lobsters, url: https://lobste.rs/rss}`, producing one source invocation per feed URL.

The template and its list file are declared in the `.vertex` file. The CLI provides `ls`, `add`, and `rm` to inspect and edit the list.

### `loops ls <vertex>`

Show all declarations for a vertex — kinds, observers, combine entries, and template sources (the "sources" section):

```bash
loops ls project                     # all declarations
loops ls project --row               # template sources only (all templates)
loops ls project --row reading       # one named template
loops ls project --kind              # loop kinds only
loops ls project --observer          # observers only
```

Flag form (`--row`, `--kind`, `--observer`, `--combine`) is canonical and composable. Positional form (`loops ls project row`) is a back-compat alias for single-section listing.

### `loops add <vertex> row <key> <values...>`

Append a row to a template population:

```bash
loops add reading row lobsters https://lobste.rs/rss
loops add reading row hn https://news.ycombinator.com/rss
```

The positional form `loops add reading lobsters https://lobste.rs/rss` is a back-compat alias for `add row` and will be retired in a future release.

`add` also supports structural mutations — adding kinds, observers, or combine entries directly to the vertex file:

```bash
loops add project kind decision --by topic   # add a new loop kind (fold by topic)
loops add project observer monitor           # declare a new observer (unrestricted)
loops add project observer monitor --grant health,deploy  # with kind grant
```

### `loops rm <vertex> row <key>`

Remove a row from the template population:

```bash
loops rm reading row lobsters
loops rm reading lobsters           # back-compat positional alias
```

### `loops export` — retired

`loops export <vertex>` was retired in Phase 3. The `.list` file is now canonical — it is edited directly via `add row` and `rm row`. There is nothing to export or materialize.

---

## Example workflow

```bash
# 1. Write the .loop file
vim ~/.config/loops/reading/rss.loop

# 2. Validate syntax
loops validate ~/.config/loops/reading/rss.loop

# 3. Inspect compiled structure
loops compile ~/.config/loops/reading/rss.loop

# 4. Test without persistence
loops test ~/.config/loops/reading/rss.loop -n 10

# 5. Add population rows
loops add reading row lobsters https://lobste.rs/rss
loops add reading row hn https://news.ycombinator.com/rss

# 6. Run for real
loops sync reading
# "Syncing reading: 1 sources (cadence-gated)"

# 7. Force a refresh
loops sync reading --force

# 8. Inspect what was ingested
loops read reading --facts --since 1h
```

---

**Next:** [Rung 09 — Store Maintenance & Transport](09-store-maintenance-and-transport.md)
**See also:** [deep dive: CADENCE](../CADENCE.md) · [CLI cheatsheet](../CLI-CHEATSHEET.md) · [guide index](README.md)
