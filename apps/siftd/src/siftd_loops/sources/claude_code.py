"""Claude Code source script — discover + parse session files, emit NDJSON exchanges.

Source script for the loops runtime. Discovers Claude Code JSONL session files,
parses user/assistant message pairs, and emits one NDJSON line per exchange on
stdout. The engine reads these as ndjson-format Source output.

Usage:
    python -m siftd_loops.sources.claude_code [--since TIMESTAMP] [--locations PATH ...]

Output format (one JSON object per line):
    {"conversation_id": "...", "prompt": "...", "response": "...",
     "model": "...", "workspace": "...", "_ts": 1234567890.0}

The Source declaration provides kind="exchange" and observer="siftd" —
this script only emits payload fields.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOCATIONS = ["~/.claude/projects", "~/.config/claude/projects"]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover(
    locations: list[str] | None = None, since: float | None = None
) -> list[Path]:
    """Find Claude Code JSONL session files.

    Args:
        locations: Directories to scan. Defaults to DEFAULT_LOCATIONS.
        since: Only include files modified after this unix timestamp.

    Returns:
        Sorted list of JSONL file paths (oldest first for stable emission order).
    """
    paths: list[Path] = []
    for loc in locations or DEFAULT_LOCATIONS:
        base = Path(loc).expanduser()
        if not base.exists():
            continue
        for jsonl_file in base.glob("**/*.jsonl"):
            if since is not None and jsonl_file.stat().st_mtime < since:
                continue
            paths.append(jsonl_file)
    paths.sort(key=lambda p: p.stat().st_mtime)
    return paths


# ---------------------------------------------------------------------------
# Conversation ID
# ---------------------------------------------------------------------------


def conversation_id_from_path(path: Path) -> str:
    """Derive a stable conversation_id from a session file path.

    Uses the sessionId from the first user record if available,
    otherwise falls back to the filename stem.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if record.get("type") == "user":
                    sid = record.get("sessionId")
                    if sid:
                        return sid
    except (OSError, UnicodeDecodeError):
        pass
    return path.stem


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _normalize_content(content: object) -> list:
    """Normalize message content to a list of blocks."""
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _extract_text(blocks: list) -> str:
    """Extract flattened text from content blocks.

    Text blocks are joined. Tool-use/tool-result blocks are summarized
    as short placeholders so the prompt/response remains readable.
    """
    parts: list[str] = []
    for block in blocks:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            btype = block.get("type", "")
            if btype == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
            elif btype == "tool_use":
                name = block.get("name", "tool")
                parts.append(f"[tool:{name}]")
            elif btype == "tool_result":
                pass  # skip — tool results are noise in flattened text
            elif btype == "thinking":
                pass  # skip extended thinking blocks
    return "\n".join(parts)


def _is_tool_result(blocks: list) -> bool:
    """Return True if content blocks are exclusively tool_result entries."""
    return bool(blocks) and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks
    )


def _parse_iso(ts: str | None) -> float | None:
    """Parse an ISO timestamp string to unix float. Returns None on failure."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def parse_exchanges(path: Path) -> list[dict]:
    """Parse a Claude Code JSONL file into exchange dicts.

    Each exchange is a user prompt paired with the assistant response(s)
    that follow it. Tool-result messages (user records containing only
    tool_result blocks) are skipped — they are not real user prompts.

    Returns:
        List of exchange dicts ready for NDJSON emission.
    """
    conv_id = conversation_id_from_path(path)
    exchanges: list[dict] = []

    # State for current exchange
    current_prompt_text: str | None = None
    current_ts: float | None = None
    response_parts: list[str] = []
    current_model: str | None = None
    current_workspace: str | None = None

    # Global workspace fallback (first cwd seen in file)
    file_workspace: str | None = None

    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                record_type = record.get("type")
                if record_type not in ("user", "assistant"):
                    continue

                message = record.get("message") or {}
                role = message.get("role") or record_type
                content_blocks = _normalize_content(message.get("content"))

                if role == "user":
                    # Skip tool_result messages
                    if _is_tool_result(content_blocks):
                        continue

                    # Flush previous exchange if we have one
                    if current_prompt_text is not None:
                        exchanges.append(_build_exchange(
                            conv_id, current_prompt_text, response_parts,
                            current_model, current_workspace or file_workspace,
                            current_ts,
                        ))

                    # Start new exchange
                    current_prompt_text = _extract_text(content_blocks)
                    current_ts = _parse_iso(record.get("timestamp"))
                    response_parts = []
                    current_model = None
                    current_workspace = record.get("cwd") or file_workspace

                    if file_workspace is None:
                        file_workspace = record.get("cwd")

                elif role == "assistant":
                    text = _extract_text(content_blocks)
                    if text:
                        response_parts.append(text)
                    # Capture model from assistant message
                    model = message.get("model")
                    if model:
                        current_model = model

    except (OSError, UnicodeDecodeError):
        return exchanges

    # Flush last exchange
    if current_prompt_text is not None:
        exchanges.append(_build_exchange(
            conv_id, current_prompt_text, response_parts,
            current_model, current_workspace or file_workspace,
            current_ts,
        ))

    return exchanges


def _build_exchange(
    conv_id: str,
    prompt: str,
    response_parts: list[str],
    model: str | None,
    workspace: str | None,
    ts: float | None,
) -> dict:
    """Assemble an exchange dict from accumulated state."""
    result = {
        "conversation_id": conv_id,
        "prompt": prompt,
        "response": "\n".join(response_parts),
        "model": model or "",
        "workspace": workspace or "",
    }
    if ts is not None:
        result["_ts"] = ts
    return result



# ---------------------------------------------------------------------------
# Manifest (cursor state for idempotent re-sync)
# ---------------------------------------------------------------------------


def load_manifest(manifest_path: Path | None) -> dict:
    """Load the file manifest from disk. Returns empty dict if missing."""
    if manifest_path is None:
        return {}
    try:
        return json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_manifest(manifest: dict, manifest_path: Path | None) -> None:
    """Atomically save the file manifest to disk."""
    if manifest_path is None:
        return
    tmp = manifest_path.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(manifest, indent=2))
    tmp.rename(manifest_path)


def file_changed(path: Path, manifest: dict) -> bool:
    """Return True if a file needs (re-)processing based on size."""
    entry = manifest.get(str(path))
    if entry is None:
        return True
    return path.stat().st_size != entry.get("size")


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def emit(paths: list[Path], out=None, manifest_path: Path | None = None) -> int:
    """Parse all session files and emit NDJSON exchanges.

    When manifest_path is provided, skips files that haven't changed
    since last processing (based on file size). Updates the manifest
    after processing.

    Returns the number of exchanges emitted.
    """
    if out is None:
        out = sys.stdout
    manifest = load_manifest(manifest_path)
    count = 0
    for path in paths:
        if not file_changed(path, manifest):
            continue
        exchanges = parse_exchanges(path)
        for exchange in exchanges:
            json.dump(exchange, out, ensure_ascii=False)
            out.write("\n")
            count += 1
        manifest[str(path)] = {
            "size": path.stat().st_size,
            "exchanges": len(exchanges),
        }
    save_manifest(manifest, manifest_path)
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Claude Code source — emit exchanges as NDJSON"
    )
    parser.add_argument(
        "--since",
        type=float,
        default=None,
        help="Only process files modified after this unix timestamp",
    )
    parser.add_argument(
        "--locations",
        nargs="+",
        default=None,
        help="Override default discovery locations",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Data directory for manifest (cursor state)",
    )
    args = parser.parse_args(argv)

    manifest_path = None
    if args.data_dir:
        manifest_path = Path(args.data_dir) / ".manifest"

    paths = discover(locations=args.locations, since=args.since)
    emit(paths, manifest_path=manifest_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
