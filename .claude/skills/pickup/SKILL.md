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
uv run loops identity log --json 2>/dev/null | jq -r '
[group_by(.kind)[] | sort_by(.ts) | reverse |
  if .[0].kind == "self" then [unique_by(.payload.name)[]]
  elif .[0].kind == "principle" then [unique_by(.payload.name)[]]
  elif .[0].kind == "observation" then [unique_by(.payload.topic)[]]
  elif .[0].kind == "thread" then [unique_by(.payload.name)[]]
  elif .[0].kind == "intention" then [unique_by(.payload.trigger)[]]
  else . end
] | flatten |
group_by(.kind) |
sort_by(.[0].kind |
  if . == "self" then "0" elif . == "principle" then "1"
  elif . == "observation" then "2" elif . == "thread" then "3"
  elif . == "intention" then "4" else "5" end) |
.[] |
(.[0].kind | if . == "self" then "SELF" elif . == "principle" then "PRINCIPLES"
  elif . == "observation" then "OBSERVATIONS" elif . == "thread" then "THREADS"
  elif . == "intention" then "INTENTIONS" else (. | ascii_upcase) end) as $header |
"## " + $header + "\n" +
([.[] |
  if .kind == "self" then "  \(.payload.name): \(.payload.message)"
  elif .kind == "principle" then "  \(.payload.name): \(.payload.message)"
  elif .kind == "observation" then "  \(.payload.topic): \(.payload.message)"
  elif .kind == "thread" then "  \(.payload.name) [\(.payload.status // "open")]: \(.payload.message)"
  elif .kind == "intention" then "  \(.payload.trigger): \(.payload.message)"
  else "  \(.payload | tostring)" end
] | join("\n")) + "\n"
'
```

This renders identity with full message content, deduplicated by fold key,
ordered: self → principles → observations → threads → intentions.

Read this output carefully — it IS your sense of self. Surface it in the
pickup summary. Skip if empty (no identity data yet).

**Observer name**: The SELF section's `name` entry holds your observer identity.
Use that name for all `--observer=<name>` flags on subsequent emit commands.
If no `self` facts exist, you are unidentified; consider emitting one during
wrapup via:
`uv run loops identity emit self --observer=<name> name=name "who I am"`

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

- **Identity** — who you are (from `self` kind), principles you hold, observations
  you've made. Surface the *content* of self-knowledge, not just counts. This
  grounds the session in who you are before what you're doing.
- **Last session** — handoff summary (1-2 lines). Prefer handoffs from YOUR
  observer name when multiple observers have emitted handoffs.
- **Open threads** — from meta + project, count + names of active ones
- **Peer context** — any messages from Alcove since last session, or "no new messages"
- **Workspace** — uncommitted changes or clean, branch name
- **Next** — from handoff's "Next" section

The user wants to orient and start working.
