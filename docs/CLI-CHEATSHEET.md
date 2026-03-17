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

---

## Read

Default shows folded state. `--facts` shows event history. `--ticks` shows tick history.

```
loops read <vertex>                           # folded state (default)
loops read <vertex> --facts                   # fact history
loops read <vertex> --ticks                   # tick history
loops read <vertex> --kind decision           # filter by kind
loops read <vertex> --facts --since 7d        # time window (7d, 24h, 1h)
loops read <vertex> --facts --kind thread --since 7d
loops read <vertex> --lens prompt             # custom lens
loops read <vertex> --facts --id <ulid>       # single fact lookup by ID/prefix
loops read <vertex> --observer all            # all observers (overrides vertex scope)
loops <vertex>                                # shorthand for: loops read <vertex>
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
| `--plain` | Strip ANSI codes (pipe-safe) |
| `--json` | JSON output |
| `--live` | Poll and re-render on change |
| `-i` | Interactive TUI (store command) |

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

## Ls

```
loops ls                                      # all discovered vertices
loops ls <target>                             # list template population rows
loops <vertex> ls                             # population for a vertex
loops <vertex> ls <template>                  # population for a specific template
```

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
