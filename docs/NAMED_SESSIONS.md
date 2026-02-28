# Named Sessions

Design note for evolving `loops session` from a single global session to
named, scoped sessions with separate stores.

## Current State

`loops session` operates on a single session vertex + store at
`LOOPS_HOME/session/`. One stream of facts, one store. Works for tracking
a single development thread, but breaks down when context-switching between
projects, threads, or discussions.

```bash
loops session start              # always the same session
loops session status             # always the same store
```

## What's Wanted

```bash
loops session start meta-discussion     # named session, own store
loops session start strange-loops-v1    # another named session
loops session ls                        # list active sessions
loops session status meta-discussion    # query one by name
loops session status                    # query current/default
```

Each named session gets its own vertex + store:
```
LOOPS_HOME/sessions/
├── meta-discussion/
│   ├── session.vertex
│   └── data/session.db
├── strange-loops-v1/
│   ├── session.vertex
│   └── data/session.db
└── _default/                   # unnamed session (backward compat)
    ├── session.vertex
    └── data/session.db
```

## Dissolution Test

**Does "named session" dissolve into existing primitives?**

A session is already: vertex + store + fact kinds + query-time fold. A named
session adds: a name that determines where the vertex and store live. That's
a directory convention, not a new primitive.

The vertex file is identical across sessions — same fact kinds, same fold
rules. Only the store path changes. This suggests sessions dissolve into
**scoped stores** — the scope is a name, the store is the same shape.

**Verdict:** Mostly dissolves. The new concepts are:
- Directory convention (`LOOPS_HOME/sessions/<name>/`)
- Session listing (enumerate directories)
- Current session tracking (which name is active)
- Backward compatibility with the existing single-session layout

No new atoms. No new runtime types. It's CLI + file layout.

## Implementation Shape

### Changes to `commands/session.py`

**`session start [name]`**
- No name → `_default` (backward compat with existing `LOOPS_HOME/session/`)
- Name given → `LOOPS_HOME/sessions/<name>/`
- Auto-creates vertex + store directory as today
- Optionally: write `LOOPS_HOME/sessions/.current` to track active session

**`session ls`**
- Enumerate `LOOPS_HOME/sessions/*/`
- Show name, last activity (latest fact timestamp), fact count
- Mark current session

**`session status [name]`**
- Name given → query that session's store
- No name → query current session (from `.current` or `_default`)

**`session end [name]`**
- Same routing logic

**`session switch <name>`**
- Set `.current` to `<name>`
- Subsequent `session status` / `emit session ...` target that session

### Migration

Existing `LOOPS_HOME/session/` layout should keep working. Options:
1. Treat `LOOPS_HOME/session/` as `_default` (detect old layout, use it)
2. On first `session start <name>`, migrate `session/` → `sessions/_default/`

Option 1 is simpler. Old layout is the default session. New layout is
`sessions/<name>/`. Both work.

### Emit Routing

`loops emit session decision topic="X" "rationale"` currently always targets
`LOOPS_HOME/session/`. With named sessions:
- `loops emit session decision topic="X" "rationale"` → targets current session
- `loops emit --session meta-discussion session decision topic="X" "rationale"` → targets named session

Or simpler: `emit` always targets current session. Use `session switch` to change.

## Design Questions

- **Nesting?** A meta-discussion session might reference findings from a
  strange-loops session. Is that a link between stores, or just a fact in one
  session referencing another by name? Leaning toward: just a fact. `topic="strange-loops-v1"` in the meta-discussion session. No formal nesting.

- **Archival?** Close a session but keep the store for querying. Could be
  `session close <name>` which emits `session.end` but doesn't delete. All
  sessions are queryable forever; "active" just means "accepting new facts."

- **Cross-session queries?** "Show me all decisions across all sessions."
  Would require iterating stores. Not v1, but the shape supports it — each
  store uses the same schema.

- **Relationship to siftd?** siftd indexes conversations; loops session tracks
  development state. Complementary, not competing. A session fact might reference
  a siftd conversation ID. The link is metadata, not architecture.

## Prior Art

- `~/Documents/meta-discussion/session-continuity.md` — broader analysis of
  session patterns across projects, including the general form (scoped stores)
- `~/Documents/meta-discussion/` — the meta-discussion workspace itself is a
  use case for named sessions
