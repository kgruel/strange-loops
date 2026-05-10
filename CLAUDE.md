# CLAUDE.md

The strange-loops monorepo. A system for focusing attention.

See `STRANGE-LOOPS.md` for the paradigm — three shapes, four properties, one pattern.
See `ARCHITECTURE.md` for why it's built this way — libraries, persistence, rendering.
See `DESIGN-DECISIONS.md` for the architectural north star — tiered decisions, layer boundaries, implementation chain.

## Where to start

Each lib and app has its own progressive CLAUDE.md. Start at the level that matches your intent:

**Most work is configuration, not code.** The abstraction chain runs:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/fold/stream    Vertex, Store        Fact, Spec
```

- **Query or emit** → `apps/loops/CLAUDE.md` Level 0
- **New vertex, lens, or data domain** → `experiments/config-reference/CLAUDE.md` Levels 1–2
- **Modify a CLI command** → `apps/loops/CLAUDE.md` Level 2
- **Change data primitives** → `libs/atoms/CLAUDE.md`
- **Change runtime behavior** → `libs/engine/CLAUDE.md`
- **Change rendering** → `libs/painted/src/painted/CLAUDE.md` (consumer) or `libs/painted/CLAUDE.md` (contributor)
- **CLI syntax reference** → `docs/CLI-CHEATSHEET.md`

## Build & Test

```bash
uv sync                                                # install all workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
```

Each lib and app with a `./dev` script also supports `./dev check` (the CI gate).

## Structure

```
experiments/config-reference/  Reference vertex declarations and lenses (see ~/.config/loops/)

libs/
  atoms/            Fact, Spec, Source, Parse, Fold — the three shapes and ingress
  engine/           Vertex, Loop, Store, Peer, Grant — the pattern and persistence
  lang/             KDL loader + validator for .loop/.vertex files
  painted/          Terminal rendering — Block, Style, Surface, run_cli, zoom levels
  store/            Store operations — slice, merge, search, transport

apps/
  loops/            CLI — emit, fold, stream, store across vertices
  hlab/             Homelab monitoring — DSL-driven status, alerts, media
  strange-loops/    Task orchestration — tasks as loops, workers in worktrees

experiments/        Integration explorations and dissolved apps
docs/               Deep dives — VERTEX.md, TEMPORAL.md, PERSISTENCE.md, IDENTITY.md
meta-discussion/    Cross-cutting design space — patterns, principles, ways of working
```

## Project Knowledge

Two stores accumulate decisions, threads, and tasks. Query from anywhere:

```bash
uv run loops read project                              # this repo — architecture, API, implementation
uv run loops read meta                                 # cross-cutting — ways of working, patterns, tooling
uv run loops read project --facts --kind decision      # project decisions
uv run loops read meta --facts --kind decision --since 7d  # recent cross-cutting decisions
```

**Project store** (`.loops/project.vertex`): architecture, API design, lib boundaries.

**Meta store** (`meta-discussion/meta.vertex`): cross-cutting patterns that apply to any project.

## Session Discipline

The project store accumulates threads, tasks, and decisions across sessions. Staleness enters when work lands (commits, implementations) but the store isn't updated to reflect it. The session hooks handle open/close mechanics — **you** handle semantic accuracy.

**Emit as you go:**
- When a thread is resolved by implementation, emit `status=resolved` before moving on
- When a task is completed, emit `status=completed`
- When a decision is made, emit it — don't defer to session end

**Emit syntax — use `key=value` for all fields:**
```bash
# CORRECT — name= is the fold key, must be explicit:
uv run loops emit project thread name=vertex-completeness status=resolved message="Done."
uv run loops emit project task name=fix-bug status=completed
uv run loops emit project decision topic=design/my-decision message="Rationale here."

# WRONG — positional arg goes to 'message', fold can't key it:
uv run loops emit project thread vertex-completeness status=resolved   # silently lost
```

The fold keys by `name` (threads, tasks, sessions) or `topic` (decisions). If the fact
has no key field, the fold can't upsert it — the emit succeeds silently but the data
is orphaned. Always use `name=` or `topic=` explicitly.

**Names and topics carry verdict-substance, not slug-identity.**

Thread `name=` and decision `topic=` render as headlines in first-disclosure surfaces
(TOUCHED, fold, reconcile). The fold doesn't care what shape the name takes as long
as it's stable. The render does — discriminating names earn the drill-down decision;
slug-like names trigger it. Prefer:

```bash
# GOOD — name carries the verdict:
uv run loops emit project thread name=read-path-depth-gap status=open ...
uv run loops emit project decision topic=painted/first-disclosure-via-existing-headlines ...

# WEAKER — name is empty calories at the headline layer:
uv run loops emit project thread name=fix-rendering-stuff ...
uv run loops emit project decision topic=design/my-decision ...
```

**Message bodies should front-load the verdict.** The first ~140 chars is the TOUCHED
preview budget. Long-form context lives in the rest of the body, discoverable at
`-v` / DETAILED+ zoom. HYPOTHESIS-shaped bodies (verdict + evidence + conclusion)
earn the drill-down decision instead of triggering it. Example:

```bash
# Earns: verdict in the first clause, evidence next, conclusion last.
uv run loops emit project decision topic=foo/bar message="Decision: X over Y. \
Evidence: 3 instances across N lenses (cite a, b, c). Implication: Z dissolves."

# Triggers: lots of context, verdict somewhere in the middle.
uv run loops emit project decision topic=foo/bar message="In yesterday's session \
we discussed X, and then thought about Y, and eventually concluded that X over Y."
```

The painted decision at `painted/first-disclosure-via-existing-headlines` codifies
the render-side half of this; emit-side discipline is the author-side half.

**Review before wrap-up:**
```bash
uv run loops read project --lens reconcile --plain    # groups by attention-need, recency tags
```

The reconcile lens groups items by: THIS SESSION (just touched, probably current),
NEEDS REVIEW (open but not touched this session — stale candidates), RESOLVED (done).
If something in NEEDS REVIEW was resolved by your work, emit the update.

**What the hooks handle (you don't need to):**
- `SessionStart`: emits `session status=open`, syncs comms, injects project fold + comms as context
- `UserPromptSubmit`: checks for new comms
- `SessionEnd`: emits mechanical delta (fact counts by kind), emits `session status=closed`

**What the hooks don't handle (you do):**
- Thread/task status changes — only you know what was accomplished
- Decision recording — the hook can't infer architectural choices from commits
- Staleness reconciliation — if the tree lens shows stale items, update them

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit
