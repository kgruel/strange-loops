"""Shared store helpers for strange-loops commands."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted.block import Block

_PKG_ROOT = Path(__file__).resolve().parent.parent.parent


def observer(args: argparse.Namespace | None = None) -> str:
    """Resolve observer: --observer flag → STRANGE_LOOPS_OBSERVER → LOOPS_OBSERVER → ""."""
    if args is not None:
        flag = getattr(args, "observer", None)
        if flag:
            return flag
    return os.environ.get("STRANGE_LOOPS_OBSERVER", os.environ.get("LOOPS_OBSERVER", ""))


def store_path() -> Path:
    """Task store path — constant until .vertex files arrive."""
    return Path.cwd() / "data" / "tasks.db"


def store_path_for(vertex_name: str) -> Path:
    """Resolve store path from loops/{name}.vertex declaration."""
    from lang import parse_vertex_file

    vertex_path = _PKG_ROOT / "loops" / f"{vertex_name}.vertex"
    vertex = parse_vertex_file(vertex_path)
    store = Path(vertex.store) if vertex.store else Path(f"data/{vertex_name}.db")
    if not store.is_absolute():
        store = _PKG_ROOT / store
    return store


def emit_fact(path: Path, kind: str, obs: str, payload: dict) -> None:
    """Emit a fact into a store."""
    from atoms import Fact
    from engine import SqliteStore

    fact = Fact.of(kind, obs, **payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(path=path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        store.append(fact)


def emit_tick(path: Path, name: str, payload: dict, origin: str = "") -> None:
    """Emit a tick into a store."""
    from engine import SqliteStore, Tick

    tick = Tick(
        name=name,
        ts=datetime.now(timezone.utc),
        payload=payload,
        origin=origin,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(path=path, serialize=lambda x: x, deserialize=lambda x: x) as store:
        store.append_tick(tick)


def require_store(path: Path, message: str | None = None) -> None:
    """Raise if the store doesn't exist yet."""
    if not path.exists():
        msg = message or "No session initialized. Run 'strange-loops session start' first."
        raise FileNotFoundError(msg)


def parse_duration(s: str) -> float:
    """Parse duration string like '7d', '24h', '1h' to seconds."""
    m = re.match(r"^(\d+)([dhms])$", s)
    if not m:
        raise ValueError(f"Invalid duration: {s!r} (expected e.g. '7d', '24h', '1h')")
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers[unit]


# -- Shared rendering helpers (used by session.py and project.py) --


def format_ts(dt: datetime) -> str:
    """Format datetime as 'HH:MM' for log display."""
    return dt.strftime("%H:%M")


def format_date(dt: datetime) -> str:
    """Format datetime as 'YYYY-MM-DD' for log grouping."""
    return dt.strftime("%Y-%m-%d")


def fact_line(fact: dict) -> "Block":
    """Render a single fact as a styled Block."""
    from painted.block import Block
    from painted.palette import current_palette

    p = current_palette()
    ts = fact["ts"]
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    time_str = format_ts(dt)
    kind = fact["kind"]
    obs = fact.get("observer", "")
    payload = fact["payload"]

    parts = [f"{k}={v}" for k, v in payload.items() if v is not None and v != ""]
    summary = " ".join(parts)

    who = f" ({obs})" if obs else ""
    text = f"  {time_str} [{kind}]{who} {summary}" if summary else f"  {time_str} [{kind}]{who}"
    return Block.text(text, p.muted)


def filter_task_facts(facts: list[dict], name: str) -> list[dict]:
    """Filter facts belonging to a specific task.

    Matches payload["name"] == name (task.* facts) or
    payload["task"] == name (worker.* facts).
    """
    result = []
    for f in facts:
        payload = f.get("payload", {})
        if payload.get("name") == name or payload.get("task") == name:
            result.append(f)
    return result


def _tick_status_style(status: str):
    """Map tick status to a palette style."""
    from painted.palette import current_palette

    p = current_palette()
    if status == "completed":
        return p.success
    if status == "errored":
        return p.error
    if status == "exhausted":
        return p.warning
    return p.accent


def tick_to_dict(tick) -> dict:
    """Convert a Tick object to a serializable dict."""
    return {
        "type": "tick",
        "name": tick.name,
        "ts": tick.ts,
        "payload": tick.payload if isinstance(tick.payload, dict) else {},
        "origin": tick.origin,
    }


def tick_line(tick: dict) -> "Block":
    """Render a single tick dict as a styled Block.

    Default: `  HH:MM ⚡ task-name status` with status colored by outcome.
    The ⚡ and status color distinguish ticks from regular fact lines.
    Accepts a tick dict (from tick_to_dict or fetch functions).
    """
    from painted.block import Block
    from painted.compose import join_horizontal
    from painted.palette import current_palette

    p = current_palette()
    ts = tick["ts"]
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    time_str = format_ts(dt)
    payload = tick.get("payload", {}) if isinstance(tick.get("payload"), dict) else {}
    status = payload.get("status", "")
    task_name = payload.get("task", "")

    prefix = Block.text(f"  {time_str} ⚡ ", p.muted)

    if task_name and status:
        name_block = Block.text(f"{task_name} ", p.muted)
        status_block = Block.text(status, _tick_status_style(status))
        return join_horizontal(prefix, name_block, status_block)
    elif status:
        status_block = Block.text(status, _tick_status_style(status))
        return join_horizontal(prefix, status_block)
    else:
        # Fallback for ticks without task/status payload
        parts = [f"{k}={v}" for k, v in payload.items() if v is not None and v != ""]
        summary = " ".join(parts) if parts else tick.get("name", "")
        return join_horizontal(prefix, Block.text(summary, p.accent))


def filter_task_ticks(ticks: list[dict], name: str) -> list[dict]:
    """Filter tick dicts belonging to a specific task.

    Matches payload["task"] == name.
    """
    result = []
    for t in ticks:
        payload = t.get("payload", {}) if isinstance(t.get("payload"), dict) else {}
        if payload.get("task") == name:
            result.append(t)
    return result


def log_block(facts: list[dict], ticks: list[dict] | None = None) -> "Block":
    """Render facts and ticks interleaved chronologically with date grouping.

    Returns a Block. Pass ticks=None or [] for fact-only logs.
    """
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    ticks = ticks or []

    if not facts and not ticks:
        p = current_palette()
        return Block.text("No facts in the given time range.", p.muted)

    # Build unified timeline: (ts, type, item)
    entries: list[tuple[float, str, dict]] = []
    for f in facts:
        ts = f["ts"]
        ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
        entries.append((ts_val, "fact", f))
    for t in ticks:
        ts = t["ts"]
        ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
        entries.append((ts_val, "tick", t))

    entries.sort(key=lambda e: e[0])

    blocks: list[Block] = []
    current_date = None
    for ts_val, entry_type, item in entries:
        dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
        date_str = format_date(dt)
        if date_str != current_date:
            if current_date is not None:
                blocks.append(Block.text("", p.muted))
            p = current_palette()
            blocks.append(Block.text(f"{date_str}:", p.accent))
            current_date = date_str

        if entry_type == "fact":
            blocks.append(fact_line(item))
        else:
            blocks.append(tick_line(item))

    return join_vertical(*blocks)


def format_ts_iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 for FULL zoom display."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_secondary(key: str, value) -> bool:
    """Whether a payload field should be shown on continuation lines at DETAILED+.

    Secondary: description, worktree, output, message, base_branch, or any value >40 chars.
    """
    if key in ("description", "worktree", "output", "message", "base_branch"):
        return True
    return isinstance(value, str) and len(value) > 40


def fact_line_zoom(fact: dict, zoom) -> "list[Block]":
    """Render a fact as one or more Blocks depending on zoom level.

    SUMMARY: delegates to fact_line() — single line.
    DETAILED: primary line + secondary fields on indented continuation lines.
    FULL: ISO timestamp, each payload field on its own indented line.
    """
    from painted import Zoom
    from painted.block import Block
    from painted.palette import current_palette

    if zoom <= Zoom.SUMMARY:
        return [fact_line(fact)]

    p = current_palette()
    ts = fact["ts"]
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    kind = fact["kind"]
    obs = fact.get("observer", "")
    payload = fact["payload"]
    who = f" ({obs})" if obs else ""

    if zoom == Zoom.FULL:
        # ISO timestamp, kind + observer on primary line, each field on own line
        time_str = format_ts_iso(dt)
        lines: list[Block] = [Block.text(f"  {time_str} [{kind}]{who}", p.muted)]
        for k, v in payload.items():
            if v is not None and v != "":
                lines.append(Block.text(f"      {k}={v}", p.muted))
        origin = fact.get("origin", "")
        if origin:
            lines.append(Block.text(f"      origin={origin}", p.muted))
        return lines

    # DETAILED: primary fields inline, secondary on continuation lines
    primary_parts = []
    secondary: list[tuple[str, str]] = []
    for k, v in payload.items():
        if v is None or v == "":
            continue
        if _is_secondary(k, v):
            secondary.append((k, str(v)))
        else:
            primary_parts.append(f"{k}={v}")

    time_str = format_ts(dt)
    summary = " ".join(primary_parts)
    text = f"  {time_str} [{kind}]{who} {summary}" if summary else f"  {time_str} [{kind}]{who}"
    lines = [Block.text(text, p.muted)]
    for k, v in secondary:
        lines.append(Block.text(f"      {k}={v}", p.muted))
    return lines


def tick_line_zoom(tick: dict, zoom) -> "list[Block]":
    """Render a tick as one or more Blocks depending on zoom level.

    SUMMARY: delegates to tick_line() — single line.
    DETAILED: + origin if present.
    FULL: ISO timestamp, all payload fields individually.
    """
    from painted import Zoom
    from painted.block import Block
    from painted.palette import current_palette

    if zoom <= Zoom.SUMMARY:
        return [tick_line(tick)]

    p = current_palette()
    ts = tick["ts"]
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    payload = tick.get("payload", {}) if isinstance(tick.get("payload"), dict) else {}
    origin = tick.get("origin", "")

    if zoom == Zoom.FULL:
        time_str = format_ts_iso(dt)
        name = tick.get("name", "")
        lines: list[Block] = [Block.text(f"  {time_str} ⚡ {name}", p.accent)]
        for k, v in payload.items():
            if v is not None and v != "":
                lines.append(Block.text(f"      {k}={v}", p.muted))
        if origin:
            lines.append(Block.text(f"      origin={origin}", p.muted))
        return lines

    # DETAILED: normal tick line + origin continuation
    lines = [tick_line(tick)]
    if origin:
        lines.append(Block.text(f"      origin={origin}", p.muted))
    return lines


def log_block_zoom(facts: list[dict], ticks: list[dict] | None, zoom) -> "Block":
    """Render facts and ticks with zoom-aware detail.

    MINIMAL: kind counts one-liner.
    SUMMARY/DETAILED/FULL: date-grouped timeline using fact_line_zoom/tick_line_zoom.
    """
    from painted import Zoom
    from painted.block import Block
    from painted.compose import join_vertical
    from painted.palette import current_palette

    ticks = ticks or []
    p = current_palette()

    if not facts and not ticks:
        return Block.text("No facts in the given time range.", p.muted)

    if zoom == Zoom.MINIMAL:
        # Count facts by kind, one-liner
        counts: dict[str, int] = {}
        for f in facts:
            kind = f["kind"]
            counts[kind] = counts.get(kind, 0) + 1
        for t in ticks:
            counts["tick"] = counts.get("tick", 0) + 1
        parts = [f"{n} {k}" for k, n in sorted(counts.items())]
        return Block.text(", ".join(parts), p.muted)

    # SUMMARY/DETAILED/FULL — date-grouped timeline
    entries: list[tuple[float, str, dict]] = []
    for f in facts:
        ts = f["ts"]
        ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
        entries.append((ts_val, "fact", f))
    for t in ticks:
        ts = t["ts"]
        ts_val = ts.timestamp() if isinstance(ts, datetime) else ts
        entries.append((ts_val, "tick", t))

    entries.sort(key=lambda e: e[0])

    blocks: list[Block] = []
    current_date = None
    for ts_val, entry_type, item in entries:
        dt = datetime.fromtimestamp(ts_val, tz=timezone.utc)
        date_str = format_date(dt)
        if date_str != current_date:
            if current_date is not None:
                blocks.append(Block.text("", p.muted))
            blocks.append(Block.text(f"{date_str}:", p.accent))
            current_date = date_str

        if entry_type == "fact":
            blocks.extend(fact_line_zoom(item, zoom))
        else:
            blocks.extend(tick_line_zoom(item, zoom))

    return join_vertical(*blocks)


def print_fact_line(fact: dict) -> None:
    """Print a fact line to stdout — for streaming/follow modes."""
    from painted import show

    show(fact_line(fact), file=sys.stdout)


def print_tick_line(tick: dict) -> None:
    """Print a tick line to stdout — for streaming/follow modes."""
    from painted import show

    show(tick_line(tick), file=sys.stdout)
