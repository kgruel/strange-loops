"""orient — stable session-start summary over structured store reads.

The Claude hook used to reverse-parse ``sl read --plain`` output with shell
greps. Once the plain fold/stream renderers moved to tables and date-grouped
ledgers, those greps silently matched nothing and every session opened with an
empty-store lie. This module computes the orient block from store/fold data
directly instead.

Undeclared seal observers follow the same posture as emit: the facts still
count, but the summary warns explicitly so an unattested seal never masquerades
as a cleanly declared one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import time


@dataclass(frozen=True)
class OrientMove:
    kind: str
    ts: float
    label: str
    observer: str


@dataclass(frozen=True)
class OrientWarning:
    observer: str
    count: int


@dataclass(frozen=True)
class OrientSummary:
    last_seal: str | None
    open_threads: int
    open_frictions: int
    adopted_threads: int
    moved_window_days: int
    moved: tuple[OrientMove, ...]
    undeclared_seals: tuple[OrientWarning, ...]


_MOVED_KINDS = frozenset({"thread", "decision", "friction"})
_DEEPER = (
    "deeper: sl read project --lens reconcile (staleness) · --ticks (windows) · "
    "--kind log --plain (reroutes) · --kind friction --plain (backlog)"
)


def _headline(kind: str, payload: dict) -> str:
    """One stable label for the orient move list."""
    if kind == "thread":
        name = str(payload.get("name", "?"))
        message = str(payload.get("message", "")).strip()
        return f"{name}: {message}" if message else name
    if kind == "decision":
        topic = str(payload.get("topic", "?"))
        message = str(payload.get("message", "")).strip()
        return f"{topic}: {message}" if message else topic
    if kind == "friction":
        name = str(payload.get("name", payload.get("topic", "?")))
        message = str(payload.get("message", "")).strip()
        return f"{name}: {message}" if message else name
    return str(payload.get("message", payload.get("name", payload.get("topic", "?"))))


def _format_clock(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime("%H:%M")


def _fact_epoch(ts: object) -> float:
    """Coerce a fact timestamp to epoch seconds."""
    if isinstance(ts, datetime):
        return ts.timestamp()
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts).timestamp()
        except ValueError:
            return float("-inf")
    return float("-inf")


def _status_count(vertex_path: Path, kind: str, status: str) -> int:
    from loops.commands.fetch import fetch_fold

    state = fetch_fold(vertex_path, kind=kind)
    total = 0
    for section in state.sections:
        for item in section.items:
            if str(item.payload.get("status", "")).strip().lower() == status:
                total += 1
    return total


def _seal_facts(vertex_path: Path, *, now_ts: float) -> tuple[dict, ...]:
    from engine import vertex_facts

    facts = tuple(vertex_facts(vertex_path, 0.0, now_ts, kind="seal"))
    return tuple(sorted(facts, key=lambda fact: _fact_epoch(fact.get("ts")), reverse=True))


def _last_seal(seals: tuple[dict, ...]) -> str | None:
    if not seals:
        return None
    payload = dict(seals[0].get("payload", {}) or {})
    message = str(payload.get("message", "")).strip()
    return message or "<no message>"


def _undeclared_seal_warnings(
    vertex_path: Path,
    seals: tuple[dict, ...],
) -> tuple[OrientWarning, ...]:
    from loops.commands.identity import check_emit

    by_observer: dict[str, int] = {}
    status_by_observer: dict[str, str] = {}
    for fact in seals:
        observer = str(fact.get("observer", "")).strip()
        if not observer:
            continue
        status = status_by_observer.get(observer)
        if status is None:
            status = check_emit(vertex_path, observer, "seal").status
            status_by_observer[observer] = status
        if status == "undeclared":
            by_observer[observer] = by_observer.get(observer, 0) + 1
    return tuple(
        OrientWarning(observer=observer, count=count)
        for observer, count in sorted(by_observer.items())
    )


def build_orient_summary(
    vertex_path: Path,
    *,
    now_ts: float | None = None,
    moved_window_days: int = 3,
    moved_limit: int = 5,
) -> OrientSummary:
    """Summarize session-start orientation from structured reads."""
    from engine import vertex_facts

    now_ts = time.time() if now_ts is None else now_ts
    since_ts = now_ts - (moved_window_days * 86400)
    seals = _seal_facts(vertex_path, now_ts=now_ts)

    moved_facts = [
        fact for fact in vertex_facts(vertex_path, since_ts, now_ts)
        if fact.get("kind") in _MOVED_KINDS
    ]
    moved_facts.sort(key=lambda fact: _fact_epoch(fact.get("ts")), reverse=True)
    moved = tuple(
        OrientMove(
            kind=str(fact["kind"]),
            ts=_fact_epoch(fact.get("ts")),
            label=_headline(str(fact["kind"]), dict(fact.get("payload", {}))),
            observer=str(fact.get("observer", "")),
        )
        for fact in moved_facts[:moved_limit]
    )

    return OrientSummary(
        last_seal=_last_seal(seals),
        open_threads=_status_count(vertex_path, "thread", "open"),
        open_frictions=_status_count(vertex_path, "friction", "open"),
        adopted_threads=_status_count(vertex_path, "thread", "adopted"),
        moved_window_days=moved_window_days,
        moved=moved,
        undeclared_seals=_undeclared_seal_warnings(vertex_path, seals),
    )


def render_orient(summary: OrientSummary) -> str:
    """Render the session-start orient block."""
    lines = [
        "== loops orient ==",
        f"last seal: {summary.last_seal or 'none'}",
        (
            "open: "
            f"{summary.open_threads} threads · "
            f"{summary.open_frictions} frictions · "
            f"{summary.adopted_threads} adopted-practices"
        ),
    ]
    for warning in summary.undeclared_seals:
        noun = "seal" if warning.count == 1 else "seals"
        lines.append(
            "warning: "
            f"{warning.count} {noun} by undeclared observer {warning.observer} — "
            "not attested; declare in observers{} or seal as a declared observer"
        )
    lines.append(f"moved in last {summary.moved_window_days}d:")
    if summary.moved:
        for move in summary.moved:
            lines.append(f"  {_format_clock(move.ts)} [{move.kind}] {move.label}")
    else:
        lines.append("  (empty)")
    lines.append(_DEEPER)
    return "\n".join(lines)
