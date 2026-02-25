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


_SCRIPT_ROOT = Path(__file__).resolve().parent.parent
PERSONAS_PATH = _SCRIPT_ROOT / "docs" / "narrative-debug" / "personas.json"


def _load_dotenv() -> None:
    """Load .env file from project root if env vars aren't already set."""
    env_file = _SCRIPT_ROOT / ".env"
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()


_load_dotenv()


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
    req = Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "discord-chat/1.0"},
    )
    with urlopen(req) as resp:
        if resp.status not in (200, 204):
            print(f"Error: Discord returned {resp.status}", file=sys.stderr)
            sys.exit(1)


DISCORD_API_BASE = "https://discord.com/api/v10"


def read_messages(limit: int = 20) -> list[str]:
    """Read recent channel messages. Returns list of '[username] content' strings."""
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    if not token or not channel_id:
        print("Error: DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID must be set", file=sys.stderr)
        sys.exit(1)

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit={limit}"
    req = Request(url, headers={
        "Authorization": f"Bot {token}",
        "User-Agent": "discord-chat/1.0",
    })
    with urlopen(req) as resp:
        messages = json.loads(resp.read())

    # Discord returns newest first; reverse for chronological order
    lines = []
    for msg in reversed(messages):
        username = msg["author"]["username"]
        content = msg["content"]
        lines.append(f"[{username}] {content}")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Discord chat for narrative debugging")
    sub = parser.add_subparsers(dest="command")

    post_p = sub.add_parser("post", help="Post as a persona")
    post_p.add_argument("--persona", required=True, help="Persona handle")
    post_p.add_argument("--message", required=True, help="Message text")

    read_p = sub.add_parser("read", help="Read recent messages")
    read_p.add_argument("--limit", type=int, default=20, help="Number of messages")

    args = parser.parse_args()
    if args.command == "post":
        post_message(args.persona, args.message)
    elif args.command == "read":
        lines = read_messages(args.limit)
        for line in lines:
            print(line)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
