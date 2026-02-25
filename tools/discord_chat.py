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
