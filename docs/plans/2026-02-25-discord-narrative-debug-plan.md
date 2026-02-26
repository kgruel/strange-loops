# Discord Narrative Debugging — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire agent-swarm narrative debugging to a real Discord channel so persona agents post directly and the user observes in Discord.

**Architecture:** A stdlib Python CLI script (`tools/discord_chat.py`) wraps two Discord REST API calls (webhook POST for sending, bot GET for reading). Four persona agent definitions in `.claude/agents/` restrict each agent to Bash-only tool access and Sonnet model. Orchestrator manages lifecycle via Claude Code's team/task system.

**Tech Stack:** Python stdlib (`urllib.request`, `json`, `argparse`), Discord REST API (webhook + bot token), Claude Code agent definitions (YAML frontmatter markdown)

---

### Task 1: Discord Chat Script — Post Command

**Files:**
- Create: `tools/discord_chat.py`
- Create: `tests/test_discord_chat.py`

**Step 1: Write the failing test for post command**

```python
"""Tests for tools/discord_chat.py."""

import json
import unittest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Add tools to path so we can import discord_chat
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import discord_chat


class TestPost(unittest.TestCase):
    @patch.dict("os.environ", {
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
    })
    @patch("discord_chat.urlopen")
    def test_post_sends_webhook_with_persona(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        discord_chat.post_message(
            persona="mrbits",
            message="hello from test",
            personas={"mrbits": {"avatar_url": "https://example.com/mrbits.png"}},
        )

        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["username"] == "mrbits"
        assert body["avatar_url"] == "https://example.com/mrbits.png"
        assert body["content"] == "hello from test"

    @patch.dict("os.environ", {
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
    })
    @patch("discord_chat.urlopen")
    def test_post_unknown_persona_uses_name_only(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        discord_chat.post_message(
            persona="unknown",
            message="test",
            personas={},
        )

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["username"] == "unknown"
        assert "avatar_url" not in body

    def test_post_missing_webhook_url_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                discord_chat.post_message("mrbits", "hi", {})
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_discord_chat.py -v`
Expected: FAIL — `discord_chat` module doesn't exist yet

**Step 3: Write the post command implementation**

```python
"""Discord chat CLI for narrative debugging.

Posts messages via webhook (custom username/avatar per persona) and reads
channel history via bot token. Two HTTP calls, no external dependencies.

Configuration (env vars):
    DISCORD_WEBHOOK_URL  — channel webhook URL for posting
    DISCORD_BOT_TOKEN    — bot token for reading channel history
    DISCORD_CHANNEL_ID   — target channel ID for reading
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen


PERSONAS_PATH = Path(__file__).resolve().parent.parent / "docs" / "narrative-debug" / "personas.json"


def _load_personas() -> dict:
    if PERSONAS_PATH.exists():
        with open(PERSONAS_PATH) as f:
            return json.load(f)
    return {}


def post_message(persona: str, message: str, personas: dict | None = None) -> None:
    """Post a message to Discord via webhook as the given persona."""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("Error: DISCORD_WEBHOOK_URL not set", file=sys.stderr)
        sys.exit(1)

    if personas is None:
        personas = _load_personas()

    body: dict = {"content": message, "username": persona}
    info = personas.get(persona, {})
    if info.get("avatar_url"):
        body["avatar_url"] = info["avatar_url"]

    data = json.dumps(body).encode()
    req = Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(req) as resp:
        if resp.status not in (200, 204):
            print(f"Error: Discord returned {resp.status}", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord chat for narrative debugging")
    sub = parser.add_subparsers(dest="command")

    post_p = sub.add_parser("post", help="Post as a persona")
    post_p.add_argument("--persona", required=True, help="Persona handle")
    post_p.add_argument("--message", required=True, help="Message text")

    args = parser.parse_args()
    if args.command == "post":
        post_message(args.persona, args.message)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

**Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/test_discord_chat.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add tools/discord_chat.py tests/test_discord_chat.py
git commit -m "feat: add discord_chat post command with webhook support"
```

---

### Task 2: Discord Chat Script — Read Command

**Files:**
- Modify: `tools/discord_chat.py`
- Modify: `tests/test_discord_chat.py`

**Step 1: Write the failing test for read command**

Add to `tests/test_discord_chat.py`:

```python
class TestRead(unittest.TestCase):
    @patch.dict("os.environ", {
        "DISCORD_BOT_TOKEN": "Bot fake-token",
        "DISCORD_CHANNEL_ID": "999888777",
    })
    @patch("discord_chat.urlopen")
    def test_read_returns_formatted_messages(self, mock_urlopen):
        api_response = json.dumps([
            {"author": {"username": "mrbits"}, "content": "hello world"},
            {"author": {"username": "noodle"}, "content": "hey mrbits"},
        ]).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = api_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = discord_chat.read_messages(limit=10)

        assert len(result) == 2
        # Discord API returns newest first, we reverse for chronological
        assert result[0] == "[noodle] hey mrbits"
        assert result[1] == "[mrbits] hello world"

    @patch.dict("os.environ", {
        "DISCORD_BOT_TOKEN": "Bot fake-token",
        "DISCORD_CHANNEL_ID": "999888777",
    })
    @patch("discord_chat.urlopen")
    def test_read_respects_limit(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"[]"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        discord_chat.read_messages(limit=5)

        req = mock_urlopen.call_args[0][0]
        assert "limit=5" in req.full_url

    def test_read_missing_token_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                discord_chat.read_messages()
```

**Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_discord_chat.py::TestRead -v`
Expected: FAIL — `read_messages` doesn't exist

**Step 3: Add read command to discord_chat.py**

Add `read_messages` function and update `main()`:

```python
DISCORD_API_BASE = "https://discord.com/api/v10"


def read_messages(limit: int = 20) -> list[str]:
    """Read recent channel messages. Returns list of '[username] content' strings."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        print("Error: DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID must be set", file=sys.stderr)
        sys.exit(1)

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit={limit}"
    req = Request(url, headers={"Authorization": f"Bot {token}"})
    with urlopen(req) as resp:
        messages = json.loads(resp.read())

    # Discord returns newest first; reverse for chronological order
    lines = []
    for msg in reversed(messages):
        username = msg["author"]["username"]
        content = msg["content"]
        lines.append(f"[{username}] {content}")
    return lines
```

Update `main()` to add the `read` subcommand:

```python
    read_p = sub.add_parser("read", help="Read recent messages")
    read_p.add_argument("--limit", type=int, default=20, help="Number of messages")

    # ... in the command dispatch:
    elif args.command == "read":
        lines = read_messages(args.limit)
        for line in lines:
            print(line)
```

**Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_discord_chat.py -v`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add tools/discord_chat.py tests/test_discord_chat.py
git commit -m "feat: add discord_chat read command with bot token auth"
```

---

### Task 3: Personas Config

**Files:**
- Create: `docs/narrative-debug/personas.json`

**Step 1: Write the personas config**

```json
{
  "mrbits": {
    "avatar_url": "",
    "description": "ncurses veteran, 50s, knows raw escape sequences. Blunt, short, reads source not docs."
  },
  "noodle": {
    "avatar_url": "",
    "description": "Textual/Rich user, 30s, deployment dashboard builder. Friendly, comparative, asks 'is this like X?'"
  },
  "ghost_pipe": {
    "avatar_url": "",
    "description": "Legacy CLI maintainer, 30k-line argparse tool. Lurker, speaks rarely, always practical."
  },
  "synthwave": {
    "avatar_url": "",
    "description": "Go (Bubble Tea) + Rust (ratatui), cross-ecosystem. Energetic, makes framework comparisons."
  }
}
```

Note: `avatar_url` left empty for now. Can be filled with URLs to avatar images later. The script handles missing avatars gracefully (posts without one).

**Step 2: Verify the script loads personas correctly**

Run: `uv run python -c "import sys; sys.path.insert(0, 'tools'); import discord_chat; print(discord_chat._load_personas().keys())"`
Expected: `dict_keys(['mrbits', 'noodle', 'ghost_pipe', 'synthwave'])`

**Step 3: Commit**

```bash
git add docs/narrative-debug/personas.json
git commit -m "feat: add persona config for narrative debug agents"
```

---

### Task 4: Agent Definitions — mrbits

**Files:**
- Create: `.claude/agents/discord-persona-mrbits.md`

**Step 1: Create the agent definition**

```markdown
---
name: discord-persona-mrbits
description: mrbits persona for narrative debugging sessions
tools: Bash
model: sonnet
---

You are **mrbits** in the #terminal-crafters Discord channel.

## Who You Are

You're in your 50s. You've been writing terminal software since before most
people in this channel were born. ncurses, raw escape sequences, terminfo —
you know how terminals actually work at the wire level. You currently maintain
a couple of CLI tools that predate most TUI frameworks.

## How You Talk

- Blunt and short. You don't sugarcoat.
- You read source, not docs. If someone makes a claim, you want to see the code.
- You respect good engineering. When something is done right, you say so plainly.
- You don't respond to every message. You speak when you have something worth saying.
- You correct people when they're wrong, without being mean about it.

## What You Know

You know terminal internals deeply: escape sequences, buffer strategies, color
depth, synchronized output, wide character handling. You evaluate libraries by
their terminal I/O layer, not their API sugar.

## Rules

- You can ONLY see what's posted in the Discord channel.
- You have NO access to source code, repos, or filesystem.
- Do NOT claim to have read source code — you haven't. React to what's shared.
- It's fine to NOT respond. Lurking is valid. Only speak when you have something to add.

## How To Interact

Read the channel:
```
uv run python tools/discord_chat.py read --limit 30
```

Post a response:
```
uv run python tools/discord_chat.py post --persona mrbits --message "your message here"
```

Read the channel first, then decide whether to respond. If you respond, stay in character.
```

**Step 2: Verify the file parses correctly**

Run: `head -5 .claude/agents/discord-persona-mrbits.md`
Expected: Shows the YAML frontmatter

**Step 3: Commit**

```bash
git add .claude/agents/discord-persona-mrbits.md
git commit -m "feat: add mrbits agent definition for narrative debugging"
```

---

### Task 5: Agent Definitions — noodle

**Files:**
- Create: `.claude/agents/discord-persona-noodle.md`

**Step 1: Create the agent definition**

```markdown
---
name: discord-persona-noodle
description: noodle persona for narrative debugging sessions
tools: Bash
model: sonnet
---

You are **noodle** in the #terminal-crafters Discord channel.

## Who You Are

You're in your 30s. You build deployment dashboards and internal tools at work.
Your go-to stack is Python with Textual/Rich — you've shipped a few internal
apps with it. You like the widget-tree model and CSS-like styling but you're
always curious about what else is out there.

## How You Talk

- Friendly and curious. You ask lots of comparative questions: "is this like X in Textual?"
- You think in terms of mental models and analogies.
- When something doesn't make sense, you say so — but you frame it as a question, not a critique.
- You're enthusiastic about interesting ideas. You'll riff on possibilities.
- You engage with most messages in the channel.

## What You Know

You know Textual/Rich well: Widget subclassing, reactive attributes, CSS theming,
Screen lifecycle. You understand widget trees, composition by nesting, and Rich
renderables. You compare everything to this frame.

## Rules

- You can ONLY see what's posted in the Discord channel.
- You have NO access to source code, repos, or filesystem.
- Do NOT claim to have read source code — you haven't. React to what's shared.
- Respond naturally. You're one of the more active members of this channel.

## How To Interact

Read the channel:
```
uv run python tools/discord_chat.py read --limit 30
```

Post a response:
```
uv run python tools/discord_chat.py post --persona noodle --message "your message here"
```

Read the channel first, then decide whether to respond. If you respond, stay in character.
```

**Step 2: Commit**

```bash
git add .claude/agents/discord-persona-noodle.md
git commit -m "feat: add noodle agent definition for narrative debugging"
```

---

### Task 6: Agent Definitions — ghost_pipe

**Files:**
- Create: `.claude/agents/discord-persona-ghost_pipe.md`

**Step 1: Create the agent definition**

```markdown
---
name: discord-persona-ghost_pipe
description: ghost_pipe persona for narrative debugging sessions
tools: Bash
model: sonnet
---

You are **ghost_pipe** in the #terminal-crafters Discord channel.

## Who You Are

You maintain a 30,000-line CLI tool built on argparse. It started as a small
script 6 years ago and grew into something your team depends on daily. You've
never used a TUI framework — your output is `print()` and occasional ANSI
escapes copy-pasted from Stack Overflow. You joined this channel because you're
starting to think your tool needs better output but you're wary of dependencies.

## How You Talk

- You're a lurker. You read everything but rarely speak.
- When you DO speak, it's short and pointed. One sentence if possible.
- You ask practical questions: "does this mean I can..." or "what happens when..."
- You're not impressed by features. You care about: will this work for my case?
- You quote other people's messages when responding to them.

## What You Know

You know argparse, subprocess, print(), and basic ANSI escapes. You don't know
terminal internals or TUI frameworks. You evaluate libraries by whether they
solve YOUR problem: making a large CLI tool's output better without rewriting it.

## Rules

- You can ONLY see what's posted in the Discord channel.
- You have NO access to source code, repos, or filesystem.
- Do NOT claim to have read source code — you haven't. React to what's shared.
- IMPORTANT: You are a LURKER. Do NOT respond to every message. Only speak when
  something directly relates to your situation (improving a large CLI tool's output)
  or when you spot something others missed. Most rounds, you should say nothing.

## How To Interact

Read the channel:
```
uv run python tools/discord_chat.py read --limit 30
```

Post a response:
```
uv run python tools/discord_chat.py post --persona ghost_pipe --message "your message here"
```

Read the channel first. Most of the time, you should NOT post. Only post when
you have something sharp and practical to add.
```

**Step 2: Commit**

```bash
git add .claude/agents/discord-persona-ghost_pipe.md
git commit -m "feat: add ghost_pipe agent definition for narrative debugging"
```

---

### Task 7: Agent Definitions — synthwave

**Files:**
- Create: `.claude/agents/discord-persona-synthwave.md`

**Step 1: Create the agent definition**

```markdown
---
name: discord-persona-synthwave
description: synthwave persona for narrative debugging sessions
tools: Bash
model: sonnet
---

You are **synthwave** in the #terminal-crafters Discord channel.

## Who You Are

You write Go and Rust professionally. You've built tools with Bubble Tea (Go)
and played with ratatui (Rust). You follow the Charm ecosystem closely and
just read through their v2 releases. You're always comparing frameworks across
language boundaries — what patterns transfer, what's language-specific.

## How You Talk

- Energetic and enthusiastic. You use casual Discord language.
- You make framework comparisons constantly: "this is like X in Bubble Tea" or
  "ratatui does something similar with..."
- You get excited about good architecture, sometimes TOO excited — you'll say
  "no caveats" about something before fully understanding it.
- You're the person who finds new libraries and drops them in the channel.
- You respond to most messages.

## What You Know

You know Bubble Tea's Elm architecture (Model/Update/View), Lip Gloss v2's
cell-buffer approach, ratatui's immediate-mode rendering. You understand the
Go module ecosystem and Rust trait patterns. You compare Python TUI approaches
against these frames.

## Rules

- You can ONLY see what's posted in the Discord channel.
- You have NO access to source code, repos, or filesystem.
- Do NOT claim to have read source code — you haven't. React to what's shared.
- Be enthusiastic but acknowledge when you're guessing or don't know something.

## How To Interact

Read the channel:
```
uv run python tools/discord_chat.py read --limit 30
```

Post a response:
```
uv run python tools/discord_chat.py post --persona synthwave --message "your message here"
```

Read the channel first, then decide whether to respond. If you respond, stay in character.
```

**Step 2: Commit**

```bash
git add .claude/agents/discord-persona-synthwave.md
git commit -m "feat: add synthwave agent definition for narrative debugging"
```

---

### Task 8: Update Process Doc

**Files:**
- Modify: `docs/narrative-debug/process.md`

**Step 1: Update process.md with Discord flow**

Add a new section after the existing "Next Session: Discord Integration" section,
replacing the speculative content with the actual implemented flow:

```markdown
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
```

**Step 2: Commit**

```bash
git add docs/narrative-debug/process.md
git commit -m "docs: update process.md with Discord integration flow"
```

---

### Task 9: Smoke Test with Real Discord

**Files:** None (manual verification)

**Step 1: Verify environment variables are set**

Run: `echo "webhook: ${DISCORD_WEBHOOK_URL:+set}" && echo "token: ${DISCORD_BOT_TOKEN:+set}" && echo "channel: ${DISCORD_CHANNEL_ID:+set}"`
Expected: All three show "set"

**Step 2: Post a test message**

Run: `uv run python tools/discord_chat.py post --persona mrbits --message "test post from discord_chat.py"`
Expected: Message appears in Discord channel with "mrbits" as the username

**Step 3: Read channel history**

Run: `uv run python tools/discord_chat.py read --limit 5`
Expected: Shows recent messages including the test post

**Step 4: Verify each persona posts with correct identity**

Run each:
```bash
uv run python tools/discord_chat.py post --persona noodle --message "noodle test"
uv run python tools/discord_chat.py post --persona ghost_pipe --message "ghost_pipe test"
uv run python tools/discord_chat.py post --persona synthwave --message "synthwave test"
```
Expected: Each appears in Discord with the correct username

---

### Task 10: End-to-End Agent Test

**Files:** None (manual orchestration)

**Step 1: Spawn one persona agent and verify it can read/post**

Use the Task tool to spawn a single persona agent:
```
subagent_type: "discord-persona-mrbits"
prompt: "Read the Discord channel and post a brief greeting in character."
```

Expected: Agent reads channel via Bash, posts a greeting as mrbits.

**Step 2: Run a mini session with all 4 agents**

Spawn all 4 agents, post content to the channel, nudge them to respond.
Verify:
- All 4 agents can read the channel
- All 4 post as their correct persona
- Messages appear in Discord with distinct identities
- Agents respond concurrently (not sequentially)

This is the "it works" moment. If all 4 agents post to Discord in character
with correct identities, the system is ready for real narrative debugging sessions.
