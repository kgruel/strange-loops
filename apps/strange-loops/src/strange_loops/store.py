"""Shared store helpers for strange-loops commands."""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def render_log_entry(fact: dict) -> None:
    """Render a single fact as a styled line via painted."""
    from painted import show
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
    show(Block.text(text, p.muted), file=sys.stdout)


def render_log(facts: list[dict]) -> None:
    """Render facts as a date-grouped chronological log."""
    from painted import show
    from painted.block import Block
    from painted.palette import current_palette

    if not facts:
        p = current_palette()
        show(Block.text("No facts in the given time range.", p.muted), file=sys.stdout)
        return

    current_date = None
    for f in facts:
        ts = f["ts"]
        dt = ts if isinstance(ts, datetime) else datetime.fromtimestamp(ts, tz=timezone.utc)
        date_str = format_date(dt)
        if date_str != current_date:
            if current_date is not None:
                print()
            p = current_palette()
            show(Block.text(f"{date_str}:", p.accent), file=sys.stdout)
            current_date = date_str

        render_log_entry(f)
