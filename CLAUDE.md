# CLAUDE.md

The strange-loops monorepo. A system for focusing attention.

See `STRANGE-LOOPS.md` for the paradigm — three shapes, four properties, one pattern.
See `ARCHITECTURE.md` for why it's built this way — libraries, persistence, rendering.

## Build & Test

```bash
uv sync                                                # install workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
uv tool install . -e                                   # (re)install sl/loops CLI from source
```

Each lib and app with a `./dev` script also supports `./dev check` (the CI gate).

**After changing CLI code, run `uv tool install . -e` and then exercise via `sl …` directly.**
The user-installed `sl` is the production install path; `uv run --package loops sl …`
re-builds from source on every invocation but doesn't guarantee parity with what
the user is actually running. Anchored 2026-05-17: a uuid4-vs-ULID divergence in
the CLI emit path lived for two months because in-session smoke-tests used the
workspace-runner form, which masked staleness of the installed `sl`.

## Structure

```
libs/
  atoms/            Fact, Spec, Source, Parse, Fold — the three shapes and ingress
  engine/           Vertex, Loop, Store, Peer, Grant — the pattern and persistence
  lang/             KDL loader + validator for .loop/.vertex files
  sign/             JWKS + signature primitives for federated attestation
  store/            Store operations — slice, merge, search, transport

apps/
  loops/            CLI — emit, fold, stream, store across vertices
  hlab/             Homelab monitoring — DSL-driven status, alerts, media
  tasks/            Task orchestration — tasks as loops, workers in worktrees

docs/               Deep dives — VERTEX, TEMPORAL, PERSISTENCE, IDENTITY, etc.
```

Rendering lives in [`painted`](https://github.com/kgruel/painted), consumed as a PyPI dependency.

## Where to start

Each lib and app has its own progressive CLAUDE.md. Start at the level that matches your intent:

**Most work is configuration, not code.** The abstraction chain runs:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/fold/stream    Vertex, Store        Fact, Spec
```

- **Query or emit** → `apps/loops/CLAUDE.md` Level 0
- **Modify a CLI command** → `apps/loops/CLAUDE.md` Level 2
- **Change data primitives** → `libs/atoms/CLAUDE.md`
- **Change runtime behavior** → `libs/engine/CLAUDE.md`
- **Change rendering** → upstream in the [painted](https://github.com/kgruel/painted) repo
- **CLI syntax reference** → `docs/CLI-CHEATSHEET.md`

## Fresh-clone bootstrap

This repo carries code and public docs. Per-clone working state — vertex
declarations, lenses, hooks, agents, accumulated facts — is not tracked.
After cloning:

```bash
uv sync                              # install workspace packages
uv tool install . -e                 # install sl/loops CLI globally
loops init project                   # create local .loops/project.vertex for this repo's design state
loops init meta                      # (optional) create a meta vertex for cross-cutting notes
```

`loops init` reads `~/.config/loops/<name>/<name>.vertex` (the user-global
template) to scaffold a local instance. If you don't have user-global
templates, the loops CLI will guide you through declaring one.

Personal Claude Code config (hooks, agents, settings) lives at `.claude/`
and is gitignored — bring your own.

## Project knowledge (this repo's loops practice)

This monorepo **dogfoods** loops. Architectural choices, open arcs, frictions,
and hypotheses accumulate in a local project vertex. Sessions read from it
at start; emissions during work feed the next session's context.

Two stores accumulate decisions, threads, tasks, hypotheses, and frictions
across sessions. The CLI is installed globally as `loops` (and `sl` shorthand).

```bash
sl read project                                # this repo — architecture, API, implementation
sl read meta                                   # cross-cutting — ways of working, patterns
sl read project --facts --kind decision        # project decisions
sl read meta --facts --kind decision --since 7d # recent cross-cutting decisions
```

**Project store** (`.loops/project.vertex`): architecture, API design, lib boundaries.

**Meta store** (`~/Code/meta-discussion/meta.vertex`, external repo, read via the config-level `meta` aggregation): cross-cutting patterns that apply to any project.

### Principles

- **The `.vertex` is editable.** It's the fold and reference state, not
  sacred. Edit when the structure stops fitting the work.
- **Granularity earned by work shape.** Add a new kind/field/prefix when
  visible work requires it, not ahead of need.
- **Names are stable handles.** Choose like API names, not commit messages.
  Thread `name=` and decision `topic=` render as headlines.
- **Friction emits in-moment.** When you notice tooling or process pain,
  emit `friction status=open` immediately — don't carry it forward in
  working memory or defer to "later." Ignored friction compounds; named
  friction can be addressed. If a specific fix isn't yet clear, emit as
  `thread status=open` and promote to friction once the fix surfaces.
- **Reroutes log at reflex speed.** Below the friction threshold sits the
  silent reroute — anything worked around instead of stopped for (tool
  fought you, verb missing, syntax retried, hand-edit where machinery
  exists). One line, zero ceremony, at the moment of rerouting:
  `sl emit project log message="..."`. No naming, no status, no
  deliberation — that's what makes it fire. A Stop hook backstops the
  noticing (thread:reroute-capture-practice).

### Review cadence — sweep and reconcile

Two tiers, two speeds. Capture happens at reflex speed (log), triage at
review speed — never the reverse.

- **Sweep** (every session wrap, fast): before the close, scan this
  session's `log` entries and unresolved moments. Repeat patterns promote
  to `friction` with proper naming; one-offs stay as log history and age
  out of the collect window. Also the moment for thread status updates
  and the session-arc emit. The sweep precedes the seal.
- **Reconcile** (own session, slower regular cadence — weekly-ish):
  `sl read project --lens reconcile` + friction backlog + stale threads
  + hypothesis staleness. Deeper structural review: does the vertex
  still fit the work, which open arcs died silently, what does the
  salience graph say. Reconcile sessions are first-class work, not
  overhead — schedule them, don't squeeze them.

### Vertex selection

| Use | Vertex |
|-----|--------|
| This repo's architecture, API, design | `project` |
| Cross-cutting patterns, ways of working | `meta` |
| Self-knowledge, identity, peer relationships | `identity` |
| Scoped experimental inquiry | `experiments/<name>` |

### Kind selection by intent

| Intent | Kind | Fold key |
|--------|------|----------|
| Architectural choice with rationale | `decision` | `topic=` |
| Open question / arc needing follow-through | `thread` | `name=` + `status=` |
| Tracked work item | `task` | `name=` + `status=` |
| Tooling/process pain with a specific fix | `friction` | `name=` + `status=` |
| Falsifiable prediction | `hypothesis` | `name=` + `status=` |
| Note something true, no prescription | `observation` | `topic=` |
| Bump prior that informed this turn (no new claim) | `cite` | (refs only) |
| Implementation strategy | `plan` | `name=` |

Forgetting the fold key (`name=` on a decision, `topic=` on a thread) silently
orphans the fact. Check this table before emit.

### Topic-prefix discipline

Existing namespaces in use:
`design/` `architecture/` `paradigm/` `rendering/` `atoms/` `workflow/`
`practice/` `implementation/` `test/` `ops/` `pattern/` `peer/` `session/`

Before adding a new prefix: dissolution-test against the list. New prefix =
ungrouped sprawl unless it genuinely doesn't fit.

### Correlation fields

Add when emits belong to an identifiable arc:

- `feature=<branch-or-arc-name>` — development work tied to a feature
- `ops=<operational-arc>` — tooling, install, infra, cross-cutting workflow

Enables `sl read project --kind decision | grep feature=vouch-substrate`
retrospection. Threads carry the conversation; correlation fields carry the
attribution — they answer different questions.

### Emit timing — when to reach for which

| Moment | Reach for |
|--------|-----------|
| Prior work informed this turn, no new claim | `sl cite REF1 REF2 -m "..."` |
| Making a claim that builds on prior | `ref=kind:key` in the new fact |
| Predicting something testable | `hypothesis status=proposed` |
| Architectural question lands | `thread` first, then design against it |
| Architectural choice settled | `decision` with `topic=` + rationale |
| Hypothesis tested | re-emit with `status=confirmed/rejected/refined` + ref to evidence |
| Thread no longer relevant | re-emit with `status=resolved` (don't delete) |
| Discovery worth noting, no prescription | `observation` |
| Tooling/process pain identified | `friction` with `status=open` |

**Don't defer to session-end.** Emit in-moment. Cost of forgetting > cost of
a shell-out.

### Emit-with-graph-fidelity (load-bearing practice)

Every emission considers its place in the graph:

- **Topic prefix** picks the namespace cluster (use existing, dissolve before adding)
- **`ref=`** links outbound to prior work
- **Stable name** makes the fact citable later — choose like an API name
- **`cite` after** bumps inbound count on prior work that informed this turn

Salience emerges from this discipline. When the graph clusters interestingly
under later scans, it's because emission was structured enough to make
clustering visible. Practice precedes the scan — load-bearing nodes are
findable because the substrate was disciplined enough to surface them.

### Read-path navigation & fact traversal

Different questions, different traversal modes. Pick the one that matches
the question, not the one that's habitual.

| Question | Traversal | Command |
|----------|-----------|---------|
| What's in this namespace? | prefix scan | `sl read project --kind <K> --key <prefix>/` |
| What does the fold currently look like? | folded state | `sl read project` |
| What concept does this build on? | ref graph | `sl read project --refs` |
| What's the lifecycle of this prediction/thread? | event history | `sl read project --kind <K> --facts` |
| What's the friction backlog? | friction scan | `sl read project --kind friction --plain` |
| What needs attention? | staleness review | `sl read project --lens reconcile` |
| What changed recently? | window slice | `sl read project --since 7d` |

`--key` is the workhorse — the newest read-path primitive (0.3.1). Default
scoping move when entering a domain.

### Emit syntax reference

```bash
sl emit project decision topic=design/foo message="..."
sl emit project thread name=arc-name status=open message="..."
sl emit project friction name=tool-pain status=open ops=loops-cli message="..."
sl emit project hypothesis name=prediction-x status=proposed message="..."
sl cite REF1 REF2 -m "what prior informed this turn"
```

Refs: `ref=decision:design/foo` or `ref=thread:arc-name`. Accumulate via
repetition (`ref=A ref=B`) or comma (`ref=A,B`).

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit
