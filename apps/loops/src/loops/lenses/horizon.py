"""Horizon — each armed loop's open window against its declared boundary.

Fold cuts by kind, stream/ticks by time, confluence by observer, graph by
connection; Horizon cuts by CYCLE PROXIMITY — how close each boundaried loop
sits to its next seal. One row per loop that DECLARES a boundary (a vertex-level
boundary is one row over the whole vertex). UNARMED = uncovered by ANY declared
trigger: a loop counts as unarmed only when it has no boundary of its own AND
the vertex declares no vertex-level boundary — a vertex boundary's tick sweeps
the whole window (all kinds), so every loop under it is covered by the armed
vertex row, and listing it as unarmed would double-report that row's unsealed
window. Unarmed loops no longer vanish but roll up into a trailing ``◦ N
unarmed · M facts accumulating`` segment (default/-q), expanding to per-loop ◦
rows at -v (decision:design/horizon-unarmed-rollup, amending
decision:design/horizon-build1-scope). Zero unarmed loops → the segment is
absent entirely (no ``◦ 0 unarmed`` noise).

Two boundary shapes render two honestly-different rows:

* **count-based** (``after``/``every``) — numeric proximity ``n/N`` with a
  TTY-only meter (``n`` unsealed facts against the declared ``count``).
* **kind-based** (``when``) — ``seals on next <kind> · N facts since last
  seal (<recency>)``. NO fake progress meter: a kind boundary has no numerator
  (hlab is 100% kind-based), so inventing a bar would smuggle a signal. The
  wording is consequence-side (thread:horizon-legibility-gap): the trigger is
  named as what CLOSES the window — for operator-emitted kinds (``seal``)
  that's the reader — and the count states its relation to the seal instead
  of juxtaposing two bare numbers. Vertex-scope rows carry their kind mix at
  default zoom (top-3 ``+N``); kind-scoped rows don't (their mix is trivially
  their own kind).

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

# Gutter glyph for an unarmed loop (covered by NO declared trigger — neither
# its own boundary nor a vertex-level one; accumulates, nothing ever seals it).
# TTY-only chrome; the pipe carries the bare words
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


def _since_phrase(ts: float) -> str:
    """``since last seal (2w)`` — the window stated as a RELATION.

    The old wording juxtaposed two numbers (``7 facts in window · last
    sealed 2w``) and left their relationship as an exercise for the reader;
    this states it: the window IS everything after that seal
    (thread:horizon-legibility-gap, Kyle 2026-07-15).
    """
    return f"since last seal ({recency(ts)})"


def _conditions_text(row: dict) -> str:
    """Boundary match + fold-state conditions as one clause, or ``''``.

    ``status=closed`` (payload match) · ``high >= 80`` (fold-state condition).
    Kind-based boundaries only; count-based carry none.
    """
    parts = [f"{k}={v}" for k, v in row.get("match", [])]
    parts += [f"{t} {op} {v}" for t, op, v in row.get("conditions", [])]
    return " · ".join(parts)


def _plural(n: int, noun: str) -> str:
    """``1 fact`` / ``2 facts`` — one pluralization idiom for the module."""
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _mix_text(
    row: dict, *, joiner: str = " · ", sep: str = " ", limit: int | None = None
) -> str:
    """Window kind mix — ``decision 2 · thread 1`` — or ``''`` when empty.

    ``limit`` truncates to the top-``limit`` kinds with a ``+N`` remainder
    tail (the default-zoom form: a bare fact count answers "how many" but
    not "of what", thread:horizon-legibility-gap); ``None`` is the full
    census (DETAILED). ``window_kinds`` is already count-desc from the
    fetch's ``most_common()``.
    """
    items = list(row.get("window_kinds", {}).items())
    parts = [f"{k}{sep}{n}" for k, n in items[:limit]]
    if limit is not None and len(items) > limit:
        parts.append(f"+{len(items) - limit}")
    return joiner.join(parts)


def _unarmed_segment(unarmed: list[dict], unarmed_facts: int, *, piped: bool) -> str:
    """The one-line unarmed rollup — ``◦ N unarmed · M facts accumulating``.

    TTY carries the ``◦`` glyph; the pipe carries the bare words (G4). Caller
    guards ``unarmed`` non-empty (zero unarmed loops → the segment is absent
    entirely, no ``◦ 0 unarmed`` noise, decision:design/horizon-unarmed-rollup).
    """
    glyph = "" if piped else f"{_UNARMED} "
    return (
        f"{glyph}{len(unarmed)} unarmed · "
        f"{_plural(unarmed_facts, 'fact')} accumulating"
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
    """The TTY row body after the name column (meter appended separately).

    Wording is consequence-side, not mechanism-side: ``seals on next seal``
    names what closes the window (for operator-emitted kinds like ``seal``
    that's the reader), and the fact count states its RELATION to the seal
    (``since last seal (2w)``) instead of juxtaposing two bare numbers
    (thread:horizon-legibility-gap).
    """
    if row["mode"] == "when":
        facts_word = _plural(row["window_facts"], "fact")
        out = f"seals on next {row['trigger_kind']}"
        if row["never_sealed"]:
            out += f" · never sealed · {facts_word} in window"
        else:
            out += f" · {facts_word} {_since_phrase(row['last_sealed'])}"
    else:
        out = f"{row['mode']} {row['count']} · {row['window_facts']}/{row['count']}"
        if row["never_sealed"]:
            out += " · never sealed"
        else:
            out += f" {_since_phrase(row['last_sealed'])}"
    if zoom < Zoom.DETAILED and row["scope"] == "vertex" and row["window_facts"]:
        # Default-zoom kind mix — vertex-scope windows span kinds, so the
        # referents matter; a kind-scoped row's mix is trivially its own kind
        # (pure redundancy, honest absence). DETAILED carries the full census
        # below instead.
        out += f" · {_mix_text(row, limit=3)}"
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


def _summary_parts(data: dict) -> list[str]:
    """Header/rollup segments shared by -q, the piped header, and the card.

    When every armed row hangs off ONE seal instant (the overwhelmingly
    common single-boundary case — and multi-boundary vertices sharing a tick
    series), the total is stated as a relation: ``7 facts since last seal
    (2w)``. With MIXED seal times that phrase would lie (the union spans
    windows with different starts), so the split form stays — honest wording
    per case, never a false merge (thread:horizon-legibility-gap).

    Shape contract: ``parts[0]`` is the armed count, ``parts[1]`` the fact
    total, ``parts[2:]`` an optional seal trailer — the card letterhead
    slices on these positions.
    """
    loops = data.get("loops", [])
    total_unsealed = data.get("total_unsealed", 0)
    parts = [_plural(data.get("armed", 0), "armed loop")]
    seal_set = {r["last_sealed"] for r in loops}
    if len(seal_set) == 1:
        only = next(iter(seal_set))
        if only is None:
            parts.append(f"{_plural(total_unsealed, 'fact')} in window")
            parts.append("never sealed")
        else:
            parts.append(f"{_plural(total_unsealed, 'fact')} {_since_phrase(only)}")
    else:
        last_sealed = data.get("last_sealed")
        parts.append(_plural(total_unsealed, "unsealed fact"))
        parts.append(
            f"last sealed {recency(last_sealed)}"
            if last_sealed is not None else "never sealed"
        )
    return parts


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
    piped = bool(piped)  # normalize None → False (the type says bool | None)
    if piped:
        width = None

    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    loops = data.get("loops", [])
    unarmed = data.get("unarmed", [])
    unarmed_facts = data.get("unarmed_facts", 0)

    if not loops and not unarmed:
        # Honest absence: a vertex with neither armed nor unarmed loops. One
        # true line, never an empty fake table.
        return _line("No armed loops — nothing seals.", p.metadata, width)

    # -q: the shared rollup, plus the unarmed segment appended as a trailing,
    # non-sheddable part. Its counts have no degraded form on the line, so —
    # like graph's hub segment — the whole line WRAPS rather than sheds
    # (decision:design/rollup-shed-only-what-degrades). ◦ is TTY-only; the pipe
    # carries the bare words.
    summary = _summary_parts(data)
    rollup_parts = list(summary)
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
        # The piped header IS the -q rollup: this branch has piped=True, so
        # the rollup above was already built with the piped unarmed segment.
        return join_vertical(_line(rollup, p.header, None), *rows)

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
        # Card letterhead: armed count + fact total merge onto the first
        # subline; any remaining segment (mixed-window seal recency) keeps
        # its own line (positions per _summary_parts' shape contract).
        sublines = [" · ".join(summary[:2])] + summary[2:]
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
