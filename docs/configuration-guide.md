# Configuration Guide

In strange-loops, **configuration is the primary interface.** You don't write
code to observe a system, accumulate state, or fire boundaries — you declare it
in two KDL file types:

- **`.vertex`** — a vertex configuration: what it stores, how it folds facts by
  kind, where its sources come from, and how it routes/aggregates.
- **`.loop`** — a source definition: a shell command, the fact kind it produces,
  and a parse pipeline that shapes raw output into structured facts.

The abstraction chain runs left to right; you live at the left:

```text
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
.vertex / .loop      emit/read/test      Vertex, Store        Fact, Spec
```

The grammar lives in `libs/lang` (`loader.py` maps KDL nodes to the frozen AST
in `ast.py`). Every KDL example below is copied or adapted from a real file in
this repo, cited on the line above its fence.

---

## 1. The `.vertex` file

A vertex routes incoming facts by kind into **loops** (fold engines), each of
which accumulates state and may fire a **boundary** to emit a tick.

The minimal shape is `name` + `store` + a `loops {}` block. Here is a real
project vertex (architecture/decision tracking):

```kdl
// apps/tasks/loops/project.vertex
name "project"
store "data/project.db"

loops {
  decision {
    fold {
      items "by" "topic"
    }
  }

  thread {
    fold {
      items "by" "name"
    }
  }

  plan {
    fold {
      items "by" "name"
    }
  }

  completion {
    fold {
      items "by" "task"
    }
  }
}
```

Read this as: facts of kind `decision` fold into a dict keyed by their `topic`
field; facts of kind `thread` fold by `name`; etc. (`store` is relative to the
`.vertex` file's directory.)

### Top-level vertex directives

Every directive the loader accepts (`_load_vertex_file` in `loader.py`):

| Directive | Meaning |
|-----------|---------|
| `name "..."` | Vertex name. Required (a bare `.vertex` dotfile defaults to `root`). |
| `store "path"` | SQLite store path, relative to the vertex file. Omit for aggregation-only vertices. |
| `loops { ... }` | Per-kind fold definitions. Required unless the vertex only discovers/combines children or has template-loop specs. |
| `routes { ... }` | Map fact kinds (fnmatch patterns) to loop names when kind ≠ loop name. |
| `emit "name"` | Tick name emitted at this vertex's boundary (flows out as a fact). |
| `sources { ... }` | `.loop` files and template sources that feed this vertex. |
| `sources sequential { ... }` | Inline sources with sequential exit-on-failure execution. |
| `discover "glob"` | Auto-discover child vertices by glob (aggregation). |
| `vertices "a" "b"` | Explicit child vertex paths (aggregation). |
| `combine { ... }` | Virtualize reads across other vertices' stores (no copy). Mutually exclusive with `store`/`sources`/`discover`. |
| `observers { ... }` | Declare observers with identity + emission grants. |
| `lens { ... }` | Default render lens for fold/stream views. |
| `scope "observer"` | Fold defaults to the current observer (observer-scoped state). |
| `strict true` | All emits to this vertex refuse on validation failure (no CLI override). |

A vertex that aggregates rather than stores uses `routes`, `discover`, and
`emit`. The fullest fixture example:

```kdl
// libs/lang/tests/fixtures/system.vertex
name "system-monitor"
store "./data/system.jsonl"
discover "./**/*.loop"

loops {
  disk {
    fold {
      mounts "by" "mount"
      updated "latest"
    }
    boundary when="disk.complete"
  }

  memory {
    fold {
      usage "latest"
      peak "max" "used"
    }
    boundary when="memory.complete"
  }
}

routes {
  disk "disk"
  memory "memory"
}

emit "system.health"
```

`routes` maps a fact `kind` (left, the child node name) to a loop name (right,
the first argument). Use it when the inbound kind differs from the loop name, or
to point an fnmatch pattern (`disk.*`) at one loop.

### Aggregation: discover, vertices, combine

A parent vertex can aggregate children three ways:

`vertices` — list explicit child vertex paths:

```kdl
// libs/lang/tests/fixtures/nested.vertex
name "regional"
vertices "./system-west.vertex" "./system-east.vertex"

loops {
  aggregate {
    fold {
      count "inc"
      updated "latest"
    }
  }
}
```

`combine` — read across other vertices' stores without copying (SQLite ATTACH).
Mutually exclusive with `store`, `sources`, and `discover`. Canonical syntax
(verified via loader; the shipped app corpus has no combine vertex — example
from the test topology builder, `apps/loops/tests/builders.py:409`):

```kdl
name "parent"
combine {
  vertex "./work/work.vertex" as="work"
}
```

The optional `as="alias"` enables slash-qualified reads: `loops read parent/work`.

`discover "glob"` (shown in `system.vertex` above) auto-discovers child vertices
matching a glob at read time — no enumeration needed.

---

## 2. The `.loop` file

A `.loop` file defines a source: a command to run, the fact kind it emits, the
observer, the output format, an optional cadence, and a parse pipeline.

Minimal:

```kdl
// libs/lang/tests/fixtures/minimal.loop
source "whoami"
kind "identity"
observer "shell"
```

Full, with cadence, timeout, and a parse pipeline:

```kdl
// libs/lang/tests/fixtures/disk.loop
source "df -h"
every "5s"
kind "disk"
observer "disk-monitor"
timeout "30s"

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

### `.loop` directives

| Directive | Meaning | Default |
|-----------|---------|---------|
| `source "cmd"` | Shell command to run. Required unless `every` is set (pure timer loop). | — |
| `kind "..."` | Fact kind produced. Required. | — |
| `observer "..."` | Who observed it. Required. | — |
| `format "..."` | Output framing: `lines`, `json`, `ndjson`, `blob`. | `lines` |
| `every "5s"` | Polling cadence (Go-style duration). Mutually exclusive with `on`. | none (one-shot) |
| `on "kind" ...` | Event trigger: run when a fact of given kind(s) arrives (OR semantics). | none |
| `timeout "30s"` | Max command runtime. | `60s` |
| `origin "..."` | Override the origin stamp. | empty |
| `env KEY="v"` | Environment variables for the command. | none |
| `parse { ... }` | Shaping pipeline (see §3). | none |

**Format semantics:**

- `lines` — each output line becomes one fact's text.
- `json` — parse stdout as one JSON object. A top-level JSON *array* is wrapped
  as `{"_json": [...]}` (then typically `explode path="_json"`).
- `ndjson` — one JSON object per line.
- `blob` — entire stdout as a single opaque fact.

**Durations** are Go-style (`Duration.parse` in `ast.py`): `5s`, `30s`, `1m`,
`1h30m`, `500ms`. Units compose; `ms` must follow `m`-then-`s` disambiguation
handled by the parser.

### Real sources

A polling SSH source emitting NDJSON (note the KDL raw-string `#"..."#` for
embedded quotes):

```kdl
// apps/hlab/src/hlab/loops/stacks/status.loop
source #"ssh deploy@{{host}} "cd /opt/{{kind}} && docker compose ps --format json""#
every "30s"
kind "{{kind}}"
observer "hlab"
format "ndjson"

parse {
  select "Name" "Service" "State" "Health" "Status" "ExitCode" "Image" "Ports" "Project" "CreatedAt" "RunningFor"
}
```

The `{{kind}}` / `{{host}}` placeholders are **template variables** substituted
when this `.loop` is instantiated from a `.vertex` template source (see §6).

A harness `.loop` that spawns a child agent. `env CLAUDECODE=` clears the
inherited Claude Code marker so the child launches cleanly; `{{prompt}}` is
substituted at run time by the task harness:

```kdl
// apps/tasks/loops/harnesses/opus.loop
source #"env CLAUDECODE= claude -p --model opus --output-format text --allowedTools 'Bash,Read,Edit,Write,Glob,Grep,Notebook' --max-turns 200 {{prompt}}"#
kind "worker.output"
observer "opus"
format "lines"
```

---

## 3. Parse pipeline ops

The `parse { ... }` block is an ordered pipeline. Each step transforms the
record stream, with shape inferred by the validator (STRING → LIST → DICT). The
loader's `_PARSE_STEP_LOADERS` defines the full vocabulary:

| Step | Syntax | Effect |
|------|--------|--------|
| `skip` | `skip "^regex"` | Drop lines matching the regex (lines format). |
| `split` | `split` or `split ","` | Split a line into fields (default whitespace). → LIST |
| `pick` | `pick 0 4 5 { names "a" "b" "c" }` | Select fields by index, optionally name them. → DICT |
| `select` | `select "Name" "State"` | Keep named keys from a dict (json/ndjson). |
| `transform` | `transform "field" { strip "%" coerce "int" }` | Mutate a named field. |
| `explode` | `explode path="data.alerts"` | Fan out an array at a JSON path into N records. |
| `project` | `project { out path="a.b" }` | Map output fields to nested JSON paths. |
| `where` | `where path="status" equals="success"` | Filter records by field comparison. |
| `flatten` | `flatten "field" into="text" { extract "a" "b" }` | Concatenate an array-of-objects into one searchable text field. |

**Transform sub-ops** (children of a `transform` node): `strip "chars"`,
`lstrip "chars"`, `rstrip "chars"`, `replace "old" "new"`, `coerce "int|float|bool|str"`.

**Where operators**: `equals=`, `not_equals=`, `exists`, and positional
`in`/`not_in` forms: `where path="type" in "user" "assistant"`.

A real JSON-API pipeline using `where` + `explode` + `project`:

```kdl
// apps/hlab/src/hlab/loops/prometheus/alerts.loop
parse {
  where path="status" equals="success"
  explode path="data.alerts"
  project {
    alertname path="labels.alertname"
    state path="state"
    severity path="labels.severity"
    instance path="labels.instance"
    summary path="annotations.summary"
    labels path="labels"
    annotations path="annotations"
    active_at path="activeAt"
  }
}
```

`explode` with `carry` (propagate parent fields into each child record):

```kdl
// apps/hlab/src/hlab/loops/prometheus/rules.loop
parse {
  where path="status" equals="success"
  explode path="data.groups" carry="name:group_name"
  explode path="rules"
  where path="type" equals="alerting"
  project {
    name path="name"
    group path="group_name"
    health path="health"
    alerts path="alerts"
  }
}
```

`carry="name:group_name"` copies the parent's `name` into each child as
`group_name` before the second explode discards the parent scope.

---

## 4. Fold ops

Inside a loop's `fold { ... }` block, each line is `<target> "<op>" [args]`. The
node name is the **target** (the field name in fold state); the first argument
is the op. The loader's `_FOLD_OP_SPECS` defines them:

| KDL op | Args | Effect |
|--------|------|--------|
| `inc` / `count` | — | Increment a counter by 1. |
| `latest` | — | Track the most recent timestamp. |
| `by` | `key_field` | Dict keyed by a payload field; upsert per fact. |
| `sum` | `field` | Running sum of a numeric field. |
| `max` | `field` | Maximum value seen. |
| `min` | `field` | Minimum value seen. |
| `avg` | `field` | Running average. |
| `collect` | `max_items` | Keep the last N items. |
| `window` | `size field` | Sliding window of a field's values. |

Common patterns from real files:

```kdl
// apps/tasks/loops/tasks.vertex (excerpt)
loops {
  task.created {
    fold {
      items "by" "name"          // dict keyed by name
    }
  }
  worker.output {
    fold {
      output "collect" 10000     // keep last 10000 output lines
    }
  }
}
```

```kdl
// libs/lang/tests/fixtures/system.vertex (excerpt)
memory {
  fold {
    usage "latest"
    peak "max" "used"            // track max of the "used" field
  }
}
```

A loop block may also carry `search "field" ...` (FTS5 index fields),
`parse { ... }` (a per-kind parse pipeline applied before folding), and
`preview "field" ...` (render-time field order). See `_load_loop_def` in
`loader.py`.

---

## 5. Boundary declarations

A `boundary` fires after a fold, producing a tick. Three modes (loader
`_load_boundary`):

| Mode | Syntax | Fires |
|------|--------|-------|
| `when` | `boundary when="kind"` | When a fact of that kind arrives. |
| `after` | `boundary after=10` | Once, after N facts (one-shot). |
| `every` | `boundary every=10` | Every N facts (repeating). |

`when` boundaries support extra **payload-match** properties and child
**fold-state conditions**:

```kdl
// syntax per loader._load_boundary / BoundaryWhen (ast.py)
boundary when="session" status="closed" {
  condition "high" ">=" 80
  run "scripts/dispatch.sh"
}
```

- `status="closed"` — a payload-match: the boundary fires only when the
  triggering fact has `status=closed` in its payload.
- `condition "target" "op" value` — a predicate on a **fold target** (numeric).
  Valid ops: `>=`, `<=`, `>`, `<`, `==`, `!=`. All conditions must hold.
- `run "command"` — a shell command carried on the tick; the app layer executes
  it fire-and-forget when the boundary fires. (Count-based `after`/`every`
  boundaries support only `run`, no conditions.)

The kind-only form is what the shipped corpus uses, often with template
substitution:

```kdl
// apps/hlab/src/hlab/loops/status.vertex (excerpt)
loop {
  fold {
    containers "collect" 50
  }
  boundary when="{{kind}}.complete"
}
```

A boundary may also be declared as a **sibling of loops** (vertex-level), firing
all loops at once — it lives directly inside the `loops { }` block as a
`boundary` node (`_load_vertex_file` collects it as `vertex_boundary`).

---

## 6. Template populations

Rather than copy a `.loop` file per host/feed, declare one **template source**
in the vertex and instantiate it N times with parameter rows. Each `with` row
supplies the `{{placeholder}}` values; the inline `loop { }` defines the fold +
boundary applied to every instance.

```kdl
// apps/hlab/src/hlab/loops/media_audit.vertex
name "media_audit"

sources {
  template "radarr/movies.loop" {
    with kind="movies" host="{{radarr_host}}" apikey="{{radarr_apikey}}"
    loop {
      fold {
        movies "collect" 10000
      }
      boundary when="{{kind}}.complete"
    }
  }

  template "radarr/quality.loop" {
    with kind="quality" host="{{radarr_host}}" apikey="{{radarr_apikey}}"
    loop {
      fold {
        quality_defs "collect" 500
      }
      boundary when="{{kind}}.complete"
    }
  }
}

emit "media_audit"
```

Each `with` line is one `SourceParams` row. Multiple `with` lines instantiate
the template multiple times — see `status.vertex`, which fans one
`stacks/status.loop` template across four hosts:

```kdl
// apps/hlab/src/hlab/loops/status.vertex (excerpt)
template "stacks/status.loop" {
  with kind="infra" host="{{infra_host}}"
  with kind="media" host="{{media_host}}"
  with kind="dev" host="{{dev_host}}"
  with kind="minecraft" host="{{minecraft_host}}"
  loop {
    fold {
      containers "collect" 50
    }
    boundary when="{{kind}}.complete"
  }
}
```

### Inline vs file storage

A template's parameter rows live in one of two places (`read_population` in
`population.py`):

- **inline** — `with` rows written directly in the `.vertex` file (above).
- **file** — an external `.list` file referenced by `from file "path.list"`:

  ```kdl
  // syntax per loader._load_template_source
  template "feed.loop" {
    from file "feeds.list"
    loop { fold { items "collect" 200 } }
  }
  ```

  A `.list` file is whitespace-delimited with a header row; the first column is
  the key. Comments (`#`) and blank lines are skipped. The last column absorbs
  the remainder, so URLs with spaces work:

  ```text
  kind url
  lobsters https://lobste.rs/rss
  hn https://news.ycombinator.com/rss
  ```

- **both** — file rows + inline rows merged (file first).

### Managing populations from the CLI

The `loops` CLI edits these rows for you (it uses
`kdl_insert_with_row`/`kdl_remove_with_row`/`export_to_file` under the hood):

```bash
loops ls reading                              # list parameter rows
loops add reading lobsters https://lobste.rs/rss   # add a row
loops rm reading lobsters                     # remove a row by key
loops export reading                          # convert inline rows → .list file
```

When a vertex has multiple templates, qualify by stem (`resolve_template`):
`loops add reading/feed ...`.

---

## 7. Vertex resolution & `LOOPS_HOME`

`resolve_vertex(name_or_path, home)` (in `population.py`) maps a name to a
`.vertex` path:

- Ends in `.vertex`, or starts with `./` or `/` → used as-is (filesystem path).
- Otherwise → `home / name / <leaf>.vertex`.

So `reading` → `$LOOPS_HOME/reading/reading.vertex`. **Slashed names** use the
leaf for the filename: `dev/project` → `$LOOPS_HOME/dev/project/project.vertex`.

`home` resolves consistently across the CLI (`loops_home` in
`commands/resolve.py`), the engine (`_loops_home` in `vertex_reader.py`), and
lang:

1. `$LOOPS_HOME` if set.
2. Else `$XDG_CONFIG_HOME/loops` (XDG default `~/.config/loops`).

### Config-level vs local instances

- **Config-level** vertices live under `$LOOPS_HOME/<name>/` and act as
  templates/aggregators for `loops init`.
- **Local instances** live in a repo's `.loops/` directory. The CLI prefers
  `.loops/.vertex`, then `.loops/*.vertex`, then a `*.vertex` in cwd
  (`_find_local_vertex`).

### `loops init`

`loops init <name>` stamps a local instance by replicating an existing
config-level vertex — there are no hardcoded template strings; the live config
instance *is* the template (`init.py`, `_find_source_vertex`):

```bash
loops init project        # local .loops/project.vertex from config-level template
loops init meta           # cross-cutting notes vertex
loops init dev/project    # namespaced
```

If the config vertex declares a `loops { }` block, init synthesizes an instance
(`name` + `store ./data/<leaf>.db` + the loops block, carrying any `lens`
block). It also registers the new instance with the config-level aggregator if
one exists.

---

## 8. Environment variables

All environment variables read by the system (verified by grep across `libs/`
and `apps/`):

| Variable | Purpose | Default |
|----------|---------|---------|
| `LOOPS_HOME` | Root config dir for vertex resolution. | `$XDG_CONFIG_HOME/loops` |
| `XDG_CONFIG_HOME` | Fallback base when `LOOPS_HOME` is unset. | `~/.config` |
| `LOOPS_OBSERVER` | Default observer name for emits. | empty |
| `STRANGE_LOOPS_OBSERVER` | Observer for the tasks app; preferred over `LOOPS_OBSERVER`. | falls back to `LOOPS_OBSERVER` |
| `LOOPS_EMIT_STRICT` | `=1` forces strict emit validation (refuse on failure). | unset |
| `LOOPS_THREAD` | Auto-tags emits with `thread=<value>` when no explicit `thread=`. | unset |
| `CLAUDECODE` | Set externally by the Claude Code harness. **Not read by loops** — harness `.loop` source commands prefix `env CLAUDECODE=` to *clear* it when spawning a child agent (see `opus.loop`/`sonnet.loop`). | — |

---

## See also

- [VERTEX.md](VERTEX.md) — routing, folding, boundaries, the runtime pattern.
- [CADENCE.md](CADENCE.md) — the Source-vs-Cadence separation (`every`/`on` semantics).
- [CLI-CHEATSHEET.md](CLI-CHEATSHEET.md) — three-tier dispatch, emit/read flags, fold keys.
- [api-reference.md](api-reference.md) — programmatic API (`parse_vertex_file`, `resolve_vertex`, fold/parse ops).
