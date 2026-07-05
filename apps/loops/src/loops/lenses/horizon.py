"""Horizon — each armed loop's open window against its declared boundary.

Fold cuts by kind, stream/ticks by time, confluence by observer, graph by
connection; Horizon cuts by CYCLE PROXIMITY — how close each boundaried loop
sits to its next seal. One row per loop that DECLARES a boundary (a vertex-level
boundary is one row over the whole vertex); loops with no boundary of their own
never seal on a cycle — they no longer vanish but roll up into a trailing
``◦ N unarmed · M facts accumulating`` segment (default/-q), expanding to
per-loop ◦ rows at -v (decision:design/horizon-unarmed-rollup, amending
decision:design/horizon-build1-scope). Zero unarmed loops → the segment is
absent entirely (no ``◦ 0 unarmed`` noise).

Two boundary shapes render two honestly-different rows:

* **count-based** (``after``/``every``) — numeric proximity ``n/N`` with a
  TTY-only meter (``n`` unsealed facts against the declared ``count``).
* **kind-based** (``when``) — ``waiting on <kind> · N facts in window · last
  sealed <recency>``. NO fake progress meter: a kind boundary has no numerator
  (hlab is 100% kind-based), so inventing a bar would smuggle a signal.

The rows carry NO rail tier glyph: a loop is a declaration, not a folded
entity, so it has no salience tier — the gutter stays blank rather than fake
one (the same honest-absence stance the rail legend documents). The one thing
the TTY gutter DOES carry is a status overlay: ``▲`` when a count loop crosses
the palette's critical threshold (▲ ≡ critical — the glyph fires exactly where
the meter ramp turns red, decision:design/horizon-proximity-sort as amended).
The piped register carries the same signal as the WORD ``approaching`` (the
G4 stance: pipes carry words, not glyphs). Rows themselves sort by proximity (count-based
by ratio, kind-based by window facts, never-sealed last — the sort lives in
``fetch_horizon`` so ``--json`` carries the order too). Deferred per the 060
view sequence: ``-v`` ETA extrapolation (needs inter-tick interval stats) and
the ⊘ staleness overlay (Horizon reads recency strings only).

Wired as a composition lens: ``sl read <vertex> --lens horizon``. The
module-level ``fetch`` overrides the default fold fetch; ``fold_view``
re-export routes ``--lens horizon`` here.
"""

from __future__ import annotations

from painted import Block, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE, LoopsPalette
from ._grammar import (
    card,
    card_width,
    recency,
    rollup_line,
    stamp,
    wrap_hanging,
)
from ._grammar import block as _line

# Gutter glyph for an unarmed loop (no boundary of its own — accumulates, never
# seals on a cycle). TTY-only chrome; the pipe carries the bare words
# (decision:rendering/flags-words-edges-arrows — a status glyph degrades to its
# word on the pipe).
_UNARMED = "◦"

_BAR_FULL = "▓"
_BAR_EMPTY = "░"

# Status overlay for a count loop about to seal. ▲ ≡ critical: the palette
# owns the one threshold (the same ratio where the meter ramp turns red), so
# glyph and ramp always tell one story. The TTY gutter carries the glyph; the
# piped register carries the word (G4: pipes carry words, not glyphs); the
# blank-gutter stance of decision:design/horizon-build1-scope stays intact.
_APPROACHING = "▲"
_APPROACHING_WORD = "approaching"


def _approaching(row: dict, p: LoopsPalette) -> bool:
    """Has this count-based loop crossed the palette's critical threshold?

    Mirrors the meter's ratio exactly (window_facts/count). Kind-based
    boundaries have no numerator, so they never approach — the gutter stays
    blank for them, honestly. Never-sealed loops also never approach: they sit
    in the lowest proximity stratum in ``_horizon_sort_key`` (no meaningful
    proximity yet), so firing the ▲ here would contradict the sort order —
    a glyph on the row the sort buries last (decision:design/horizon-proximity-sort).
    """
    if row["mode"] == "when" or row["never_sealed"]:
        return False
    count = row.get("count") or 0
    return count > 0 and p.horizon_approaching(row["window_facts"] / count)


def fetch(vertex_path, kind=None, observer=None):
    """Lens-declared fetch — the open-window-against-boundary projection."""
    from loops.commands.fetch import fetch_horizon

    return fetch_horizon(vertex_path, kind=kind, observer=observer)


def _meter(n: int, total: int, width: int = 8) -> str:
    """A clamped proximity bar — ``n`` of ``total``, never overflowing ``width``.

    Count-based only. ``n`` can exceed ``total`` (the boundary fires on the Nth
    fact but a read between fires can catch more) — the bar saturates full
    rather than lying about being past 100%.
    """
    if total <= 0:
        return ""
    filled = min(width, round(width * n / total))
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def _seal_phrase(row: dict) -> str:
    """``last sealed 2h`` / ``never sealed`` — the honest recency of the seal."""
    if row["never_sealed"]:
        return "never sealed"
    return f"last sealed {recency(row['last_sealed'])}"


def _shape_word(row: dict) -> str:
    """The boundary shape as a bare word — ``when`` / ``after`` / ``every``."""
    return row["mode"]


def _conditions_text(row: dict) -> str:
    """Boundary match + fold-state conditions as one clause, or ``''``.

    ``status=closed`` (payload match) · ``high >= 80`` (fold-state condition).
    Kind-based boundaries only; count-based carry none.
    """
    parts = [f"{k}={v}" for k, v in row.get("match", [])]
    parts += [f"{t} {op} {v}" for t, op, v in row.get("conditions", [])]
    return " · ".join(parts)


def _mix_text(row: dict, *, joiner: str = " · ", sep: str = " ") -> str:
    """Window kind mix — ``decision 2 · thread 1`` — or ``''`` when empty."""
    return joiner.join(f"{k}{sep}{n}" for k, n in row.get("window_kinds", {}).items())


def _unarmed_segment(unarmed: list[dict], unarmed_facts: int, *, piped: bool) -> str:
    """The one-line unarmed rollup — ``◦ N unarmed · M facts accumulating``.

    TTY carries the ``◦`` glyph; the pipe carries the bare words (G4). Caller
    guards ``unarmed`` non-empty (zero unarmed loops → the segment is absent
    entirely, no ``◦ 0 unarmed`` noise, decision:design/horizon-unarmed-rollup).
    """
    glyph = "" if piped else f"{_UNARMED} "
    facts_word = "fact" if unarmed_facts == 1 else "facts"
    return (
        f"{glyph}{len(unarmed)} unarmed · "
        f"{unarmed_facts} {facts_word} accumulating"
    )


def _unarmed_row_text(row: dict, name_w: int, *, piped: bool) -> str:
    """One per-loop unarmed row (-v) — name, kind mix, accumulating count.

    The kind mix (``decision 4``) IS the loop's window scoped to its own kind;
    a zero-fact loop carries no mix (honest absence). TTY prefixes the ``◦``
    glyph; the pipe drops it.
    """
    mix = _mix_text(row, joiner=" ", sep=" ")
    acc = f"{row['window_facts']} accumulating"
    if piped:
        segs = [f"{row['name']:<{name_w}}"]
        if mix:
            segs.append(mix)
        segs.append(acc)
        return "  ".join(segs).rstrip()
    body = f"{_UNARMED} {row['name']:<{name_w}}"
    if mix:
        body += f"  {mix}"
    return f"  {body}  {acc}"


def _descriptor(row: dict, zoom: Zoom) -> str:
    """The TTY row body after the name column (meter appended separately)."""
    if row["mode"] == "when":
        wf = row["window_facts"]
        out = f"waiting on {row['trigger_kind']}"
        out += f" · {wf} fact{'s' if wf != 1 else ''} in window · {_seal_phrase(row)}"
    else:
        out = f"{row['mode']} {row['count']} · {row['window_facts']}/{row['count']}"
        out += f" · {_seal_phrase(row)}"
    if zoom >= Zoom.DETAILED:
        cond = _conditions_text(row)
        if cond:
            out += f"   [{cond}]"
        mix = _mix_text(row)
        if mix and row["window_facts"]:
            out += f"   ({mix})"
    if zoom >= Zoom.FULL and not row["never_sealed"]:
        out += f"   sealed {stamp(row['last_sealed'])}"
    return out


def horizon_view(
    data: dict,
    zoom: Zoom,
    width: int | None,
    palette: LoopsPalette | None = None,
    *,
    piped: bool | None = None,
) -> Block:
    """Render the open-window-against-boundary projection on both registers.

    ``piped=True`` forces width=None — the agent channel never clips; every
    count, boundary shape, condition, and absolute seal stamp is carried whole.
    """
    if piped:
        width = None

    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    loops = data.get("loops", [])
    armed = data.get("armed", 0)
    total_unsealed = data.get("total_unsealed", 0)
    last_sealed = data.get("last_sealed")
    unarmed = data.get("unarmed", [])
    unarmed_facts = data.get("unarmed_facts", 0)

    if not loops and not unarmed:
        # Honest absence: a vertex with neither armed nor unarmed loops. One
        # true line, never an empty fake table.
        return _line("No armed loops — nothing seals.", p.metadata, width)

    seal_tag = recency(last_sealed) if last_sealed is not None else "never"

    # -q: the shared rollup, plus the unarmed segment appended as a trailing,
    # non-sheddable part. Its counts have no degraded form on the line, so —
    # like graph's hub segment — the whole line WRAPS rather than sheds
    # (decision:design/rollup-shed-only-what-degrades). ◦ is TTY-only; the pipe
    # carries the bare words.
    rollup_parts = [
        f"{armed} armed loop{'s' if armed != 1 else ''}",
        f"{total_unsealed} unsealed fact{'s' if total_unsealed != 1 else ''}",
        f"last sealed {seal_tag}",
    ]
    if unarmed:
        rollup_parts.append(_unarmed_segment(unarmed, unarmed_facts, piped=piped))
    rollup = rollup_line(vertex, rollup_parts)
    if zoom == Zoom.MINIMAL:
        return wrap_hanging(rollup, p.metadata, width, hang=2)

    name_w = max((len(r["name"]) for r in loops), default=0)
    unarmed_name_w = max((len(r["name"]) for r in unarmed), default=0)
    rows: list[Block] = []

    if piped:
        # Flat ledger — full names, bare shape, unsealed count, ISO seal stamp,
        # whole condition + kind mix. One greppable line per armed loop. The
        # approaching signal rides as a trailing WORD, not the ▲ glyph — the
        # G4 stance: a pipe consumer greps words, it doesn't decode glyphs.
        for r in loops:
            if r["mode"] == "when":
                shape = f"when {r['trigger_kind']}"
                prox = f"{r['window_facts']} unsealed"
            else:
                shape = f"{r['mode']} {r['count']}"
                prox = f"{r['window_facts']}/{r['count']}"
            # Never-sealed rides the same "never sealed" phrase as the TTY (both
            # registers carry the wording — parity over word order); a sealed
            # row carries its absolute ISO stamp.
            seal_part = (
                "never sealed" if r["never_sealed"]
                else f"sealed {stamp(r['last_sealed'])}"
            )
            line = (
                f"{r['name']:<{name_w}}  {r['scope']:<6}  {shape}  "
                f"{prox}  {seal_part}"
            )
            cond = _conditions_text(r)
            if cond:
                line += f"  [{cond}]"
            mix = _mix_text(r, joiner=" ", sep="=")
            if mix:
                line += f"  {mix}"
            if _approaching(r, p):
                line += f"  {_APPROACHING_WORD}"
            rows.append(_line(line.rstrip(), Style(), None))
        # Unarmed per-loop rows enumerate uncapped at -v (the agent channel is
        # information-faithful); the header always carries the rollup counts.
        if unarmed and zoom >= Zoom.DETAILED:
            rows.append(_line("unarmed:", p.header, None))
            for r in unarmed:
                rows.append(
                    _line(_unarmed_row_text(r, unarmed_name_w, piped=True),
                          Style(), None)
                )
        header_parts = [
            f"{armed} armed",
            f"{total_unsealed} unsealed",
            f"last sealed {seal_tag}",
        ]
        if unarmed:
            header_parts.append(
                _unarmed_segment(unarmed, unarmed_facts, piped=True)
            )
        header = rollup_line(vertex, header_parts)
        return join_vertical(_line(header, p.header, None), *rows)

    # --- TTY register ------------------------------------------------------
    for r in loops:
        desc = _descriptor(r, zoom)
        # Gutter: no salience tier (honest absence) so it stays blank — EXCEPT
        # the ▲ status overlay when a count loop approaches its seal. Two-space
        # indent + glyph + space keeps the name column fixed whether or not the
        # overlay fires (a non-approaching row is identical to the old 4-space
        # indent, so style-stable goldens don't drift).
        g = _APPROACHING if _approaching(r, p) else " "
        text = f"  {g} {r['name']:<{name_w}}  {desc}"
        row = _line(text, Style(), width)
        if r["mode"] != "when":
            # Count-based: append a TTY-only proximity meter under the row body.
            meter = _meter(r["window_facts"], r["count"])
            if meter:
                # Colour ramps with closeness to the boundary — the palette owns
                # the thresholds (accent → warn → critical). TTY-only chrome: the
                # ratio is already stated by ``window_facts/count`` in the row.
                count = r["count"] or 0
                ratio = r["window_facts"] / count if count > 0 else 0.0
                row = join_vertical(
                    row,
                    _line(
                        f"    {'':<{name_w}}  {meter}",
                        p.horizon_meter_style(ratio), width,
                    ),
                )
        rows.append(row)

    # Unarmed rollup: a trailing one-line segment at default zoom, expanding to
    # per-loop ◦ rows at -v (decision:design/horizon-unarmed-rollup).
    unarmed_rows: list[Block] = []
    if unarmed:
        if loops:
            unarmed_rows.append(_line("", Style(), width))  # separator
        if zoom >= Zoom.DETAILED:
            unarmed_rows.append(_line("UNARMED", p.header, width))
            for r in unarmed:
                unarmed_rows.append(
                    _line(_unarmed_row_text(r, unarmed_name_w, piped=False),
                          p.metadata, width)
                )
        else:
            unarmed_rows.append(
                _line(f"  {_unarmed_segment(unarmed, unarmed_facts, piped=False)}",
                      p.metadata, width)
            )

    blocks: list[Block] = []
    if loops:
        body = join_vertical(*rows)
        sublines = [
            f"{armed} armed · {total_unsealed} unsealed",
        ]
        if last_sealed is not None:
            sublines.append(f"last sealed {recency(last_sealed)}")
        else:
            sublines.append("never sealed")
        title = f"{vertex} · horizon"
        card_w = card_width(body, title, sublines, width)
        blocks.append(card(title, sublines, card_w, p=p))
        blocks.append(body)
    else:
        # No armed loops, but unarmed accumulation exists — surface it honestly
        # rather than hiding it behind "nothing seals".
        blocks.append(_line("No armed loops.", p.metadata, width))
    blocks.extend(unarmed_rows)
    return join_vertical(*blocks)


# ``--lens horizon`` on the read/fold path resolves ``fold_view`` in this module
# (the composition-lens re-export pattern, see lenses/graph.py).
fold_view = horizon_view
