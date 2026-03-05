# CLAUDE.md Hierarchy

How project guidance layers from global to local, and what belongs at each level.

## The Levels

```
~/.config/claude/CLAUDE.md          # global: personal preferences + principles
project/CLAUDE.md                   # root: model, build, structure, conventions
project/libs/<lib>/CLAUDE.md        # library: domain focus, key invariants, API
project/apps/<app>/CLAUDE.md        # app: domain conventions, dev cycle, CLI shape
```

### Level 0: Global (`~/.config/claude/CLAUDE.md`)

**Audience:** Every project, every session.

**Contains:**
- Communication preferences (direct, concise, explain *why*)
- Design principles (explicit over implicit, dissolution test, patterns over point solutions)
- Collaboration style (one question at a time, pushback is engagement)

**Does NOT contain:** Project-specific anything. This is about *how you work*,
not *what you're working on*.

### Level 1: Project Root (`project/CLAUDE.md`)

**Audience:** Anyone (human or AI) working in this repo.

**Contains:**
- The model / domain overview (what the system IS)
- Build & test commands
- Project structure (directory layout with descriptions)
- Data flow / architecture diagram
- Key patterns and conventions
- Import rules and dependency policy
- References to deeper docs

**Examples:**
- loops: three atoms, data flow diagram, kind namespacing, Spec naming convention
- siftd: source of truth docs, LLM instructions, quick reference for hosts/services
- painted: layer stack, primitives, component model

### Level 2: Library (`libs/<lib>/CLAUDE.md`)

**Audience:** Someone working within this specific library.

**Contains:**
- What this library's one concern is
- Key types and their relationships
- Layer stack / pipeline within the lib
- Invariants specific to this lib
- Package structure

**Why it exists:** The root CLAUDE.md is already long. Library-specific detail
(e.g., cells' rendering pipeline, engine's compiler phases) would bloat it.
The library CLAUDE.md answers "I'm about to edit a file in this lib, what do I
need to know?"

### Level 3: App (`apps/<app>/CLAUDE.md`)

**Audience:** Someone working on this specific application.

**Contains:**
- How this app maps to the underlying model
- Dev cycle commands (`./dev check`, etc.)
- CLI shape and subcommand conventions
- Testing conventions specific to this app
- What's NOT in scope for v1

**Examples:**
- strange-loops: "tasks are loops," harness interface, worktree strategy, dev harness
- hlab: "DSL defines data flow, Python handles everything else"

## What Goes Where (Decision Framework)

| Question | Where it goes |
|----------|--------------|
| How do I prefer to communicate? | Global |
| What is this system? | Root |
| How do I build and test? | Root |
| What can module X import? | Root (cross-cutting) or lib (internal) |
| What does this library do? | Lib |
| What invariants does this lib enforce? | Lib |
| How do I add a new command? | App |
| What's the dev cycle for this app? | App |
| What testing patterns do we use? | Root (general) + App (specific) |

## Anti-patterns

- **God CLAUDE.md** — everything in the root file. Gets too long, important
  things buried. Split when a section serves only one lib/app.
- **Stale CLAUDE.md** — conventions documented but no longer true. Architecture
  tests (tier 3) help here — if the CLAUDE.md says "frozen dataclasses" and a
  test enforces it, the doc can't go stale without the test failing.
- **Redundant CLAUDE.md** — lib CLAUDE.md repeating what root says. Each level
  should add, not repeat. Reference up: "See root CLAUDE.md for build commands."
- **Missing CLAUDE.md** — new lib/app created without one. The scaffold template
  should include a CLAUDE.md stub.

## Relationship to Other Docs

CLAUDE.md is for AI and human *working context*. It's not:
- **README.md** — for external users/contributors (how to install, what it does)
- **HANDOFF.md** — for session continuity (what's next, what's deferred)
- **LOG.md** — for history (what happened when)
- **DESIGN.md** — for architecture decisions (why this shape)
- **VOCABULARY.md** — for definitions (what terms mean)

Each doc has a different audience and update cadence. CLAUDE.md changes when
conventions change. LOG.md grows every session. HANDOFF.md is rewritten each
session. DESIGN.md is written once and updated rarely.
