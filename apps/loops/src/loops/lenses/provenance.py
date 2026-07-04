"""Provenance lens — render the ``--why`` per-field attribution drill.

One folded ``(kind, key)`` entry, answered field by field: what is each
field's current value, which fact set it, and (at ``-v``) what it superseded.
Address-scoped — this lens renders a single ``Provenance`` (from
``loops.provenance``), never the multi-section fold. The register split keys on
``piped``: a TTY read gets the rounded card + recency tags; a pipe gets a plain
header + ISO stamps (greppable ledger parity).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE, LoopsPalette
from ._grammar import block as _line
from ._grammar import (
    card,
    card_width,
    full_iso,
    recency,
    rollup_line,
    wrap_hanging,
)

if TYPE_CHECKING:
    from ..provenance import FactRef, Provenance


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _fmt_value(value: object) -> str:
    """Display form for a folded field value — empty renders as a clear mark."""
    if value == "" or value is None:
        return "∅"
    return str(value)


def _stamp(ref: "FactRef", *, piped: bool) -> str:
    return full_iso(ref.ts) if piped else recency(ref.ts)


def _last_observer(prov: "Provenance") -> str:
    if prov.facts:
        obs = prov.facts[-1].get("_observer")
        if obs:
            return str(obs)
    return prov.observers[-1] if prov.observers else "?"


def why_view(
    data: "Provenance",
    zoom: Zoom,
    width: int | None,
    *,
    piped: bool | None = None,
    palette: LoopsPalette | None = None,
) -> Block:
    """Render a Provenance ledger at the given fidelity."""
    p = palette or DEFAULT_PALETTE
    is_piped = (width is None) if piped is None else piped
    # The agent channel is information-faithful: force width=None so a pipe that
    # inherited COLUMNS never truncates the ledger (parity.py's contract).
    if is_piped:
        width = None
    address = f"{data.kind}/{data.key}"

    if data.mode == "empty":
        return _line(
            f"No source facts retained for {address} — nothing to attribute. "
            f"Check the address is exact, or use --facts to see the raw stream.",
            p.metadata, width,
        )

    if zoom == Zoom.MINIMAL:
        return _line(_rollup(data, address), Style(), width)

    if data.mode == "collect":
        return _render_collect(data, address, width, p, piped=is_piped)

    return _render_upsert(data, address, zoom, width, p, piped=is_piped)


def _rollup(data: "Provenance", address: str) -> str:
    if data.mode == "collect":
        parts = [_plural(data.total_facts, "fact"), "collect", f"last {recency(data.last_ts)}"]
    elif data.mode == "empty":
        parts = ["0 facts", "no attribution"]
    else:
        parts = [
            _plural(len(data.fields), "field"),
            _plural(data.total_facts, "fact"),
            f"last set {recency(data.last_ts)} by {_last_observer(data)}",
        ]
    return rollup_line(address, parts)


def _window(data: "Provenance") -> str:
    lo, hi = recency(data.first_ts), recency(data.last_ts)
    return lo if lo == hi else f"{lo} → {hi}"


def _header(data: "Provenance", address: str, width: int | None, p, *, piped: bool) -> Block:
    """The letterhead — plain rollup line when piped, rounded card on a TTY."""
    observers = ", ".join(data.observers) if data.observers else "?"
    if piped:
        line = " · ".join([
            address,
            _plural(data.total_facts, "fact"),
            _window(data),
            f"observers: {observers}",
        ])
        return _line(line, p.header, width)
    sublines = [
        f"{_plural(data.total_facts, 'fact')} · {_window(data)}",
        f"observers: {observers}",
    ]
    title = f"why · {address}"
    # A card needs a concrete width even when piped-narrow; fall back to the
    # sublines' natural width when there's no terminal width to fill.
    body = Block.empty(1, 1)
    card_w = card_width(body, title, sublines, width) if width else max(
        len(title) + 4, *(len(s) + 3 for s in sublines)
    )
    return card(title, sublines, card_w, p=p)


def _connector(index: int, total: int) -> str:
    """Trace gutter connector — ``┌`` opens, ``│`` continues, ``└`` closes."""
    if total <= 1:
        return "└"
    if index == 1:
        return "┌"
    if index == total:
        return "└"
    return "│"


def _trace_rows(data: "Provenance", width, p, *, piped) -> list[Block]:
    """The chronological fold trace — oldest first, one row per ``Spec.apply``.

    ``┌│└ <date> <observer> <what changed> · ×n``. ``×n`` is facts folded so
    far — the SAME thing ``×n`` means everywhere else in the spine (never a
    field count), so the trace reads as progression: ``status→proposed · ×1``,
    ``status→review · ×2``. A status transition names its landing value inline;
    other changed fields list bare. The trace CONTENT (dates, observers,
    changed fields, fold depth) is on both registers; the connector glyphs +
    terminator are TTY-legible chrome the piped channel also carries but which
    parity strips as decorative.
    """
    rows: list[Block] = []
    for a in data.applies:
        stamp = full_iso(a.ts) if piped else recency(a.ts)
        conn = _connector(a.index, a.total)
        parts = [
            f"{f}→{a.status_to}" if f == "status" and a.status_to else f
            for f in a.changed
        ]
        changed = ", ".join(parts) if parts else "(no field change)"
        obs = a.observer or "?"
        text = f"{conn} {stamp} {obs}  {changed} · ×{a.index}"
        rows.append(wrap_hanging(text, p.content, width, hang=2))
    # Pointer aims DOWN: the trace is the history; the ledger below it is the
    # current folded state — computed by the reduce, never stored as a row.
    rows.append(_line("══ the ledger below ↓ is the fold, not a stored record",
                      p.chrome, width))
    return rows


def _mechanism_rows(data: "Provenance", width, p) -> list[Block]:
    """The ``-vv`` mechanism block — render-only, no re-verification.

    States the reduction identity and the fact chain it ran over. The linkage
    line reuses the ordered fact chain already replayed (same fact sequence
    ``store verify``/``ticks --chain`` attest over) — a read, not a re-verify.
    """
    span = _window(data)
    return [
        _line("── mechanism ──", p.section, width),
        _line("state = facts.reduce(Spec.apply, ∅)", p.metadata, width),
        _line(f"chain: {data.total_facts} facts linked · {span}", p.metadata, width),
    ]


def _render_upsert(data, address, zoom, width, p, *, piped):
    rows: list[Block] = [_header(data, address, width, p, piped=piped)]
    show_history = zoom >= Zoom.DETAILED
    if show_history and data.applies:
        rows.extend(_trace_rows(data, width, p, piped=piped))
    # TODO(design-pull P1 remainder): the ledger's observer names should carry
    # palette.observer_style like confluence/stream -v do, but each ledger row
    # renders through a single-style wrap_hanging — colouring one token needs a
    # span-aware wrap. Deferred until _grammar grows one; don't fake it by
    # styling the whole row.
    for attr in data.fields:
        stamp = _stamp(attr.setter, piped=piped)
        prefix = f"{attr.field} = "
        rows.append(wrap_hanging(
            f"{prefix}{_fmt_value(attr.value)}  "
            f"← {stamp} {attr.setter.observer or '?'} "
            f"(fact {attr.setter.index}/{attr.setter.total})",
            p.content, width, hang=len(prefix),
        ))
        if show_history:
            for prior in attr.priors:
                pstamp = _stamp(prior.fact, piped=piped)
                rows.append(wrap_hanging(
                    f"    was {_fmt_value(prior.value)}  "
                    f"← {pstamp} {prior.fact.observer or '?'} "
                    f"(fact {prior.fact.index}/{prior.fact.total})",
                    p.metadata, width, hang=len("    was "),
                ))
    if zoom >= Zoom.FULL:
        rows.extend(_mechanism_rows(data, width, p))
    return join_vertical(*rows)


def _fact_body(payload: dict, key_field: str | None) -> str:
    """First non-meta, non-key field value — the fact's headline content."""
    for fk, fv in payload.items():
        if fk.startswith("_") or fk == (key_field or ""):
            continue
        if fv:
            return str(fv)
    return ""


def _render_collect(data, address, width, p, *, piped):
    label = f"{address} · collect-fold — chronology is the provenance"
    rows: list[Block] = [_line(label, p.header, width)]
    for i, fact in enumerate(data.facts, start=1):
        stamp = full_iso(fact.get("_ts")) if piped else recency(fact.get("_ts"))
        obs = str(fact.get("_observer", "") or "?")
        body = _fact_body(fact, data.key_field)
        prefix = f"  {i}/{data.total_facts}  {stamp} {obs}  "
        rows.append(wrap_hanging(
            f"{prefix}{body}", p.content, width, hang=len(prefix),
        ))
    return join_vertical(*rows)
