"""Claude Code source script — discover + parse session files, emit NDJSON exchanges.

Source script for the loops runtime. Discovers Claude Code JSONL session files,
parses user/assistant message pairs, and emits one NDJSON line per exchange on
stdout. The engine reads these as ndjson-format Source output.

Usage:
    python -m siftd_loops.sources.claude_code [--since TIMESTAMP] [--locations PATH ...]

Output format (one JSON object per line):
    {"conversation_id": "...", "prompt": "...", "response": "...",
     "model": "...", "workspace": "...", "usage": {...},
     "thinking": [...], "tool_calls": [...], "_ts": 1234567890.0}

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

    Text blocks are joined. Tool-use blocks are summarized as [tool:Name]
    placeholders for narrative flow. Tool-result and thinking blocks are
    skipped (their data is captured separately in tool_calls/thinking).
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
                pass  # skip — captured in tool_calls
            elif btype == "thinking":
                pass  # skip — captured in thinking array
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
    """Parse a Claude Code JSONL file into full-fidelity exchange dicts.

    Each exchange represents a user turn: starts with a real user prompt
    (user record with text content, NOT tool_result-only records) and
    includes all assistant records, tool results, system records, and
    thinking blocks until the next real user prompt or EOF.

    Returns:
        List of exchange dicts ready for NDJSON emission.
    """
    conv_id = conversation_id_from_path(path)
    exchanges: list[dict] = []

    # State for current turn
    current_prompt_text: str | None = None
    current_ts: float | None = None
    response_parts: list[str] = []
    current_model: str | None = None
    current_workspace: str | None = None
    current_git_branch: str | None = None
    current_usage: dict | None = None
    current_turn_duration_ms: int | None = None
    thinking_blocks: list[str] = []
    tool_calls: list[dict] = []
    pending_tools: dict[str, dict] = {}  # tool_use id -> {name, id, input}

    # Global workspace fallback (first cwd seen in file)
    file_workspace: str | None = None

    def _flush_turn():
        if current_prompt_text is None:
            return
        # Include any pending tools that never received results
        all_tools = tool_calls + list(pending_tools.values())
        exchanges.append(_build_exchange(
            conv_id, current_prompt_text, response_parts,
            current_model, current_workspace or file_workspace,
            current_git_branch, current_ts, current_usage,
            current_turn_duration_ms, thinking_blocks, all_tools,
        ))

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

                # Handle system records (turn_duration)
                if record_type == "system":
                    if record.get("subtype") == "turn_duration":
                        current_turn_duration_ms = record.get("durationMs")
                    continue

                if record_type not in ("user", "assistant"):
                    continue

                message = record.get("message") or {}
                role = message.get("role") or record_type
                content_blocks = _normalize_content(message.get("content"))

                if role == "user":
                    # Tool result records — match with pending tool_use
                    if _is_tool_result(content_blocks):
                        tool_use_result = record.get("toolUseResult")
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                tid = block.get("tool_use_id")
                                if tid and tid in pending_tools:
                                    entry = pending_tools.pop(tid)
                                    if tool_use_result is not None:
                                        entry["result"] = tool_use_result
                                    else:
                                        entry["result"] = block.get("content")
                                    tool_calls.append(entry)
                        continue

                    # Real user prompt — flush previous turn
                    _flush_turn()

                    # Start new turn
                    current_prompt_text = _extract_text(content_blocks)
                    current_ts = _parse_iso(record.get("timestamp"))
                    response_parts = []
                    current_model = None
                    current_workspace = record.get("cwd") or file_workspace
                    current_git_branch = record.get("gitBranch")
                    current_usage = None
                    current_turn_duration_ms = None
                    thinking_blocks = []
                    tool_calls = []
                    pending_tools = {}

                    if file_workspace is None:
                        file_workspace = record.get("cwd")

                elif role == "assistant":
                    text = _extract_text(content_blocks)
                    if text:
                        response_parts.append(text)

                    # Capture model (last wins)
                    model = message.get("model")
                    if model:
                        current_model = model

                    # Capture usage (last assistant record wins — cumulative)
                    usage = message.get("usage")
                    if usage:
                        current_usage = usage

                    # Extract thinking blocks
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "thinking":
                            thinking_text = block.get("thinking", "")
                            if thinking_text:
                                thinking_blocks.append(thinking_text)

                    # Extract tool_use blocks into pending
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tid = block.get("id")
                            if tid:
                                pending_tools[tid] = {
                                    "name": block.get("name", ""),
                                    "id": tid,
                                    "input": block.get("input", {}),
                                }

    except (OSError, UnicodeDecodeError):
        return exchanges

    # Flush last turn
    _flush_turn()

    return exchanges


def _build_exchange(
    conv_id: str,
    prompt: str,
    response_parts: list[str],
    model: str | None,
    workspace: str | None,
    git_branch: str | None,
    ts: float | None,
    usage: dict | None,
    turn_duration_ms: int | None,
    thinking: list[str],
    tool_calls: list[dict],
) -> dict:
    """Assemble a full-fidelity exchange dict from accumulated turn state."""
    result = {
        "conversation_id": conv_id,
        "prompt": prompt,
        "response": "\n".join(response_parts),
        "model": model or "",
        "workspace": workspace or "",
    }
    if git_branch:
        result["git_branch"] = git_branch
    if ts is not None:
        result["_ts"] = ts
    if usage:
        result["usage"] = usage
    if turn_duration_ms is not None:
        result["turn_duration_ms"] = turn_duration_ms
    if thinking:
        result["thinking"] = thinking
    if tool_calls:
        result["tool_calls"] = tool_calls
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
