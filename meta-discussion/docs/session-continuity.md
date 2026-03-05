# Session Continuity

How development state persists across sessions — from documents to structured
facts, and where the pattern wants to go next.

## The Evolution

### Phase 1: Paired Documents (all projects)

Every project has some version of:
- **LOG.md** — what happened, when, why. Narrative history.
- **HANDOFF.md** — what's next, what's deferred, what's active. Threading.

These are human-readable, version-controlled, and work. But they're manually
maintained and can't be queried programmatically.

### Phase 2: Structured Session Facts (loops)

`loops session start/end/status/log` — session observations as facts in a
vertex store.

```bash
loops session start                    # creates vertex + store
loops emit session decision topic="X" "rationale here"
loops emit session thread name="Y" status="resolved"
loops session status                   # query-time fold over facts
```

Six fact kinds: `decision`, `thread`, `task`, `change`, `session.start`,
`session.end`. State via query-time fold (latest-per-key for keyed kinds,
collect for changes). Correction by re-emit.

**What it proved:** The loops model can track its own development. Session
state IS a loop — observations accumulate, boundaries fire, state persists.

### Phase 3: Named Sessions with Separate Stores (where it wants to go)

**The insight:** The current `loops session` is a single global session at
`LOOPS_HOME/session/`. But development doesn't happen in one stream. You
context-switch between projects, between threads within a project, between
meta-discussions and implementation.

**What's wanted:**
```bash
loops session start test-layers        # named session, own store
loops session start strange-loops-v1   # another named session
loops session ls                       # list active sessions
loops session status test-layers       # query one
loops session switch test-layers       # set as current
```

Each named session gets its own vertex + store at
`LOOPS_HOME/sessions/<name>/`. The default (unnamed) session still works for
quick, unstructured use.

**Why this matters for meta-discussion:** This workspace IS a session. The
threads here (test-layers, dev-harness, scaffold) are observations in a
meta-session about development methodology. Being able to `loops session start
meta-discussion` and emit decisions/threads into a named store would close the
loop — the meta-discussion about how we work would itself be tracked by the
system we're building.

**Design questions:**
- Is a named session just a vertex with a name? (Dissolution test: does it
  reduce to existing primitives?)
- Should sessions nest? (A meta-discussion session contains references to
  project-specific sessions)
- What's the relationship between a session store and a project store? Are they
  the same kind of thing?
- Does `LOOPS_HOME/sessions/` become a convention, or should it be configurable?
- Can sessions be archived? (Close, but keep the store for querying)

**The general form:** Sessions are *scoped stores*. The scope could be a project,
a thread, a discussion, a sprint. The store is always the same shape — facts
in, fold, query. The scope is just a name that determines where the store lives.

## Relationship to Documents

LOG.md and HANDOFF.md don't go away. They serve a different purpose:
- **Session facts** are structured, queryable, machine-readable
- **LOG.md** is narrative, contextual, captures the *why* and the *journey*
- **HANDOFF.md** is the human-readable summary for session pickup

The relationship: session facts are the source of truth for *state*. Documents
are the source of truth for *understanding*. You could generate a HANDOFF.md
from session facts, but you couldn't generate a good LOG.md entry — that
requires narrative judgment.

## Cross-Project Pattern

| Project | Session mechanism | Structured? | Queryable? |
|---------|------------------|-------------|------------|
| loops | `loops session` + LOG.md + HANDOFF.md | Yes (facts) | Yes (fold) |
| siftd | siftd itself (indexes conversations) | Yes (conversations) | Yes (search) |
| painted | HANDOFF.md only | No | No |
| gruel.network | changelog + handoffs | No | No |
| strange-loops | Inherits from loops | Planned | Planned |

siftd is interesting here — it's a session continuity tool for *conversations*,
not development sessions. But the shape is the same: observations go in, you
query them later. The question is whether siftd and loops session converge or
remain complementary (siftd for conversation history, loops session for
development state).

## Graduated

The named sessions design has moved into the loops monorepo:
- Design note: `~/Code/loops/docs/NAMED_SESSIONS.md`
- HANDOFF.md updated: named sessions is next step #1
- LOG.md updated: 2026-02-28 entry covers the full session
