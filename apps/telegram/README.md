# Telegram Archiver

Polling-based Telegram message archiver that outputs NDJSON.  Designed as a
loops Source — fetches messages across all chats, tracks progress with a cursor
file, and emits one JSON line per message to stdout.

## Setup

### 1. Get API credentials

Go to [my.telegram.org](https://my.telegram.org):

1. Log in with your phone number
2. Go to "API development tools"
3. Create an application — note the **api_id** and **api_hash**

### 2. Create config file

Create `config.json` (keep this out of version control):

```json
{
  "api_id": 12345678,
  "api_hash": "your_api_hash_here",
  "phone": "+1234567890"
}
```

### 3. Install

From the monorepo root:

```bash
uv sync
```

### 4. First run (authentication)

The first run will prompt you for a verification code sent to your Telegram:

```bash
uv run --package telegram-archiver telegram-poll --config config.json --session ./data/telegram
```

This creates a session file (`data/telegram.session`) that persists your login.
Subsequent runs won't need the code.

### 5. Create data directory

```bash
mkdir -p data
```

## Usage

### Poll for new messages

```bash
uv run --package telegram-archiver telegram-poll \
  --config config.json \
  --cursor ./data/cursor.json \
  --session ./data/telegram
```

Fetches messages newer than what the cursor file records, writes NDJSON to
stdout, updates the cursor.

### Backfill full history

```bash
uv run --package telegram-archiver telegram-poll \
  --config config.json \
  --cursor ./data/cursor.json \
  --session ./data/telegram \
  --backfill
```

Pages through complete message history across all chats.  Rate-limited with
1-second delays between batches and automatic FloodWait handling.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--config` | *(required)* | Path to JSON config with api_id, api_hash, phone |
| `--cursor` | `cursor.json` | Path to cursor file (chat_id → last message_id) |
| `--session` | `telegram` | Telethon session name/path |
| `--backfill` | off | Fetch full history instead of just new messages |
| `--limit` | 100 | Messages per batch |

## Output format

One JSON object per line:

```json
{
  "message_id": 12345,
  "chat_id": -100123456789,
  "chat_title": "My Group",
  "chat_type": "supergroup",
  "sender_id": 987654321,
  "sender_name": "Alice",
  "text": "Hello world",
  "timestamp": 1709136000.0,
  "has_media": false,
  "media_type": null
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | int | Telegram message ID (unique within chat) |
| `chat_id` | int | Telegram chat/channel ID |
| `chat_title` | string | Chat name |
| `chat_type` | string | `private`, `group`, `supergroup`, or `channel` |
| `sender_id` | int | Sender's Telegram user ID |
| `sender_name` | string | Sender's first name or title |
| `text` | string | Message text (empty string if media-only) |
| `timestamp` | float | Unix epoch timestamp |
| `has_media` | bool | Whether message contains media |
| `media_type` | string\|null | `photo`, `video`, `audio`, `document`, `sticker`, `webpage`, or null |

## Loops integration

The `loops/` directory contains:

- `telegram.loop` — Source config that runs `telegram-poll` every 5 minutes
- `telegram.vertex` — Vertex that folds messages by chat_id

## Files to keep out of version control

Add to `.gitignore`:

```
config.json
data/
*.session
```
