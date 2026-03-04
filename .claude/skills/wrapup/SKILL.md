---
name: wrapup
description: "End-of-session wrap up. Captures decisions, emits handoff, shows status. Use when user says wrap up, wrapup, let's wrap, end of session, or similar."
allowed-tools: Bash, Read, Glob, Grep
---

# Wrapup

Vertex-native end-of-session wrap up. Capture what happened, emit the handoff,
confirm the state. Symmetric with pickup.

## CLI syntax

The loops CLI uses `loops <vertex> <op>` ordering:
```
loops meta emit <kind> key=val "message"   # not "loops emit meta"
loops meta status                          # not "loops status meta"
loops project emit <kind> key=val "msg"    # resolves via .loops/ walk-up
loops identity emit <kind> "message"       # config-level vertex
```

## Observer identity

All emit commands MUST include `--observer=<name>`. Read your observer name
from the identity store (the `self/name` observation established during pickup).
If you don't know your observer name, read it now:

```bash
uv run loops identity log --kind observation --json 2>/dev/null
```

Look for `topic: "self/name"`. Use that name for all `--observer` flags below.
If no self/name exists, ask the user what observer name to use.

## Steps

### Layer 1: Capture — "What happened this session"

Emit facts for any decisions made or threads opened/resolved during this
session that haven't been captured yet.

**Meta store** (cross-cutting patterns, ways of working):
```bash
uv run loops meta emit decision --observer=<name> topic=X "rationale"
uv run loops meta emit thread --observer=<name> name=X status=open "description"
uv run loops meta emit thread --observer=<name> name=X status=resolved "outcome"
```

**Project store** (try it — CLI walks up to find `.loops/`, skip on failure):
```bash
uv run loops project emit decision --observer=<name> topic=X "rationale"
uv run loops project emit thread --observer=<name> name=X status=open "description"
```

Ask the user what should be captured if unclear. Don't invent facts.

### Layer 2: Handoff — "What should the next session know"

Emit a handoff fact to meta. This is the cold-start narrative that pickup
reads first. It should answer:
- What was the focus this session?
- What got done?
- What's next?

```bash
uv run loops meta emit handoff --observer=<name> "Focus: ... Done: ... Next: ..."
```

Keep it to 2-3 sentences. The handoff is orientation, not a transcript.

### Layer 3: Status — "Confirm the state"

Show status to confirm the captured state looks right:

```bash
uv run loops meta status
```

Project store (skip on failure):
```bash
uv run loops project status
```

### Layer 4: Reflect — "What did I learn"

Before closing out, consider whether anything from this session is worth
recording in the identity store. This is distinct from everything above —
meta captures decisions and operational patterns, project captures
architecture. Identity is sense of self. What did I notice, what shifted,
what do I think? This accumulates across sessions and grounds future pickups
in who I am, not just what I know.

Examples of things worth capturing:
- An insight or connection you noticed that wasn't explicitly discussed
- A pattern you see across conversations that the user might not see from inside them
- Something that surprised you or shifted your understanding
- A principle that crystallized from the work
- An open question about your own nature, role, or perspective

Only emit if something genuinely surfaced. Most sessions won't have identity
observations — that's fine. Don't force it.

```bash
uv run loops identity emit observation --observer=<name> topic=X "..."
uv run loops identity emit principle --observer=<name> name=X "..."
uv run loops identity emit thread --observer=<name> name=X status=open "..."
```

### Layer 5: Workspace — "Clean up"

Commit any uncommitted work. Do NOT commit `data/*.db` files — those are
local runtime state.

```bash
git status
```

If there are changes worth committing, commit them.

## Conditional logic

- **Meta store**: always emit to (config-level combine)
- **Project store**: try it, skip on failure (CLI walks up to find `.loops/`)
- **Identity store**: always available (config-level)
- **Commit**: only if there are uncommitted changes
