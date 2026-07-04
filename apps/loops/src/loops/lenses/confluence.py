"""Confluence — the store cut by observer (the axis loops is named for).

Every view so far cuts by kind (fold, ls) or by time (stream, ticks).
Confluence cuts by WHO: one row per observer — fact count, kind mix,
recency — with the rail gutter carrying the observer's inherited tier
(an observer is a container cut: MAX over the tiers of the keys it
touched, decision:design/salience-max-propagation).

Delegation-path compounds (``a/b`` observer names) nest under their root
when the root itself has emitted — render-only grouping, no edge claim
(decision:design/observer-compound-delegation-path). The root's gutter
rolls up MAX over its group. Observers stay bare strings until a Peer
declaration gives them a face (decision:design/
observer-typing-dissolves-to-declared-peer); the ``-v`` feedback relay
and ``-vv`` horizon/potential rungs from the design study are named
fast-follows arriving with declared Peers, not build-1
(decision:design/confluence-build1-scope).

Wired as a composition lens: ``sl read <vertex> --lens confluence``.
The module-level ``fetch`` overrides the default fold fetch.
"""

from __future__ import annotations

from painted import Block, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE, LoopsPalette
from ._grammar import (
    RAIL_LEGEND,
    card,
    card_width,
    coerce_dt,
    full_iso,
    rail_glyph,
    recency,
    short_date,
    stamp,
)
from ._grammar import block as _line


def fetch(vertex_path, kind=None, observer=None):
    """Lens-declared fetch — the observer-cut projection."""
    from loops.commands.fetch import fetch_confluence

    return fetch_confluence(vertex_path, kind=kind, observer=observer)


UNATTRIBUTED = "(unattributed)"


def _display(name: str) -> str:
    return name or UNATTRIBUTED


def _root(name: str) -> str:
    """Delegation-path root: ``a/b`` groups under ``a``; '' stays its own."""
    return name.split("/", 1)[0] if name else name


def _group(observers: list[dict]) -> list[tuple[dict | None, list[dict]]]:
    """Group count-desc observers into (root_row | None, members) clusters.

    ``root_row`` is the observer whose name IS the root (when it emitted);
    ``members`` are the remaining group rows, count-desc. Groups keep the
    order of their hottest member (first appearance in the count-desc list).
    """
    clusters: dict[str, list[dict]] = {}
    order: list[str] = []
    for o in observers:
        r = _root(o["name"])
        if r not in clusters:
            clusters[r] = []
            order.append(r)
        clusters[r].append(o)
    out: list[tuple[dict | None, list[dict]]] = []
    for r in order:
        members = clusters[r]
        root_row = next((m for m in members if m["name"] == r), None)
        rest = [m for m in members if m is not root_row]
        out.append((root_row, rest))
    return out


def confluence_view(
    data: dict,
    zoom: Zoom,
    width: int | None,
    palette: LoopsPalette | None = None,
    *,
    piped: bool | None = None,
) -> Block:
    """Render the observer-cut projection on both registers.

    ``piped=True`` forces width=None — the agent channel never clips.
    """
    if piped:
        width = None

    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    observers = data.get("observers", [])
    total = data.get("total_facts", 0)

    if not observers:
        return _line("No facts — no observers.", p.metadata, width)

    def _rollup(top_n: int) -> str:
        top = " · ".join(
            f"{_display(o['name'])} {o['count']}" for o in observers[:top_n]
        )
        if len(observers) > top_n:
            top += (" · " if top else "") + f"+{len(observers) - top_n}"
        return f"{vertex} · {len(observers)} observers · {total} facts · {top}"

    rollup = _rollup(3)
    if zoom == Zoom.MINIMAL:
        # Shed top-observer names (3 → 0, rolled into +N) before letting the
        # one-liner clip — the counts survive, never a severed "+8" tail.
        if width is not None:
            for top_n in (3, 2, 1, 0):
                rollup = _rollup(top_n)
                if len(rollup) <= width:
                    break
        return _line(rollup, p.metadata, width)

    dim = Style(dim=True)
    name_w = max(
        len(_display(o["name"])) + (0 if o["name"] == _root(o["name"]) else 2)
        for o in observers
    )
    count_w = max(len(str(o["count"])) for o in observers)

    rows: list[Block] = []
    for root_row, rest in _group(observers):
        nested = root_row is not None and rest
        group = ([root_row] if root_row else []) + rest
        for o in group:
            is_child = nested and o is not root_row
            disp = f"└ {_display(o['name'])}" if is_child else _display(o["name"])
            # Root gutter rolls up MAX over its delegation group
            # (decision:design/observer-compound-delegation-path).
            tier = o["tier"]
            if nested and o is root_row:
                from loops.surface import tier_max

                tier = tier_max([m["tier"] for m in group])

            mix_items = list(o.get("kinds", {}).items())
            rec = recency(o.get("last"))

            def _desc(mix_n: int) -> str:
                mix = " · ".join(f"{k} {n}" for k, n in mix_items[:mix_n])
                if len(mix_items) > mix_n:
                    mix += (" · " if mix else "") + f"+{len(mix_items) - mix_n}"
                out = mix
                if rec:
                    out += f"   {rec}"
                return out

            # Full census at -v and up (piped always carries it whole); the
            # TTY row sheds mix entries (rolled into +N) before letting a row
            # clip mid-token — wrap-never-clip, and the recency trailer
            # survives. SUMMARY starts from top-3.
            full_n = len(mix_items)
            steps = (full_n, 3, 2, 1, 0) if zoom >= Zoom.DETAILED else (3, 2, 1, 0)
            desc = _desc(steps[0])
            prefix_w = 2 + 2 + name_w + 2 + count_w + 2  # "  ◆ name  count  "
            if width is not None:
                for mix_n in steps:
                    desc = _desc(mix_n)
                    if prefix_w + len(desc) <= width:
                        break

            if piped:
                # Flat ledger: full name, tier word, counts, absolute stamp,
                # whole (untruncated) kind mix. One greppable line per row.
                full_mix = " ".join(f"{k}={n}" for k, n in mix_items)
                line = (
                    f"{_display(o['name']):<{name_w}}  "
                    f"{o['tier'] or 'untiered':<8} "
                    f"{o['count']:>{count_w}} facts  "
                    f"{o['keys']:>4} keys  "
                    f"{stamp(o.get('last'))}  {full_mix}"
                )
                if zoom >= Zoom.FULL and o.get("first"):
                    line += (
                        f"  window {full_iso(o['first'])} → {full_iso(o['last'])}"
                    )
                rows.append(_line(line.rstrip(), Style(), width))
                if zoom >= Zoom.DETAILED and o.get("touched"):
                    touched = " · ".join(
                        f"{tk}:{tkey}" + (f" ×{tn}" if tn > 1 else "")
                        for tk, tkey, tn in o["touched"][:5]
                    )
                    rows.append(_line(f"  touched: {touched}", Style(), width))
            else:
                indent = "  " if is_child else ""
                row_style = Style(bold=True) if tier == "high" else Style()
                rows.append(_line(
                    f"  {rail_glyph(tier)} {disp:<{name_w}}"
                    f"  {o['count']:>{count_w}}  {desc}",
                    row_style, width,
                ))
                if zoom >= Zoom.DETAILED and o.get("touched"):
                    for tk, tkey, tn in o["touched"][:5]:
                        times = f" ×{tn}" if tn > 1 else ""
                        rows.append(_line(
                            f"    {indent}{tk}:{tkey}{times}", dim, width
                        ))
                if zoom >= Zoom.FULL and o.get("first"):
                    rows.append(_line(
                        f"    {indent}window: {stamp(o['first'])}"
                        f" → {stamp(o['last'])}",
                        dim, width,
                    ))

    body = join_vertical(*rows)

    # Piped keeps the plain rollup header (chrome-free); TTY wears the header
    # card (spine G5). Both channels carry observer count + total facts.
    if piped:
        return join_vertical(_line(rollup, p.header, None), body)

    sublines = [f"{len(observers)} observers · {total} facts"]
    stamps = [
        dt for o in observers if (dt := coerce_dt(o.get("last"))) is not None
    ]
    if stamps:
        firsts = [
            dt for o in observers if (dt := coerce_dt(o.get("first"))) is not None
        ]
        lo = min(firsts) if firsts else min(stamps)
        hi = max(stamps)
        span = short_date(lo) if lo == hi else f"{short_date(lo)} → {short_date(hi)}"
        sublines.append(f"{span} · latest {recency(hi)}")
    title = f"{vertex} · confluence"
    card_w = card_width(body, title, sublines, width)
    return join_vertical(
        card(title, sublines, card_w, p=p),
        body,
        _line(RAIL_LEGEND, dim, width),
    )


# ``--lens confluence`` on the read/fold path resolves ``fold_view`` in this
# module (the composition-lens re-export pattern, see lenses/autoresearch.py).
fold_view = confluence_view
