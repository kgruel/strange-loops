# Narrative Debugging via Agent Swarm

Reference for picking up this process in future sessions.

## What This Is

Use an agent swarm to simulate a community encountering your project.
Each agent holds a persistent persona with specific background, mental
models, and communication style. Drop content into the shared channel,
observe reactions, catch "oh no" moments.

Descended from the NDTD work at `~/Documents/Obsidian/Programming/NDTD/`
but stripped of the theoretical scaffolding. The core is just: let
simulated users react to your stuff, see where they get confused or
excited, fix the gaps.

## Why Swarm, Not Single Context

A single LLM playing multiple characters optimizes for scene coherence.
Characters harmonize, agree too readily, and never genuinely disagree.
Separate agents with separate contexts can't read the room — if three
of them independently ask the same question, that's a real signal.

Proven in session: synthwave said "no caveats" about `print_block`,
mrbits independently corrected them. Would never happen in single-context
roleplay.

## Session 1 Setup (2026-02-25)

**Team:** `terminal-crafters` (TeamCreate)
**Agents:** 4x Opus via Task with team_name
**Communication:** SendMessage broadcast (each agent's message goes to all)
**Transcript:** Facilitator (team lead) serialized messages into markdown

### Personas Used

| Handle | Frame | Voice |
|--------|-------|-------|
| mrbits | ncurses veteran, 50s, knows raw escape sequences | Blunt, short, reads source not docs |
| noodle | Textual/Rich user, 30s, deployment dashboard builder | Friendly, comparative, asks "is this like X?" |
| ghost_pipe | Legacy CLI maintainer, 30k-line argparse tool | Lurker, speaks rarely, always practical |
| synthwave | Go (Bubble Tea) + Rust (ratatui), cross-ecosystem | Energetic, makes framework comparisons |

### Content Dropped

README with code sample and API table. Option 4 from design conversation:
"someone in the room just mentions they found this library" — most natural
entry point.

## What Worked

- Independent convergence on real findings (TTY detection, Lens confusion)
- Personas held their frames throughout (ghost_pipe spoke 5 times, all sharp)
- Transcript reads as a useful artifact on its own
- Agents articulated the value proposition better than the docs do

## What Didn't Work

- **Facilitator bottleneck**: every round required manual relay, nudging idle
  agents, serializing to transcript. User couldn't follow in real-time.
- **Cold start failure**: first broadcast produced no reactions. Had to
  individually nudge 3 of 4 agents.
- **Partial hallucination**: agents claimed to "read source" but mixed real
  code knowledge with inferred/hallucinated details. Missed `run_cli`'s
  existing TTY detection while confidently describing `print_block` internals.
- **Cost**: 4x Opus running concurrently is expensive for a design review.

## Discord Integration (Implemented)

### Prerequisites

1. Discord server with a channel for the session
2. A webhook created on that channel (Settings → Integrations → Webhooks)
3. A Discord bot with `Read Message History` permission added to the server
4. Environment variables set:
   - `DISCORD_WEBHOOK_URL` — the channel webhook URL
   - `DISCORD_BOT_TOKEN` — bot token (from Discord Developer Portal)
   - `DISCORD_CHANNEL_ID` — the channel's ID

### Running a Session

From a Claude Code session:

1. **Spawn persona agents** — use Task tool with each persona's agent type
   (e.g., `subagent_type: "discord-persona-mrbits"`)
2. **Drop content** — post to the channel via:
   ```bash
   uv run python tools/discord_chat.py post --persona facilitator --message "content here"
   ```
3. **Nudge agents** — send a message to each agent asking them to check the
   channel and respond naturally
4. **Watch in Discord** — messages appear in real-time with per-persona identities
5. **Interject** — post in Discord as yourself, then nudge agents again
6. **End** — send shutdown requests to agents

### What Changed from Session 1

- Messages appear in Discord in real-time (no facilitator relay)
- User can interject by posting directly in Discord
- Channel IS the transcript (no manual serialization)
- Agents respond concurrently
- Filesystem access restricted (Bash-only tools, channel-content-only)

### Limitations (Fixed by Standalone Bot Graduation)

- Orchestrator still nudges agents to check channel
- Agents don't spontaneously notice new messages
- No persona persistence across sessions

## Persona Design Principles

From session 1 observations:

- **Histories over roles.** "Person who's maintained a legacy CLI for 6 years"
  is better than "the practical user." Specific backgrounds produce specific
  reactions.
- **Mental model diversity is the axis that matters.** mrbits (raw terminal),
  noodle (Textual/widget-tree), synthwave (Elm/Bubble Tea), ghost_pipe
  (argparse/print) — each brings a different collision surface.
- **Lurkers are the best signal.** ghost_pipe spoke least and produced the
  sharpest finding ("that's the sentence"). Tell lurker personas to NOT
  respond to everything.
- **Let agents disagree.** Don't instruct them to be constructive or helpful.
  mrbits correcting synthwave was the most valuable moment.

## Relationship to NDTD

The NDTD corpus at `~/Documents/Obsidian/Programming/NDTD/` contains 12
documents. Most are over-documented theory. The useful artifacts are:

- `narrative-debugging-landing.md` — the kernel. Discord examples, cooking,
  speedrunning. "Design it, write what someone's thinking, fix the oh no."
- `narrative-debugging-llm-guide.md` — the LLM loop. 90-minute process,
  emotional loading, adversarial personas.
- `A Collaboration Story...` — honest postmortem. "The simplicity was there
  all along."

Everything else (cognitive theory, semantic guides, Maya scenarios, research
foundations, context window considerations) is scaffolding from a
dopamine-tap session. Read it for context if curious, don't treat it as
prescriptive.
