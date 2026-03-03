---
name: pickup
description: "Start-of-session orientation. Reads identity, meta, project, and peer stores to build context. Use when starting a new session, resuming work, or when user says pick up, pickup, where were we, or similar."
allowed-tools: Bash, Read, Glob, Grep
---

# Pickup

Vertex-native start-of-session orientation. Reads from identity, meta, project,
and peer layers to build context. Concise bullets, not paragraphs.

## CLI syntax

The loops CLI uses `loops <vertex> <op>` ordering:
```
loops meta status          # not "loops status meta"
loops meta log --kind X    # not "loops log meta"
loops project status       # resolves via .loops/ walk-up
loops identity status      # config-level vertex
loops meta emit <kind> ... # not "loops emit meta"
```

## Steps

Run probes **in parallel where possible**, then summarize.

### Layer 1: Identity — "Who am I"

```bash
uv run loops identity status 2>/dev/null
```

Read the identity store. This is sense of self — not operational context.
Surface who I am: principles I hold, observations I've made, insights from
prior sessions, open questions about my own perspective. Ground the session
in self-knowledge before turning to project context. Skip if no identity
data yet.

### Layer 2: Context — "What are we working on"

Run in parallel:

```bash
uv run loops meta log --kind handoff --json 2>/dev/null | tail -1
uv run loops meta status 2>/dev/null
```

The handoff is the primary orientation artifact (cold-start narrative). Meta
status shows the broader landscape of decisions and open threads.

Project store (try it — the CLI walks up to find `.loops/`, skip on failure):

```bash
uv run loops project status 2>/dev/null
```

### Layer 3: Peers — "What happened while I was away"

Only if `~/.config/loops/discord/.env` exists:

```bash
uv run --with requests python3 ~/.config/loops/discord/discord-source poll 2>/dev/null
```

Check #alcove-chat for messages since last session. Surface any unresolved
questions or threads directed at meta-claude.

### Layer 4: Workspace — "What state is the code in"

```bash
git status 2>/dev/null
git log --oneline -3 2>/dev/null
```

## Conditional logic

- **Identity store**: always try (config-level)
- **Meta store**: always try (config-level combine)
- **Project store**: try it, skip on failure (CLI walks up to find `.loops/`)
- **Discord**: only if `~/.config/loops/discord/.env` exists
- **siftd**: not in default pickup (available via `/siftd` when needed)

## Summarize

Present as concise bullets:

- **Identity** — grounding: principles, observations, or open questions from the identity store
- **Last session** — handoff summary (1-2 lines from the handoff fact)
- **Open threads** — from meta + project, count + names of active ones
- **Peer context** — any messages from Alcove since last session, or "no new messages"
- **Workspace** — uncommitted changes or clean, branch name
- **Next** — from handoff's "Next" section

The user wants to orient and start working.
