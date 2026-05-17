"""Deliberation-depth lens — structural overfit detector.

Reads fact history for status-bearing kinds (hypothesis by default), counts
emit-depth + transition-count + session-span per fold-key chain. Surfaces
chains whose final status is closed (confirmed/rejected/resolved/completed)
with session_span == 1 — within-density confirmations that haven't been
exposed to lower-density review.

This is the structural form of paradigm/suspicious-cleanness-as-overfit-check
(Alcove convergence 2026-05-10): manual-noticing becomes read-path detection.
When a chain looks too clean (closed in one session, low depth), the lens
surfaces it as a candidate for re-examination — not a verdict, a question.

The discriminator is **session_span**, not depth alone. A chain confirmed
across two sessions has been exposed to lower-density attention; one confirmed
inside a single session window hasn't. Depth becomes secondary sort within
the SUSPICIOUS bucket.

Status stickiness under fold-merge: a re-emit without ``status=`` keeps the
prior status. We track last-explicitly-set status and count transitions only
when the value changes — so a body-only re-emit doesn't inflate transitions.

Scope: project vertex only at this writing. ``.loops/lenses/`` is vertex-local
for the project vertex specifically; cross-vertex surfacing is a separate
question (would mean co-locating with meta/identity or moving to a project-
local tier).

Surface:
    sl read project --lens deliberation                # hypothesis (default)
    sl read project --lens deliberation --kind thread  # any status-bearing kind
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_KIND = "hypothesis"

# Kinds that have a status lifecycle worth examining for deliberation depth.
# Decision is intentionally absent — status isn't load-bearing on decisions.
# Observation likewise.
_STATUS_BEARING_KINDS = frozenset({"hypothesis", "thread", "friction", "task"})

# Final/closed status values across all status-bearing kinds. Landing the
# chain in one of these is what makes the depth/span signal meaningful —
# an unclosed chain isn't "suspicious", it's just "in flight."
_CLOSED_STATUSES = frozenset({
    "confirmed", "rejected", "disconfirmed", "abandoned",   # hypothesis
    "resolved",                                               # thread, friction
    "completed",                                              # task
})

# In-flight status values — chains here are not candidates, they're just open.
_OPEN_STATUSES = frozenset({
    "proposed",      # hypothesis
    "open",          # thread, friction
    "in_progress",   # task
})


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainSignals:
    """Computed deliberation signals for one fold-key chain."""
    kind: str
    key: str
    emit_count: int               # total facts in chain
    transitions: int              # distinct sequential status values
    session_span: int             # distinct session windows touched
    final_status: str             # last explicitly-set status
    status_path: tuple[str, ...]  # ordered status values, deduped consecutively
    first_ts: float | None
    last_ts: float | None
    ts_spread: float              # last_ts - first_ts, seconds. <1s = batch.


@dataclass(frozen=True)
class DeliberationData:
    kind: str
    chains: tuple[ChainSignals, ...]


# ---------------------------------------------------------------------------
# Session window computation
# ---------------------------------------------------------------------------


_CLOSING_SESSION_STATUSES = frozenset({"closed", "resolved"})


def _compute_session_windows(
    vertex_path: Path,
    current_observer: str = "",
) -> list[tuple[float, float]]:
    """Return [(open_ts, close_ts), ...] for all session intervals.

    Per-observer pairing: ``session status=open name=X`` matched with the
    next closing-status fact for the same name. Closing statuses include
    both ``closed`` (canonical) and ``resolved`` (some historical sessions).

    Edge cases:
    - New ``open`` arrives while one is pending for the same name: the prior
      session is synthetically closed at the new open's ts. Serial sessions
      without explicit close shouldn't collapse into one giant window.
    - Still-pending open at end of scan: synthesize close=now (active session).
    - Orphan close (no pending open): ignored.
    """
    from loops.commands.fetch import fetch_fold

    state = fetch_fold(vertex_path, kind="session", retain_facts=True)

    events: list[tuple[float, str, str]] = []  # (ts, status, name)
    for sec in state.sections:
        if sec.kind != "session":
            continue
        kf = sec.key_field or "name"
        for item in sec.items:
            key = str(item.payload.get(kf, ""))
            for src in state.source_facts.get(f"{sec.kind}/{key}", []):
                ts = src.get("_ts")
                if ts is None:
                    continue
                events.append((
                    float(ts),
                    str(src.get("status", "")),
                    str(src.get("name", key)),
                ))

    events.sort(key=lambda e: e[0])

    open_pending: dict[str, float] = {}  # name → open_ts
    last_seen_ts: dict[str, float] = {}  # name → most recent ts of any event
    windows: list[tuple[float, float]] = []
    now = datetime.now(timezone.utc).timestamp()

    for ts, status, name in events:
        last_seen_ts[name] = ts
        if status == "open":
            prior = open_pending.pop(name, None)
            if prior is not None and prior < ts:
                windows.append((prior, ts))
            open_pending[name] = ts
        elif status in _CLOSING_SESSION_STATUSES:
            ots = open_pending.pop(name, None)
            if ots is not None:
                windows.append((ots, ts))

    # Still-pending opens at end of scan: cap close by observer identity.
    #   - Current observer: synthesize close=now (their active session).
    #   - Other observers: cap close at their last-seen-ts. If that equals
    #     the open's ts (orphan open with no follow-up), drop the window —
    #     synthesizing close=now would fabricate a fake mega-window that
    #     swallows everything.
    for name, ots in open_pending.items():
        if name == current_observer:
            close_ts = now
        else:
            close_ts = last_seen_ts.get(name, ots)
        if close_ts > ots:
            windows.append((ots, close_ts))

    windows.sort()
    return windows


def _session_index_for_ts(
    ts: float, windows: list[tuple[float, float]],
) -> int:
    """Return index of the session window containing ts, or -1 if outside."""
    for i, (start, end) in enumerate(windows):
        if start <= ts <= end:
            return i
    return -1


# ---------------------------------------------------------------------------
# Chain signal computation
# ---------------------------------------------------------------------------


def _compute_chain_signals(
    kind: str,
    key: str,
    facts: list[dict],
    sessions: list[tuple[float, float]],
) -> ChainSignals:
    """Given chronological facts for one chain, compute deliberation signals.

    Status stickiness: only ``status=<value>`` emits update the running status.
    A transition counts when the new value differs from the running value —
    so a body-only re-emit doesn't inflate transitions, and ``refined→refined``
    on consecutive emits counts as one state, not two.
    """
    facts_sorted = sorted(facts, key=lambda f: f.get("_ts") or 0)

    running_status = ""
    status_path: list[str] = []
    # Bucket key for each fact's session-membership:
    #   ("w", window_index)  when fact falls inside a tracked session
    #   ("d", "YYYY-MM-DD")  when fact is outside any tracked window
    # The set of distinct buckets is session_span. Day-bucketing the orphans
    # keeps pre-session-discipline chains from collapsing into one fake span.
    buckets: set[tuple[str, object]] = set()
    first_ts: float | None = None
    last_ts: float | None = None

    for f in facts_sorted:
        ts_raw = f.get("_ts")
        if ts_raw is not None:
            ts = float(ts_raw)
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            si = _session_index_for_ts(ts, sessions)
            if si >= 0:
                buckets.add(("w", si))
            else:
                day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                buckets.add(("d", day))

        status = f.get("status")
        if status:
            status = str(status)
            if status != running_status:
                status_path.append(status)
                running_status = status

    return ChainSignals(
        kind=kind,
        key=key,
        emit_count=len(facts_sorted),
        transitions=len(status_path),
        # session_span: distinct session-or-day buckets the chain touched.
        # min=1 because every non-empty chain has at least one fact-with-ts.
        session_span=max(1, len(buckets)),
        final_status=running_status,
        status_path=tuple(status_path),
        first_ts=first_ts,
        last_ts=last_ts,
        ts_spread=(last_ts - first_ts) if (first_ts is not None and last_ts is not None) else 0.0,
    )


# ---------------------------------------------------------------------------
# Fetch — lens-declared input contract
# ---------------------------------------------------------------------------


def fetch(vertex_path: Path, **kwargs) -> DeliberationData:
    """Pull chains for the target kind, compute deliberation signals.

    Accepts ``kind=`` to override the default (hypothesis). Other kwargs
    (observer, retain_facts) are ignored — this lens always wants full
    fact history for the target kind.
    """
    from loops.commands.fetch import fetch_fold

    kind = (kwargs.get("kind") or _DEFAULT_KIND).strip()
    if kind not in _STATUS_BEARING_KINDS:
        return DeliberationData(kind=kind, chains=())

    # Resolve current observer so my own active session caps at now and
    # other observers' orphan opens get capped at their last-seen ts.
    observer = kwargs.get("observer") or ""
    if not observer:
        try:
            from loops.commands.identity import resolve_observer
            observer = resolve_observer() or ""
        except Exception:
            observer = ""

    sessions = _compute_session_windows(vertex_path, current_observer=observer)
    state = fetch_fold(vertex_path, kind=kind, retain_facts=True)

    chains: list[ChainSignals] = []
    for sec in state.sections:
        if sec.kind != kind:
            continue
        kf = sec.key_field
        if not kf:
            continue
        for item in sec.items:
            key = str(item.payload.get(kf, ""))
            if not key:
                continue
            facts = state.source_facts.get(f"{sec.kind}/{key}", [])
            chains.append(_compute_chain_signals(kind, key, facts, sessions))

    return DeliberationData(kind=kind, chains=tuple(chains))


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


# Cross-chain batch detection: when N or more chains share the same
# emission timestamp (rounded to whole seconds), that's a batch-emit
# signature — a script wrote them all in one instant, not human
# deliberation. Threshold of 3 because two chains sharing a second
# could be coincidence; three is a pattern. Without this filter,
# bulk-loaded data masquerades as "confirmed without deliberation"
# — sharing the costume but not the mechanism.
_BATCH_COCHAIN_THRESHOLD = 3


def _categorize(chain: ChainSignals, batch_ts: frozenset[int]) -> str:
    """Bucket a chain: 'SUSPICIOUS' | 'HEALTHY' | 'IN_FLIGHT' | 'BATCH' | 'OTHER'.

    OTHER captures chains terminating in non-closed-non-open status — most
    notably ``refined`` as a final hypothesis state. Design choice: ``refined``
    is treated as "still evolving" rather than closure, so refined-as-final
    chains are exempt from the SUSPICIOUS check. They may still warrant
    review (a fast refinement that stalled), but the suspicious-cleanness
    semantic is specifically about closure-without-deliberation. Re-examine
    this choice if a "fast-refined-then-stalled" pattern becomes load-bearing.

    BATCH detection: a chain whose first_ts is shared with N other chains
    routes to BATCH rather than SUSPICIOUS — the cleanness is a load
    artifact, not a deliberation gap.
    """
    if chain.final_status in _OPEN_STATUSES or not chain.final_status:
        return "IN_FLIGHT"
    if chain.final_status in _CLOSED_STATUSES:
        # BATCH only when the chain ALSO didn't cross sessions. A chain that
        # emerged in a batch but later evolved across sessions is closer in
        # shape to HEALTHY — the post-batch deliberation rescued it.
        batch_first = (
            chain.first_ts is not None and int(chain.first_ts) in batch_ts
        )
        if batch_first and chain.session_span <= 1:
            return "BATCH"
        return "SUSPICIOUS" if chain.session_span <= 1 else "HEALTHY"
    return "OTHER"


def _detect_batch_timestamps(chains: tuple[ChainSignals, ...]) -> frozenset[int]:
    """Identify timestamps where N+ chains share the same emission second."""
    from collections import Counter
    counts: Counter[int] = Counter()
    for c in chains:
        if c.first_ts is not None:
            counts[int(c.first_ts)] += 1
    return frozenset(
        ts for ts, n in counts.items() if n >= _BATCH_COCHAIN_THRESHOLD
    )


def _fmt_ts(ts: float | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d")


def _zoom_at_least(zoom: Zoom, target: Zoom) -> bool:
    """Zoom comparison: is `zoom` at or above `target`?

    Zoom is ordered MINIMAL < SUMMARY < DETAILED < FULL by enum value.
    """
    return zoom.value >= target.value


def _render_chain_line(chain: ChainSignals, zoom: Zoom) -> Block:
    style = Style()
    path = "→".join(chain.status_path) if chain.status_path else "(no status)"
    head = (
        f"  {chain.key}  "
        f"e={chain.emit_count} t={chain.transitions} s={chain.session_span}  "
        f"{path}"
    )
    if _zoom_at_least(zoom, Zoom.DETAILED):
        head += f"   [{_fmt_ts(chain.first_ts)} → {_fmt_ts(chain.last_ts)}]"
    return Block.text(head, style)


def fold_view(
    data: DeliberationData,
    zoom: Zoom,
    width: int | None,
    **kwargs,
) -> Block:
    """Render deliberation-depth report.

    MINIMAL: header counts only.
    SUMMARY: + SUSPICIOUS list, ascending emit_count.
    DETAILED: + HEALTHY + IN-FLIGHT + per-chain date range.
    FULL: same as DETAILED currently; reserve for future emit-by-emit view.
    """
    style = Style()

    if not data.chains:
        return Block.text(
            f"## DELIBERATION DEPTH — {data.kind}\n  (no chains)", style,
        )

    batch_ts = _detect_batch_timestamps(data.chains)
    by_cat: dict[str, list[ChainSignals]] = defaultdict(list)
    for c in data.chains:
        by_cat[_categorize(c, batch_ts)].append(c)

    sus = sorted(
        by_cat["SUSPICIOUS"],
        key=lambda c: (c.emit_count, -(c.last_ts or 0)),
    )
    healthy = sorted(by_cat["HEALTHY"], key=lambda c: -c.emit_count)
    in_flight = sorted(by_cat["IN_FLIGHT"], key=lambda c: -(c.last_ts or 0))
    batch = sorted(by_cat["BATCH"], key=lambda c: -(c.first_ts or 0))
    other = sorted(by_cat["OTHER"], key=lambda c: -(c.last_ts or 0))

    rows: list[Block] = []
    rows.append(Block.text(
        f"## DELIBERATION DEPTH — {data.kind} "
        f"(SUS={len(sus)} HEALTHY={len(healthy)} "
        f"OPEN={len(in_flight)} BATCH={len(batch)} OTHER={len(other)})",
        style,
    ))

    if zoom == Zoom.MINIMAL:
        return join_vertical(*rows)

    # SUMMARY and above always render SUSPICIOUS — that's the point of the lens.
    rows.append(Block.text("", style))
    if sus:
        rows.append(Block.text(
            "SUSPICIOUS — closed within one session window "
            "(candidates for lower-density re-examination)",
            style,
        ))
        for c in sus:
            rows.append(_render_chain_line(c, zoom))
    else:
        rows.append(Block.text("SUSPICIOUS — (none)", style))

    if _zoom_at_least(zoom, Zoom.DETAILED):
        if healthy:
            rows.append(Block.text("", style))
            rows.append(Block.text(
                "HEALTHY — closed across multiple session windows",
                style,
            ))
            for c in healthy:
                rows.append(_render_chain_line(c, zoom))
        if in_flight:
            rows.append(Block.text("", style))
            rows.append(Block.text("IN-FLIGHT — open chains", style))
            for c in in_flight:
                rows.append(_render_chain_line(c, zoom))
        if batch:
            rows.append(Block.text("", style))
            rows.append(Block.text(
                "BATCH — shared-timestamp with peer chains (bulk-load, not deliberation)",
                style,
            ))
            for c in batch:
                rows.append(_render_chain_line(c, zoom))
        if other:
            rows.append(Block.text("", style))
            rows.append(Block.text(
                "OTHER — terminal status outside closed/open sets",
                style,
            ))
            for c in other:
                rows.append(_render_chain_line(c, zoom))

    return join_vertical(*rows)
