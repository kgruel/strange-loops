"""Shared store helpers for strange-loops commands."""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


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


def emit_fact(path: Path, kind: str, obs: str, payload: dict) -> None:
    """Emit a fact into the task store."""
    from atoms import Fact
    from engine import SqliteStore

    fact = Fact.of(kind, obs, **payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(path=path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        store.append(fact)


def require_store(path: Path) -> None:
    """Raise if the store doesn't exist yet."""
    if not path.exists():
        raise FileNotFoundError("No session initialized. Run 'strange-loops session start' first.")


def parse_duration(s: str) -> float:
    """Parse duration string like '7d', '24h', '1h' to seconds."""
    m = re.match(r"^(\d+)([dhms])$", s)
    if not m:
        raise ValueError(f"Invalid duration: {s!r} (expected e.g. '7d', '24h', '1h')")
    value = int(m.group(1))
    unit = m.group(2)
    multipliers = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return value * multipliers[unit]
