"""Discord message archiver — polling-based NDJSON exporter.

Wraps DiscordChatExporter CLI (Tyrrrz/DiscordChatExporter) to export messages
across all accessible channels, then re-emits as NDJSON to stdout.  Cursor
file tracks progress so subsequent runs only fetch new messages.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discord-poll",
        description="Poll Discord for new messages via DiscordChatExporter, emit NDJSON to stdout",
    )
    p.add_argument(
        "--config", required=True,
        help="Path to JSON config file (token, optional exporter_path)",
    )
    p.add_argument(
        "--cursor", default="cursor.json",
        help="Path to cursor file tracking last-seen message per channel (default: cursor.json)",
    )
    p.add_argument(
        "--exporter-path", default=None,
        help="Path to DiscordChatExporter.Cli binary (overrides config file)",
    )
    p.add_argument(
        "--backfill", action="store_true",
        help="Fetch full message history instead of just new messages",
    )
    p.add_argument(
        "--channels", nargs="*", default=None,
        help="Export only these channel IDs (default: all accessible channels)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Config / cursor
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        cfg = json.load(f)
    if "token" not in cfg:
        raise SystemExit("Config missing required key: token")
    return cfg


def load_cursor(path: str) -> dict[str, str]:
    """Load cursor: channel_id -> last_message_id (both as strings)."""
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return {}


def save_cursor(path: str, cursor: dict[str, str]) -> None:
    with open(path, "w") as f:
        json.dump(cursor, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# DiscordChatExporter interaction
# ---------------------------------------------------------------------------

def get_exporter(args: argparse.Namespace, cfg: dict) -> str:
    """Resolve exporter binary path: CLI flag > config > default."""
    if args.exporter_path:
        return args.exporter_path
    return cfg.get("exporter_path", "DiscordChatExporter.Cli")


def list_channels(exporter: str, token: str) -> list[dict]:
    """List all accessible channels via DiscordChatExporter.

    Returns parsed channel dicts from the CLI's JSON output.
    Each dict has: id, name, type, guildId, guildName (if applicable).
    """
    cmd = [exporter, "channels", "-t", token, "--json"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"Error listing channels: {result.stderr.strip()}", file=sys.stderr)
        return []

    channels = []
    # DiscordChatExporter outputs one JSON object per line
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            channels.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return channels


def classify_channel(channel_type: str) -> str:
    """Map DiscordChatExporter channel type to our simplified type."""
    mapping = {
        "DirectTextChat": "dm",
        "DirectGroupTextChat": "group",
        "GuildTextChat": "text",
        "GuildVoiceChat": "voice",
        "GuildCategory": "category",
        "GuildNews": "text",
        "GuildNewsThread": "text",
        "GuildPublicThread": "text",
        "GuildPrivateThread": "text",
        "GuildForum": "forum",
        "GuildStageVoice": "voice",
    }
    return mapping.get(channel_type, channel_type.lower())


def export_channel(
    exporter: str,
    token: str,
    channel_id: str,
    output_path: str,
    after: str | None = None,
) -> bool:
    """Export a single channel to JSON file.  Returns True on success."""
    cmd = [
        exporter, "export",
        "-t", token,
        "-c", channel_id,
        "-f", "Json",
        "-o", output_path,
    ]
    if after:
        cmd.extend(["--after", after])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        stderr = result.stderr.strip()
        # "No messages" is not an error — just an empty channel since cursor
        if "no messages" in stderr.lower() or "nothing to export" in stderr.lower():
            return True
        print(f"Error exporting channel {channel_id}: {stderr}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# JSON parsing — DiscordChatExporter output → NDJSON
# ---------------------------------------------------------------------------

def parse_timestamp(ts_str: str) -> float:
    """Parse ISO 8601 timestamp to epoch float."""
    # DiscordChatExporter uses ISO 8601 with timezone
    # Handle both "2024-01-15T10:30:00+00:00" and "2024-01-15T10:30:00Z"
    ts_str = ts_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts_str)
    return dt.timestamp()


def extract_media(msg: dict) -> tuple[bool, str | None, list[str]]:
    """Extract media info from a DiscordChatExporter message.

    Returns (has_media, media_type, attachment_urls).
    """
    attachments = msg.get("attachments", [])
    embeds = msg.get("embeds", [])
    stickers = msg.get("stickers", [])

    urls = [a.get("url", "") for a in attachments if a.get("url")]

    if not attachments and not embeds and not stickers:
        return False, None, []

    if stickers:
        return True, "sticker", urls
    if attachments:
        # classify by first attachment content type
        first = attachments[0]
        content_type = first.get("contentType", "") or ""
        if content_type.startswith("image/"):
            media_type = "image"
        elif content_type.startswith("video/"):
            media_type = "video"
        elif content_type.startswith("audio/"):
            media_type = "audio"
        else:
            media_type = "attachment"
        return True, media_type, urls
    if embeds:
        return True, "embed", urls

    return True, None, urls


def format_message(
    msg: dict,
    channel_id: str,
    channel_name: str,
    channel_type: str,
    guild_id: str | None,
    guild_name: str | None,
) -> dict:
    """Convert a DiscordChatExporter message dict to our NDJSON format."""
    author = msg.get("author", {})
    has_media, media_type, attachment_urls = extract_media(msg)

    return {
        "message_id": msg.get("id", ""),
        "channel_id": channel_id,
        "channel_name": channel_name,
        "channel_type": channel_type,
        "guild_id": guild_id,
        "guild_name": guild_name,
        "sender_id": author.get("id", ""),
        "sender_name": author.get("name", "") or author.get("nickname", "") or str(author.get("id", "")),
        "text": msg.get("content", ""),
        "timestamp": parse_timestamp(msg["timestamp"]),
        "has_media": has_media,
        "media_type": media_type,
        "attachment_urls": attachment_urls,
    }


def parse_export(
    export_path: str,
    channel_id: str,
    channel_name: str,
    channel_type: str,
    guild_id: str | None,
    guild_name: str | None,
) -> list[dict]:
    """Parse a DiscordChatExporter JSON export file into formatted messages."""
    p = Path(export_path)
    if not p.exists():
        return []

    with open(p) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print(f"Failed to parse export for channel {channel_id}", file=sys.stderr)
            return []

    raw_messages = data.get("messages", [])
    messages = []
    for msg in raw_messages:
        try:
            messages.append(format_message(
                msg, channel_id, channel_name, channel_type, guild_id, guild_name,
            ))
        except (KeyError, ValueError) as e:
            print(f"Skipping message in {channel_id}: {e}", file=sys.stderr)
            continue

    return messages


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------

def cursor_after_date(cursor: dict[str, str], channel_id: str) -> str | None:
    """Get the --after date for a channel from its cursor.

    The cursor stores message IDs.  Discord snowflake IDs encode timestamps,
    so we extract the timestamp and format as ISO date for --after.
    """
    last_id = cursor.get(channel_id)
    if not last_id:
        return None
    try:
        # Discord snowflake: (id >> 22) + 1420070400000 = unix ms
        ts_ms = (int(last_id) >> 22) + 1420070400000
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    cursor = load_cursor(args.cursor)
    exporter = get_exporter(args, cfg)
    token = cfg["token"]

    # Determine channels to export
    if args.channels:
        # User specified explicit channel IDs — still need metadata
        all_channels = list_channels(exporter, token)
        by_id = {ch.get("id", ""): ch for ch in all_channels}
        channels = [by_id[cid] for cid in args.channels if cid in by_id]
        missing = [cid for cid in args.channels if cid not in by_id]
        if missing:
            print(f"Channels not found: {', '.join(missing)}", file=sys.stderr)
    else:
        channels = list_channels(exporter, token)

    if not channels:
        print("No channels to export", file=sys.stderr)
        return

    print(f"Found {len(channels)} channels", file=sys.stderr)
    total = 0

    with tempfile.TemporaryDirectory(prefix="discord-export-") as tmpdir:
        for ch in channels:
            channel_id = str(ch.get("id", ""))
            channel_name = ch.get("name", channel_id)
            channel_type = classify_channel(ch.get("type", ""))
            guild_id = ch.get("guildId") or None
            guild_name = ch.get("guildName") or None

            # Skip categories — they don't contain messages
            if channel_type == "category":
                continue

            # Determine --after for incremental export
            after = None
            if not args.backfill:
                after = cursor_after_date(cursor, channel_id)

            output_path = str(Path(tmpdir) / f"{channel_id}.json")

            ok = export_channel(exporter, token, channel_id, output_path, after=after)
            if not ok:
                continue

            messages = parse_export(
                output_path, channel_id, channel_name,
                channel_type, guild_id, guild_name,
            )

            # Emit NDJSON, oldest first
            for msg in messages:
                print(json.dumps(msg), flush=True)
                total += 1

            # Update cursor to newest message in this channel
            if messages:
                max_id = max(messages, key=lambda m: int(m["message_id"]))["message_id"]
                old = cursor.get(channel_id, "0")
                if int(max_id) > int(old):
                    cursor[channel_id] = str(max_id)

    save_cursor(args.cursor, cursor)
    print(f"Exported {total} messages", file=sys.stderr)


def main() -> None:
    args = parse_args()
    run(args)


if __name__ == "__main__":
    main()
