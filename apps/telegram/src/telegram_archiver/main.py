"""Telegram message archiver — polling-based NDJSON exporter.

Connects as a user via MTProto (Telethon), fetches messages across all dialogs,
and emits one JSON object per message to stdout.  Cursor file tracks progress
so subsequent runs only fetch new messages.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    Channel,
    Chat,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
    User,
)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="telegram-poll",
        description="Poll Telegram for new messages, emit NDJSON to stdout",
    )
    p.add_argument(
        "--config", required=True,
        help="Path to JSON config file (api_id, api_hash, phone)",
    )
    p.add_argument(
        "--cursor", default="cursor.json",
        help="Path to cursor file tracking last-seen message per chat (default: cursor.json)",
    )
    p.add_argument(
        "--session", default="telegram",
        help="Telethon session name/path (default: telegram)",
    )
    p.add_argument(
        "--backfill", action="store_true",
        help="Fetch full message history (paginated, rate-limited) instead of just new messages",
    )
    p.add_argument(
        "--limit", type=int, default=100,
        help="Messages per batch (default: 100)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Config / cursor
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    missing = [k for k in ("api_id", "api_hash", "phone") if k not in cfg]
    if missing:
        raise SystemExit(f"Config missing required keys: {', '.join(missing)}")
    return cfg


def load_cursor(path: str) -> dict[str, int]:
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def save_cursor(path: str, cursor: dict[str, int]) -> None:
    with open(path, "w") as f:
        json.dump(cursor, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------

def classify_chat(entity) -> str:
    if isinstance(entity, User):
        return "private"
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        return "supergroup" if entity.megagroup else "channel"
    return "unknown"


def media_info(message) -> tuple[bool, str | None]:
    media = message.media
    if media is None:
        return False, None
    if isinstance(media, MessageMediaPhoto):
        return True, "photo"
    if isinstance(media, MessageMediaDocument):
        doc = media.document
        if doc:
            for attr in doc.attributes:
                name = type(attr).__name__
                if "Video" in name:
                    return True, "video"
                if "Audio" in name:
                    return True, "audio"
                if "Sticker" in name:
                    return True, "sticker"
            return True, "document"
        return True, "document"
    if isinstance(media, MessageMediaWebPage):
        return True, "webpage"
    return True, type(media).__name__.replace("MessageMedia", "").lower()


def format_message(msg, chat_id: int, title: str, chat_type: str) -> dict:
    sender = msg.sender
    has_media, mtype = media_info(msg)

    if sender:
        sender_name = (
            getattr(sender, "first_name", None)
            or getattr(sender, "title", None)
            or str(msg.sender_id)
        )
    else:
        sender_name = str(msg.sender_id)

    return {
        "message_id": msg.id,
        "chat_id": chat_id,
        "chat_title": title,
        "chat_type": chat_type,
        "sender_id": msg.sender_id,
        "sender_name": sender_name,
        "text": msg.text or "",
        "timestamp": msg.date.timestamp(),
        "has_media": has_media,
        "media_type": mtype,
    }


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

async def poll_chat(
    client: TelegramClient,
    dialog,
    cursor: dict[str, int],
    backfill: bool,
    limit: int,
) -> list[dict]:
    """Fetch messages from a single dialog.  Returns formatted dicts oldest-first."""
    chat_id = dialog.id
    title = dialog.name or str(dialog.id)
    ctype = classify_chat(dialog.entity)
    last_id = cursor.get(str(chat_id), 0)

    messages: list[dict] = []

    if backfill:
        offset_id = 0
        while True:
            batch = await client.get_messages(dialog, limit=limit, offset_id=offset_id)
            if not batch:
                break
            for msg in batch:
                if msg.text is not None or msg.media is not None:
                    messages.append(format_message(msg, chat_id, title, ctype))
            offset_id = batch[-1].id
            if len(batch) < limit:
                break
            # pace backfill to avoid rate limits
            await asyncio.sleep(1)
    else:
        batch = await client.get_messages(dialog, limit=limit, min_id=last_id)
        for msg in batch:
            if msg.text is not None or msg.media is not None:
                messages.append(format_message(msg, chat_id, title, ctype))

    # update cursor to newest message seen
    if messages:
        max_id = max(m["message_id"] for m in messages)
        cursor[str(chat_id)] = max(last_id, max_id)

    # return oldest-first for natural chronological output
    messages.reverse()
    return messages


async def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    cursor = load_cursor(args.cursor)

    client = TelegramClient(args.session, int(cfg["api_id"]), cfg["api_hash"])
    await client.start(phone=cfg["phone"])

    try:
        dialogs = await client.get_dialogs()
        total = 0

        for dialog in dialogs:
            try:
                messages = await poll_chat(client, dialog, cursor, args.backfill, args.limit)
                for msg in messages:
                    print(json.dumps(msg), flush=True)
                    total += 1
            except FloodWaitError as e:
                print(f"Rate limited on {dialog.name}: waiting {e.seconds}s", file=sys.stderr)
                await asyncio.sleep(e.seconds)
                # save progress so far, then retry this dialog
                save_cursor(args.cursor, cursor)
            except Exception as e:
                print(f"Error in {dialog.name}: {e}", file=sys.stderr)

        save_cursor(args.cursor, cursor)
        print(f"Exported {total} messages", file=sys.stderr)
    finally:
        await client.disconnect()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
