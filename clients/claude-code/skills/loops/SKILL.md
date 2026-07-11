---
name: loops
description: >
  How to use the loops CLI (sl/loops) to accumulate design state across sessions —
  bootstrapping a vertex, establishing your own observer identity and signing,
  emitting facts, choosing kinds and fold keys, navigating the read path, and running
  the sweep/reconcile review cadence. Use when setting up loops in a fresh repo or
  minting an observer key, when emitting or reading loops vertices, when deciding
  which kind/topic/ref to use, when a session opens or closes, or when the user
  mentions loops, vertices, facts, folds, observers, signing, reconcile, or "the store".
---

# loops practice

Loops is a fact-accumulation substrate: every session emits immutable facts into a
**vertex** (`.vertex` file + sqlite store); a **fold** keeps a compressed current
view keyed by `name=`/`topic=`. You read the fold at session start, emit during work,
and the next session reads what you left. This skill is the portable distillation of
that practice — the per-repo runbook in `CLAUDE.md` carries repo-specific detail.

## The loop in one breath

```
session start  →  read the fold (orient)
during work    →  emit decisions / threads / frictions / hypotheses in-moment
reflex speed   →  log reroutes (tool fought you) with zero ceremony
session wrap   →  sweep (promote repeat logs to frictions, update thread status)
weekly-ish     →  reconcile (own session: stale threads, friction backlog, does the vertex still fit)
```

## Bootstrapping — starting fresh in a repo

A returning agent skips this (the vertex and your identity already exist). A
**fresh agent in a new repo** wires the loop first:

1. **Is there a vertex?** `sl ls` discovers all of them. If this repo's design
   state has no home, stand one up.
2. **Stand one up.** `loops init <name>` scaffolds `<repo>/.loops/<name>.vertex`
   + its store from the config-level template. (Or hand-write the `.vertex` —
   `name`, a `store` path, a `loops {}` fold schema — for a custom shape.)
3. **Become someone — choose your own name.** Your facts are signed under an
   observer identity, and you mint it yourself; it isn't assigned. Pick a handle
   you'll keep (convention `<human>/<agent>`, e.g. `kyle/<your-name>`), then mint
   + register it — see **Observer & signing** below.
4. **Verify the loop.** `sl whoami` (right identity?) → emit a probe
   (`sl emit <name> observation topic=test/bootstrap message="hello"`) → read it
   back (`sl read <name>`) → `sl seal <name>` to confirm the signed tick.
5. **Cross-repo?** A read-only `combine` aggregation vertex unifies several
   repos' stores on demand; cross-store refs resolve in the graph when read
   through it (each store still emits only to itself).

## Observer & signing — who you emit as

Every fact is attributed to an **observer**. `sl whoami` shows the resolved
identity; `LOOPS_OBSERVER=<name>` (env) overrides it so every emit auto-tags.
Convention is `<human>/<agent>` — and **you choose your own agent name**. It's
self-minted identity, not handed to you.

Signing is **progressive and honest**: no key → facts and ticks append
UNSIGNED, and that pre-signature era is not a failure. A vertex enters the
signed era the moment an observer key exists.

- **Custody is co-located with the store** — the private key lives at
  `<vertex dir>/keys/`, beside the `.vertex` and its db; minting auto-gitignores
  `keys/`. **Never reuse another store's key** — each store mints its own.
- **The registry IS the vertex file** — the `observers { <name> { key "<b64>" } }`
  block. The verifier accepts a signature matching any declared key.

```bash
loops add <vertex> observer <human>/<agent> --keygen  # mint custody-local keypair + register pubkey
loops add <vertex> observer <name> --key <b64>         # register an already-minted pubkey
export LOOPS_OBSERVER=<human>/<agent>                   # tag this session's emits
sl seal <vertex> -m "why"                              # close a window → mint a SIGNED tick
```

## Emit syntax

All payload fields are `key=value`. The **fold key is REQUIRED** and silently orphans
the fact if missing — check the table before emit.

```bash
sl emit <vertex> decision  topic=design/foo   message="..." ref=kind:key
sl emit <vertex> thread    name=arc-name       status=open    message="..."
sl emit <vertex> friction  name=tool-pain      status=open    message="..."
sl emit <vertex> hypothesis name=prediction-x  status=proposed message="..."
sl emit <vertex> observation topic=pattern/x   message="..."
sl <vertex> cite kind:key kind:key -m "what prior work informed this turn"
```

Trailing non-`key=value` tokens join as `message=`. Refs accumulate: `ref=A ref=B`
or `ref=A,B` both produce one comma-separated value.

**Default to `--stdin FIELD` for any prose or code-bearing message**, not inline
`message="..."`. Emit bodies naturally quote code identifiers, and apostrophes in
prose force double-quoting — exactly where a stray backtick triggers live shell
command substitution and silently corrupts the stored fact (a real incident: a
backtick pair in a double-quoted `message=` ran as a subshell and stored the
mangled output instead of the intended text). A quoted heredoc delimiter (`<<'EOF'`)
disables all shell expansion inside the body:

```bash
sl emit <vertex> <kind> name=... status=... --strict --stdin message <<'EOF'
Body text with `backticks`, apostrophes, and code — none of it is live shell here.
EOF
```

**`cite` takes the vertex FIRST** (`sl <vertex> cite …`), unlike `emit` where it follows
the verb (`sl emit <vertex> …`). `cite` has no vertex positional — all positionals are
refs — so `sl cite <vertex> …` would wrongly treat the vertex name as a ref. From inside a
vertex's own directory, the bare `sl cite kind:key …` resolves the local vertex.

## Kind selection by intent

| Intent | Kind | Fold key |
|--------|------|----------|
| Architectural choice + rationale | `decision` | `topic=` |
| Open question / arc needing follow-through | `thread` | `name=` + `status=` |
| Tracked work item | `task` | `name=` + `status=` |
| Tooling/process pain with a fix | `friction` | `name=` + `status=` |
| Falsifiable prediction | `hypothesis` | `name=` + `status=` |
| Note something true, no prescription | `observation` | `topic=` |
| Bump prior work that informed this turn | `cite` | (refs only) |

Status vocab: hypothesis `proposed→confirmed/rejected/refined`; thread
`open/resolved/parked`; task `in_progress/completed`; friction `open/resolved`.
To update, re-emit the same `name=`/`topic=` with new status — the fold upserts in
place and the fact history preserves the lineage. **Don't delete; resolve.**

Different kinds fold by different keys (table above) — using the wrong one
(`thread topic=` instead of `name=`, `decision name=` instead of `topic=`) doesn't
error, it silently stores a stray unfolded fact. Nothing surfaces the mismatch
until a post-store WARN. When unsure, check the KEY column of
`sl read <vertex> --kind <kind>` before emitting, and pass `--strict` in
orchestrated/agent sessions so a wrong fold key refuses instead of storing.

## Topic-prefix discipline

Existing namespaces: `design/ architecture/ paradigm/ rendering/ atoms/ workflow/
practice/ implementation/ test/ ops/ pattern/ peer/ session/`. Dissolution-test
against this list before adding a prefix — a new prefix is ungrouped sprawl unless it
genuinely doesn't fit. Topic names the THING (`design/coupling-emission-shape`), not
the act (`decided/coupling`). Names are stable handles — choose like API names.

## Read-path navigation — pick the traversal that matches the question

| Question | Command |
|----------|---------|
| What's in this namespace? | `sl read <v> --kind <K> --key <prefix>/` |
| What does the fold look like now? | `sl read <v>` |
| What concept does this build on? | `sl read <v> --refs` |
| Lifecycle of a prediction/thread? | `sl read <v> <kind>/<key> --diff` (or `--facts`) |
| Friction backlog? | `sl read <v> --kind friction --plain` |
| What needs attention? | `sl read <v> --lens reconcile` |
| What changed recently? | `sl read <v> --since 7d` |

`--key` (trailing `/` for prefix scan) is the workhorse — default scoping move when
entering a domain. `--plain` disables truncation/animation (use it when you want the
full body, not a terminal-scan view).

## Capture cadence — two tiers, two speeds

- **Reroute log (reflex speed).** Below the friction threshold sits the silent
  reroute — a tool fought you, a verb was missing, you hand-edited where machinery
  exists. One line, zero ceremony, at the moment:
  `sl emit <v> log message="..."`. No naming, no status — that's what makes it fire.
- **Friction (in-moment).** Real tooling/process pain with a fix-shape:
  `sl emit <v> friction name=... status=open message="..."`. Don't carry it in
  working memory or defer to "later"; ignored friction compounds.
- **Sweep (every session wrap, fast).** Scan this session's `log` entries — repeat
  patterns promote to named frictions; one-offs age out. Update thread statuses,
  emit the session-arc observation.
- **Reconcile (own session, weekly-ish).** `--lens reconcile` + friction backlog +
  stale threads + hypothesis staleness. First-class work, not overhead. At reconcile,
  prefer `cite` over re-emit for items you reviewed-but-didn't-change — it bumps
  salience without churning the fact stream.

## Emit-with-graph-fidelity (load-bearing)

Every emission considers its place in the graph: pick the namespace prefix, link
outbound with `ref=`, choose a citable stable name, and `cite` afterward to bump
inbound count on prior work that informed the turn. Salience emerges from this
discipline — load-bearing nodes are findable because the substrate was kept
disciplined, not because of a later scan.

## Anti-patterns

- Forgetting the fold key → orphaned fact. Check the table.
- Deferring emits to session-end → the trace future-you reads is gone. Emit in-moment.
- Re-emitting unchanged items at reconcile → churn. Use `cite`.
- Adding a new topic prefix without dissolution-testing → ungrouped sprawl.
- Reading the fold as "current truth" when you wrote an intention fact — a write
  receipt is not a temporal query. Distrust your own "current state" claims.

---
*This skill is grown incrementally — add patterns as they prove themselves in real
work. Canonical home: the `loops` Claude Code plugin
(`clients/claude-code/skills/loops/SKILL.md` in the strange-loops monorepo).
Installing the plugin makes it available in every repo (auto-invoked by
description, or `/loops:loops`) — edit it there, not a per-repo fork. Repo-specific
detail (vertex names, the local runbook) stays in each repo's `CLAUDE.md`; this
skill is the portable practice.*
