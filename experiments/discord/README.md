# Discord Archiver

Polling-based Discord message archiver that outputs NDJSON.  Designed as a
loops Source — wraps [DiscordChatExporter](https://github.com/Tyrrrz/DiscordChatExporter)
to export messages across all channels, tracks progress with a cursor file,
and emits one JSON line per message to stdout.

## Prerequisites

### 1. Install DiscordChatExporter

DiscordChatExporter is a .NET tool.  Install via one of:

**Option A — .NET tool (recommended):**

```bash
dotnet tool install -g DiscordChatExporter.Cli
```

The binary will be available as `DiscordChatExporter.Cli` on PATH.

**Option B — Docker:**

```bash
docker pull tyrrrz/discordchatexporter
```

When using Docker, set `exporter_path` in your config to a wrapper script
that calls `docker run --rm tyrrrz/discordchatexporter`.

**Option C — Standalone binary:**

Download from the [releases page](https://github.com/Tyrrrz/DiscordChatExporter/releases)
and place somewhere on PATH, or set the path in your config file.

### 2. Get your Discord user token

> **Warning:** Using user tokens for automation may violate Discord's Terms of
> Service.  Use at your own risk.  This tool is intended for archiving your own
> messages and conversations.

To find your user token:

1. Open Discord in a web browser (not the desktop app)
2. Open Developer Tools (F12 or Ctrl+Shift+I)
3. Go to the **Network** tab
4. Send a message or perform any action in Discord
5. Find a request to `discord.com/api` in the network log
6. Look for the `Authorization` header in the request headers
7. Copy the token value (do **not** share this with anyone)

### 3. Create config file

Create `config.json` (keep this out of version control):

```json
{
  "token": "your_discord_user_token_here"
}
```

Optional fields:

```json
{
  "token": "your_discord_user_token_here",
  "exporter_path": "/path/to/DiscordChatExporter.Cli"
}
```

### 4. Install

From the monorepo root:

```bash
uv sync
```

### 5. Create data directory

```bash
mkdir -p data
```

## Usage

### Poll for new messages

```bash
uv run --package discord-archiver discord-poll \
  --config config.json \
  --cursor ./data/cursor.json
```

Fetches messages newer than what the cursor file records, writes NDJSON to
stdout, updates the cursor.

### Backfill full history

```bash
uv run --package discord-archiver discord-poll \
  --config config.json \
  --cursor ./data/cursor.json \
  --backfill
```

Exports complete message history across all accessible channels.

### Export specific channels only

```bash
uv run --package discord-archiver discord-poll \
  --config config.json \
  --cursor ./data/cursor.json \
  --channels 123456789 987654321
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | *(required)* | Path to JSON config with token |
| `--cursor` | `cursor.json` | Path to cursor file (channel_id → last message_id) |
| `--exporter-path` | `DiscordChatExporter.Cli` | Path to exporter binary (overrides config) |
| `--backfill` | off | Fetch full history instead of just new messages |
| `--channels` | all | Space-separated channel IDs to export |

## Output format

One JSON object per line:

```json
{
  "message_id": "1234567890123456789",
  "channel_id": "9876543210987654321",
  "channel_name": "general",
  "channel_type": "text",
  "guild_id": "1111111111111111111",
  "guild_name": "My Server",
  "sender_id": "2222222222222222222",
  "sender_name": "Alice",
  "text": "Hello world",
  "timestamp": 1709136000.0,
  "has_media": false,
  "media_type": null,
  "attachment_urls": []
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | string | Discord message snowflake ID |
| `channel_id` | string | Discord channel ID |
| `channel_name` | string | Channel name |
| `channel_type` | string | `dm`, `group`, `text`, `voice`, or `forum` |
| `guild_id` | string\|null | Server ID (null for DMs) |
| `guild_name` | string\|null | Server name (null for DMs) |
| `sender_id` | string | Sender's Discord user ID |
| `sender_name` | string | Sender's display name |
| `text` | string | Message text (empty string if media-only) |
| `timestamp` | float | Unix epoch timestamp |
| `has_media` | bool | Whether message contains media |
| `media_type` | string\|null | `image`, `video`, `audio`, `attachment`, `embed`, `sticker`, or null |
| `attachment_urls` | list | URLs of attached files |

## Loops integration

The `loops/` directory contains:

- `discord.loop` — Source config that runs `discord-poll` every 5 minutes
- `discord.vertex` — Vertex that folds messages by channel_id

## Files to keep out of version control

Add to `.gitignore`:

```
config.json
data/
```
