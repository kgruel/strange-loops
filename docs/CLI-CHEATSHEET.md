# CLI Cheatsheet

Quick reference for `loops` commands. Run `loops -h` or `loops -hv` for built-in help.

---

## Dispatch Model

Three-tier dispatch:

```
loops <verb> [vertex] [args]       # verb-first (primary)
loops <command> [args]             # dev/setup commands
loops <vertex> [flags]             # implicit read (= loops read <vertex>)
```

Vertex resolution chain: `.loops/<name>.vertex` > `cwd/<name>.vertex` > `~/.config/loops/<name>/<name>.vertex`

Top-level: `loops --version` (or `-V`) prints the installed release version; `loops --help` / `loops` lists the command roster.

---

## Read

Default shows folded state. `--facts` shows event history. `--ticks` shows tick history.

```
loops read <vertex>                           # folded state (default)
loops read <vertex> --facts                   # fact history
loops read <vertex> --ticks                   # tick history
loops read <vertex> --kind decision           # filter by kind
loops read <vertex> --key design/             # filter by fold-key prefix (kind-aware)
loops read <vertex> --key design/,architecture/   # comma-OR multiple prefixes
loops read <vertex> thread/auth-refactor      # [kind/key] positional shorthand
loops read <vertex> --kind thread status=open # field=value predicate (row filter)
loops read <vertex> --kind thread status=open,refined  # comma-OR within one value
loops read <vertex> --kind decision observer=NAME  # row filter: who emitted the fact
loops read <vertex> --facts --since 7d        # time window (7d, 24h, 1h)
loops read <vertex> --facts --kind thread --since 7d
loops read <vertex> --lens prompt             # custom lens
loops read <vertex> --facts --id <ulid>       # single fact lookup by ID/prefix
loops read <vertex> --observer all            # peel identity scope (--observer NAME/all)
loops <vertex>                                # shorthand for: loops read <vertex>
```

### Query & transform grammar

These reshape the default fold render. **They are INERT on custom-lens vertices
(identity, comms, session) and under `--lens` overrides — they apply only to the
default fold path.**

```
loops read <vertex> --match QUERY             # content search — FTS5 for indexed kinds, substring fallback
loops read <vertex> --grep QUERY              # alias for --match
loops read <vertex> --full                    # force full-body (whole) granularity on every row
loops read <vertex> --fields topic,status     # project only these payload fields (narrow each row)
loops read <vertex> --limit N                 # keep the top-N rows by salience
loops read <vertex> --last N                  # keep the newest-N rows by timestamp
loops read <vertex> --count                   # aggregate rows into counts
loops read <vertex> --count --by kind         # one count row per group (--by row attr / payload field)
```

### Zoom flags

| Flag | Level | What you get |
|------|-------|-------------|
| `-q` | MINIMAL | Counts only |
| (none) | SUMMARY | Default orientation view |
| `-v` | DETAILED | Bodies, descriptions |
| `-vv` | FULL | Timestamps, all metadata |

### Format flags

| Flag | Effect |
|------|--------|
| `--plain` | Force plain on a TTY (plain is already the default when piped / non-TTY / `NO_COLOR`) |
| `--json` | Structured Surface encoding — `to_dict(surface)` with addressed rows (implies `--static`) |
| `--live` | Poll and re-render on change |
| `-i` | Interactive TUI mode (autoresearch lens) |

---

## Emit

Inject a fact into a vertex store.

```
loops emit <vertex> <kind> key=value ...      # basic emit
loops emit <vertex> <kind> key=value ... --dry-run   # preview without storing
loops emit <vertex> <kind> key=value ... --observer <name>
```

### Key=value parsing

- `KEY=VALUE` tokens become payload fields
- Bare words (no `=`) join into `payload["message"]`
- `LOOPS_THREAD` env auto-tags `thread=` if not explicit

### Fold keys (critical)

The fold keys by a specific field per kind. Facts missing this field are stored but orphaned (never appear in fold).

| Kind | Fold key | Example |
|------|----------|---------|
| `thread` | `name=` | `loops emit project thread name=my-thread status=open` |
| `task` | `name=` | `loops emit project task name=fix-bug status=open` |
| `session` | `name=` | (managed by hooks) |
| `decision` | `topic=` | `loops emit project decision topic=auth/jwt message="Rationale"` |

**Always use the fold key explicitly.** Positional args go to `message`, not the fold key:

```
# CORRECT
loops emit project thread name=my-thread status=resolved message="Done."

# WRONG — "my-thread" lands in message, fold can't key it
loops emit project thread my-thread status=resolved
```

### Entity references

Payload values matching `kind/fold_key_value` auto-resolve to ULIDs:

```
loops emit project task name=fix-it thread=thread/auth-refactor
# adds thread_ref=<ULID> automatically
```

---

## Close

Resolve an item and capture what it produced (decisions, tasks, threads emitted during its lifetime).

```
loops close <vertex> <kind> <name> [message]
loops close <vertex> <kind> <name> --dry-run
loops close thread my-thread "Completed auth work"
```

Artifact collection: tagged facts (`thread=<name>`) take priority; temporal proximity is the fallback.

---

## Sync

Run sources (cadence-gated by default).

```
loops sync <vertex>                           # run stale sources
loops sync <vertex> --force                   # run all sources unconditionally
loops sync <vertex> --var KEY=VALUE           # pass variables to sources
```

---

## Ls — stat over the containment tree (vertex ⊃ kind ⊃ fact)

```
loops ls                                      # vertices visible from here (local + config), with stat columns
loops ls --all / -a                           # expand the config layer (default collapses it to a count-line)
loops ls -1                                    # terse, names only (scripting)
loops ls <vertex>                             # descend: list the vertex's kinds (count / share / trend / last-update)
loops ls <vertex> --kind                      # just the KINDS listing
loops ls <vertex> --kind NAME                 # descend INTO a kind — its entries one level down (namespaces / keys / observers), a stat view (NOT the facts — use read for those)
loops ls <vertex> --kind NAME --key PREFIX/   # drill a namespace within the kind (e.g. --kind decision --key design/)
loops ls <vertex> --observer|--combine|--row  # declaration sections (back-compat narrowing)
```

Stat columns are uniform at every level of the containment tree
(**vertex ⊃ kind ⊃ key ⊃ fact**): **size = Σfacts, mtime = last update
(newest fact — "where did I leave off?"), type = vertex-kind / fold-op.** Shown
by default (vertices are few); `-1` opts out. On a TTY the human register adds a
header card, a share meter, a per-kind activity sparkline, and freshness colour;
piped/agent output stays terse plain text. `ls` owns the structural levels
(vertex / kind / key); `read` owns the content level (facts).

---

## Init

```
loops init                                    # root .vertex in ~/.config/loops/
loops init <name>                             # local instance in .loops/ from config source
loops init <name> --template <source>         # use different config vertex as source
loops init <name> key=value ...               # seed config facts after creation
```

---

## Store

```
loops store                                   # inspect root vertex store
loops store <vertex>                          # by vertex name
loops store <path.db>                         # by database path
loops store <vertex> -i                       # interactive TUI explorer
loops store <vertex> --live                   # poll for changes
loops store ticks <vertex>                    # tick series (density: items/facts/delta)
loops store ticks <vertex> --chain            # per-tick attestation envelope (linkage/signature/cursor); requires .vertex, refused on combine aggregates
loops store stats <vertex>                    # topline store totals (.db or .vertex)
loops store stats <vertex> --by-kind          # count-descending per-kind tally
```

---

## Dev Commands

```
loops validate [files...]                     # validate .loop/.vertex syntax (default: all in cwd)
loops compile <file>                          # show compiled structure of .loop or .vertex
loops test <file>                             # run .loop command, preview facts (no persistence)
loops test <file> --input <sample>            # test parse pipeline against sample input
loops test <file> --limit N                   # cap output facts
```

---

## Other

```
loops whoami                                  # show resolved observer identity
loops add <target> <values...>                # add row to template population
loops rm <target> <key>                       # remove row from template population
loops export <target>                         # materialize .list from store
```

---

## Vertex-first Dispatch

Any vertex name as the first arg enables vertex-scoped operations:

```
loops project                                 # = loops read project
loops project --facts                         # = loops read project --facts
loops project emit decision topic=x ...       # = loops emit project decision ...
loops project sync --force                    # = loops sync project --force
loops project store                           # = loops store project
loops project close thread name ...           # = loops close project thread name ...
```
