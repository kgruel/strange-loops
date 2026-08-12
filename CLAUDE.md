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
  custody/          Signing composition — domain constants, key layout, signer/verifier builders
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

### The store is a file, and the file is `.jsonl`

`.loops/data/<name>.jsonl` **is** the store: one append-only interleaved log
of facts and ticks, tracked in git. `.loops/data/<name>.db` is a *derived*
sqlite index over it — gitignored, rebuildable, and materialized on first
read. Nothing is lost by deleting a `.db`; deleting a `.jsonl` deletes the
store.

**Not yet true for `project.jsonl`**: at 111 MB it exceeds GitHub's 100 MiB
per-file limit, so the log is intentionally left untracked for now — the
`.gitignore` exception is in place, and it gets tracked once the fold-snapshot
bloat is compacted. See `friction:jsonl-canonical-log-exceeds-git-limit`.
Until then a fresh clone starts an empty project store, as before.

The **store locator's extension is the switch** (`engine/residence.py`):

| `store "…"` in the `.vertex` | Canonical artifact | sqlite |
|------------------------------|--------------------|--------|
| `….jsonl` | the log | derived index at the sibling `….db` |
| `….db` / `….sqlite` | the db | *is* the store (pre-flip status quo) |

No extra key, no mode flag — declare where the truth lives and the runtime
follows. Read paths always resolve to the index (reads are sqlite reads,
unchanged); only the write path asks which file is authoritative.

After cloning, the first `sl read`/`sl emit` rebuilds the index from the log
automatically. To force it:

```bash
rm .loops/data/project.db && sl read project    # index rebuilds from the log
```

**Consequence for history-mutating ops.** `absorb_edit`, `reanchor`, and
`absorb_genesis` refuse on a JSONL-canonical store (`JsonlCanonicalUnsupported`) —
they would rewrite sqlite rows the log doesn't account for. Ops that write
the `.db` directly (`store merge`/`receive`/`rebirth`/`compact`) are detected
on the next open, not prevented: the store refuses to open rather than
rebuild over rows the log never saw.

**What open-time detection actually covers.** It is deliberately cheap — two
checks, no content walk — so its scope is narrower than "direct sqlite writes
are detected":

| Out-of-band write | Caught on open by |
|---|---|
| rows inserted straight into `facts`/`ticks` | the stamped row counts vs `COUNT(*)` |
| an edit to the last log-consumed row | the last-line integrity compare |
| a shrunk log, a torn tail, an offset outside `0..size` | rebuild triggers |
| an in-place edit to any **interior** row | **not caught** — see below |

Interior content is `sl store verify`'s job, not the open path's: a fact
sealed by a tick has its content committed in that tick's window hash, so the
chain walk breaks on exactly the edit that opens clean. The remaining gap is
the same custody boundary ticks already have — a **live-edge** fact (emitted,
not yet sealed by a boundary) has no hash over its content, so a direct edit
to it is undetectable until the next tick. Pinned by
`test_interior_sqlite_tamper_of_a_sealed_fact_survives_open_but_fails_verify`
and its unsealed sibling in `libs/engine/tests/test_jsonl_store.py`.

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

**Project store** (`.loops/project.vertex` → `.loops/data/project.jsonl`):
architecture, API design, lib boundaries. JSONL-canonical since 0.10.0 S4 —
the log is the store; `project.db` beside it is the derived index. Not yet
tracked in git (size — see "The store is a file" above).

**Meta store** (`~/Code/meta-discussion/meta.vertex`, external repo, read via the config-level `meta` aggregation): historical cross-cutting notes. **Deprecated as an emit destination** (decision:practice/meta-store-role-dissolved, 2026-07-13): process/practice lessons emit in the project where they're born, under `practice/`/`workflow/` prefixes — cross-cutting is a read-path property (aggregation over stores), not an authoring destination. Meta's original intent — a separate workspace recursing over all stores mining for patterns, storing separately — is deferred until multi-project store usage matures.

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
| Ways of working, process/practice lessons born in this repo's work | `project` (under `practice/`/`workflow/` prefixes) |
| Cross-cutting reads across projects | the config-level aggregation (read path, not an emit target) |
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
| Design deliberation that revises in place (options weighed, position evolves across sessions) | `design` | `topic=` + `status=` |
| Arc-level process synthesis after a body of work closes | `retrospective` | `name=` (arc handle) |

Forgetting the fold key (`name=` on a decision, `topic=` on a thread) silently
orphans the fact. Check this table before emit.

**`decision` vs `design`**: corpus-forensics on this store's 662 `decision`
facts (2026-07-11) found only ~10% of topics ever get revised — the rest are
correctly one-shot. `decision` keeps that narrower role: a settled choice,
stated once. `design` is for the visible minority that iterates — start
`status=proposed`, re-emit the same `topic=` as it refines (message carries
what changed and why, same convention as `hypothesis-with-status`), land on
`ratified`/`rejected`/`parked`, mark `superseded` (+ `superseded_by=`) if a
later design replaces it. `alternatives=` is a first-class field (the ADR
"considered options" convention) — capture what else was weighed and why not,
not just the verdict. See `design/practice/design-kind-adr-elements`.

Note the namespace overlap is intentional and harmless: `design/` below is a
**topic prefix** (used under `decision`/`observation` for meta-level choices
about how design work happens), while `design` above is a **kind name** — two
different axes that happen to share a word. A `design`-kind fact's `topic=`
should use the domain prefix directly (`rendering/foo`, `architecture/foo`),
not `design/foo` — the kind already says "this is a design."

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
| Design deliberation opens (options to weigh, not yet settled) | `design` with `topic=` + `status=proposed` + `alternatives=` |
| Design position evolves | re-emit same `topic=`, `status=refined`, message explains what changed |
| Design settles or dies | re-emit `status=ratified`/`rejected`/`parked` |
| A design replaces an earlier one | re-emit the OLD `topic=` with `status=superseded superseded_by=design:topic/new-slug` |
| Discovery worth noting, no prescription | `observation` |
| An arc closes and its process lessons are worth keeping | `retrospective` with `name=` — synthesis in the message, findings as ref='d observations; store-native, not a dev-doc |
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
| What changed recently? | window slice | `sl read project --facts --since 7d` |

`--key` is the workhorse — the newest read-path primitive (0.3.1). Default
scoping move when entering a domain.

### Emit syntax reference

```bash
sl emit project decision topic=design/foo message="..."
sl emit project thread name=arc-name status=open message="..."
sl emit project friction name=tool-pain status=open ops=loops-cli message="..."
sl emit project hypothesis name=prediction-x status=proposed message="..."
sl emit project design topic=rendering/foo status=proposed message="..." alternatives="option A: rejected because ...; option B: kept as the decomposed sibling, not folded in, because ..."
sl cite REF1 REF2 -m "what prior informed this turn"
```

Refs: `ref=decision:design/foo` or `ref=thread:arc-name`. Accumulate via
repetition (`ref=A ref=B`) or comma (`ref=A,B`). `ref` is a UNION edge
(attention-events accumulate).

Typed edges: any payload field declared `edge "<field>" targets="<kind>"` on
its kind becomes an OVERLAY graph edge (last-set wins, `field=` clears,
`field=a,b` is a multi-valued set). Declaration is late-bound and retroactive —
it lights up historical facts at read time (no re-emit). Undeclared
address-fields stay inert provenance pins; `--lens reconcile` surfaces them as
edge-declaration candidates. See decision:architecture/typed-edges-overlay-default.

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- Review-established invariants become structural, construction-first —
  see `docs/RATCHETS.md` (dissolve into the substrate before writing a
  detection rule; detection only at ambient-authority boundaries)
- Cross-lib imports follow the DAG in `tests/test_architecture.py`
  (`_LIB_ALLOWED_RUNTIME`) — engine→{lang,atoms}, store→{engine},
  custody→{sign,engine}; everything else is forbidden. The signing domain
  constants (`loops-tick-v1`/`loops-fact-v1`) are string-pinned to
  `libs/custody` — import them, never re-hardcode.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit

## Shell notes (zsh)

One-liner Bash here runs under zsh — a few idioms reliably bite:

- **Never put a bare `=` in echo/separator strings** (`echo ===`, `echo a=b`) —
  zsh treats `=` as globbing. Use `---` separators, or quote the whole string.
- **Quote glob-looking flag values and unquoted lists** — `--include="*.py"`,
  not `--include=*.py` (the latter both word-splits and glob-expands).
- **Prefer `grep -rl ... | while IFS= read -r f`** over `for f in $(...)` on
  unquoted command substitution — the for-loop word-splits paths with spaces.
- **Watch for non-ascii punctuation** sneaking in — a full-width semicolon
  (U+FF1B) reads as text, not a separator, and fails cryptically.
- **Keep cwd-setting in the same compound line** — cwd does not persist across
  separate Bash calls, so `cd … && cmd`, not `cd …` then `cmd` next call. For
  multi-step work prefer a heredoc script over a semicolon-dense one-liner.
