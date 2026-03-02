# Discord Narrative Debugging — Design

## What

Wire up the agent-swarm narrative debugging pattern (session 1: simulated
Discord channel via SendMessage) to a real Discord channel. Agents post
as individual webhook identities, you observe and interject in Discord.

## Why

Session 1 bottleneck was facilitator-as-relay: every message required
manual serialization, agent nudging, transcript maintenance. A real
Discord channel provides async visibility, natural interjection, and
the channel itself IS the transcript.

## Architecture

```
You (Discord)  ──────────────────────────┐
                                          ▼
Claude Code session (orchestrator)      Discord Channel
  ├─ Spawns persona agents               ▲  ▲  ▲  ▲
  ├─ Posts content via webhook ──────────►│  │  │  │
  └─ Nudges agents per round             │  │  │  │
                                          │  │  │  │
     mrbits ──── Bash ── discord_chat.py ─┘  │  │  │
     noodle ──── Bash ── discord_chat.py ────┘  │  │
     ghost_pipe ─ Bash ── discord_chat.py ──────┘  │
     synthwave ── Bash ── discord_chat.py ─────────┘
```

## Components

### 1. Discord Chat Script (`tools/discord_chat.py`)

CLI tool, ~100-150 LOC, two commands:

```bash
# Post as a persona (webhook with custom username + avatar)
python tools/discord_chat.py post \
  --persona mrbits \
  --message "That Block type is basically a 2D string buffer, right?"

# Read recent channel messages
python tools/discord_chat.py read --limit 20
```

**Implementation:**
- `post`: POST to Discord webhook URL with `username` and `avatar_url`
  fields. One webhook, multiple identities per call.
- `read`: GET `/channels/{channel_id}/messages` with bot token. Returns
  plain text: `[mrbits] message content here`.

**Dependencies:** `requests` (or `httpx`). No Discord library needed.

**Configuration (env vars):**
- `DISCORD_WEBHOOK_URL` — channel webhook for posting
- `DISCORD_BOT_TOKEN` — bot token for reading channel history
- `DISCORD_CHANNEL_ID` — target channel

### 2. Persona Agent Definitions (`.claude/agents/`)

One file per persona. Each restricts tools to `Bash` only (hard
enforcement — no Read, Glob, Grep, Edit, Write). Model: Sonnet.

```yaml
---
name: discord-persona-mrbits
description: mrbits persona for narrative debugging
tools: Bash
model: sonnet
---
```

Agent body contains:
- Persona description (history, mental model, communication style)
- Instructions to use `discord_chat.py` for reading/posting
- Explicit "you can ONLY see channel content" constraint
- "Lurking is valid" — don't respond to everything

### 3. Personas Config (`docs/narrative-debug/personas.json`)

Maps handle → avatar URL. Script looks up avatar when posting.

```json
{
  "mrbits": {"avatar_url": "...", "description": "ncurses veteran, 50s"},
  "noodle": {"avatar_url": "...", "description": "Textual/Rich user, 30s"},
  "ghost_pipe": {"avatar_url": "...", "description": "legacy CLI maintainer"},
  "synthwave": {"avatar_url": "...", "description": "Go/Rust cross-ecosystem"}
}
```

### 4. Orchestration Flow

**Setup:**
1. Verify Discord env vars present
2. TeamCreate
3. Spawn each persona agent via Task (subagent_type per agent definition)

**Running a session:**
1. Orchestrator posts content to channel (as facilitator persona)
2. Broadcasts to agents: "check the channel, respond naturally"
3. Agents run concurrently, read channel, post via webhook
4. User watches in Discord, interjects by posting directly
5. Orchestrator nudges next round when conversation slows

**Ending:**
- Shutdown requests to all agents
- Channel is the transcript

## What This Fixes

| Session 1 Problem | Discord Solution |
|---|---|
| Facilitator-as-relay bottleneck | Agents post directly to channel |
| No real-time visibility | Discord shows messages as they arrive |
| Manual transcript maintenance | Channel IS the transcript |
| User can't interject naturally | Post in Discord as yourself |
| Sequential agent responses | Concurrent background agents |

## What This Doesn't Fix (Yet)

- Orchestrator still nudges agents to check channel (not event-driven)
- Agents don't spontaneously notice new messages
- No persona persistence across sessions

These resolve with the standalone bot graduation (long-running Python
process with `discord.py` + Anthropic SDK). The CC-orchestrated version
is the proving ground.

## File Layout

```
tools/
  discord_chat.py              # CLI: post + read

.claude/agents/
  discord-persona-mrbits.md
  discord-persona-noodle.md
  discord-persona-ghost_pipe.md
  discord-persona-synthwave.md

docs/narrative-debug/
  process.md                   # Updated with Discord flow
  personas.json                # handle → avatar_url mapping
```

## Open Questions for Implementation

- Avatar images: generate or grab from a free service?
- Rate limiting: should the script enforce minimum delay between posts?
- Channel history depth: how much context should agents see per read?
