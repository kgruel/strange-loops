# Rung 05 — The loops CLI: emit, read, fold

> **What you'll learn:** How to install and use the `loops` CLI to emit facts, read folded state, and scaffold vertex programs. The `sl` shorthand is introduced here.
> **Prerequisites:** [Rung 04 — Declaring Vertices in KDL](04-declaring-vertices-in-kdl.md)
> **Time:** ~20 min

The `loops` CLI is the "use" layer — the entry point that turns `.vertex` declarations into live behavior. Everything in rungs 01–04 runs inside it.

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/read/sync      Vertex, Store        Fact, Spec
```

---

## Installing the CLI

```bash
uv tool install . -e    # installs loops (and sl shorthand) globally
```

`sl` is the shorthand alias for `loops`. They run the same binary.

> **⚠️ Use the installed binary — not the workspace runner.** After any CLI code change, run:
>
> ```bash
> uv tool install . -e
> sl emit project decision topic=test "verify this works"
> ```
>
> `uv run --package loops sl …` rebuilds from source on every invocation but does **not** guarantee parity with the installed binary. It can mask staleness. A real divergence — uuid4 vs ULID in the emit path — went undetected for ~two months because in-session smoke-tests used the workspace-runner form. The installed `sl` is the production path. Use it.

---

## Three-tier dispatch

The CLI dispatches in three tiers, checked in order:

**Tier 1 — verb-first:** `loops <verb> [vertex] [args]`

Verbs: `read`, `emit`, `close`, `sync`, `cite`, `store`

```bash
loops read project
loops emit project decision topic=auth "Use JWT"
loops cite ref1 ref2 -m "context"
```

**Tier 2 — command:** `loops <command> [args]`

Commands: `test`, `compile`, `validate`, `init`, `whoami`, `ls`, `add`, `rm`, `export`

```bash
loops validate disk.loop
loops compile project.vertex
loops init project
```

**Tier 3 — vertex-first shorthand:** `loops <vertex> [op] [args]`

When the first argument is not a known verb or command, it's treated as a vertex name. With no subcommand (or flags only), it's an implicit `read`:

```bash
loops project                   # same as: loops read project
loops project --since 7d        # same as: loops read project --since 7d
loops project --facts           # same as: loops read project --facts
```

---

## Vertex resolution

When you run `loops read project`, the CLI resolves the vertex in this order:

1. `.loops/project.vertex` — directory-local instance
2. `project.vertex` in the current working directory
3. `~/.config/loops/project/project.vertex` — user-global config

The first match wins. `loops ls` shows all discovered vertices.

---

## Scaffolding with `loops init`

`loops init` creates vertex instances. No arguments creates a root discovery vertex in `LOOPS_HOME`:

```bash
loops init                # creates ~/.config/loops/root.vertex
```

With a name, it creates a local instance from the config-level source:

```bash
loops init project        # creates .loops/project.vertex from ~/.config/loops/project/project.vertex
loops init meta           # creates .loops/meta.vertex (cross-cutting notes)
```

The init reads the user-global template and replicates its loop declarations locally. If the user-global template doesn't exist yet, the CLI guides you through declaring one.

---

## Emitting facts

```bash
loops emit <vertex> <kind> [KEY=VALUE...] [bare words...]
```

`KEY=VALUE` pairs become payload fields. Bare words become the `message` field:

```bash
loops emit project decision topic=auth/jwt "Use JWT over sessions"
# payload: {topic: "auth/jwt", message: "Use JWT over sessions"}

loops emit project thread name=auth-refactor status=open "Refactoring auth"
# payload: {name: "auth-refactor", status: "open", message: "Refactoring auth"}
```

**Fold keys are required for the fact to fold.** Each kind has a designated fold key — the field that determines where the fact lands in the accumulated state. Missing it stores the fact but orphans it (it won't fold into the state dict). The fold key table is in [Rung 06](06-the-fact-graph-refs-and-cites.md#fold-keys).

**Multiple `ref=` fields accumulate:**

```bash
loops emit project decision topic=auth ref=decision:prior-decision ref=thread:auth-refactor "Built on prior work"
# payload: {topic: "auth", ref: "decision:prior-decision,thread:auth-refactor", ...}
```

**Flags:**

| Flag | Effect |
|------|--------|
| `--dry-run` | Parse and validate without storing |
| `--strict` | Refuse if kind is undeclared or fold key missing |
| `-q` / `--quiet` | Suppress receipt output |
| `--stdin FIELD` | Read stdin, inject as `FIELD=<content>` |
| `--file FIELD=PATH` | Read file, inject as `FIELD=<content>` |
| `--observer NAME` | Override observer identity |

**Using `--stdin` for long content:**

```bash
cat notes.txt | loops emit project observation topic=design/notes --stdin body
```

**Receipt output** (to stderr):

```
stored: decision/auth/jwt @ 01JXABCDEF...   (refs: 2 resolved)
```

If the kind isn't declared on the vertex, or the fold key is missing, the CLI emits a `WARN:` line but still stores the fact. With `--strict`, it refuses.

---

## Reading state

```bash
loops read <vertex>                     # folded state (default view)
loops read <vertex> --kind decision     # one kind only
loops read <vertex> --facts             # raw fact history
loops read <vertex> --facts --since 7d  # filtered by time window
loops read <vertex> --ticks             # tick history (boundary events)
```

**Zoom levels** control detail:

| Flag | Level | Shows |
|------|-------|-------|
| `-q` | MINIMAL | Counts only |
| _(default)_ | SUMMARY | Oriented overview |
| `-v` | DETAILED | Full payloads |
| `-vv` | FULL | Timestamps, refs |

**Output format flags:**

| Flag | Effect |
|------|--------|
| `--plain` | Plain text (no ANSI) |
| `--json` | JSON output |
| `--live` | Continuous live update |
| `-i` | Interactive TUI explorer |

**Filtering:**

```bash
loops read project --kind decision --since 30d
loops read meta --facts --kind friction --observer kyle
```

---

## Worked example: project vertex

```bash
# 1. Scaffold a local project vertex
loops init project

# 2. Emit a decision
sl emit project decision topic=auth/strategy "Use JWT with short-lived tokens"

# 3. Emit a thread
sl emit project thread name=auth-refactor status=open "Refactor auth module"

# 4. Read current state
sl read project

# 5. Check recent decisions
sl read project --kind decision --since 7d --facts

# 6. Validate the vertex file
sl validate .loops/project.vertex
```

Step 4 renders the folded state — each kind as a dict keyed by its fold key:

```
decision
  auth/strategy → {topic: "auth/strategy", message: "Use JWT..."}

thread
  auth-refactor → {name: "auth-refactor", status: "open", ...}
```

---

## Other useful commands

```bash
loops ls                            # list all discovered vertices
loops store .loops/project.db       # inspect the raw store
loops store .loops/project.db -i    # interactive store explorer
loops validate project.vertex       # syntax + semantic validation
loops compile project.vertex        # show compiled structure
loops test disk.loop                # run the loop command, preview facts
```

---

## What you've learned

- `uv tool install . -e` installs `loops` and `sl` globally. Use the installed binary — not the workspace runner — when exercising CLI behavior.
- Three-tier dispatch: verb-first, command, vertex-first (implicit read).
- Vertex resolution: `.loops/<name>.vertex` → cwd → `~/.config/loops/<name>/`.
- `loops init <name>` scaffolds from the user-global template.
- `KEY=VALUE` pairs become payload fields; bare words become `message`; `ref=` accumulates.
- Fold keys are required for facts to fold — missing one orphans the fact.
- `loops read` with zoom flags, `--facts`, `--ticks`, `--since`, and format flags.

---

**Next:** [Rung 06 — The Fact Graph: refs & cites](06-the-fact-graph-refs-and-cites.md)
**See also:** [CLI cheatsheet](../CLI-CHEATSHEET.md) · [configuration guide](../configuration-guide.md) · [guide index](README.md)
