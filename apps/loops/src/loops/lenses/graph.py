"""Graph — the store cut as a directed ref/edge graph (the fourth view).

Fold cuts by kind, stream/ticks by time, confluence by observer; Graph cuts
by CONNECTION. One row is one node (a folded entity); the edges are its
outbound refs and typed edges resolved to another node. Three reads over the
same projection:

* **HUBS** — nodes by inbound count (the ``←N`` sinks). The per-hub predicate
  mix (``ref`` vs a declared typed-edge field name) is where typed edges
  become VISIBLE — the graph is the view that pays off the typed-edge overlay
  (decision:architecture/typed-edges-overlay-default).
* **CHAINS** — the longest directed ref paths (net-new traversal: memoized DFS
  with a per-path cycle guard + depth cap 32; refs point temporally backward so
  the graph is a near-DAG, back-edges are skipped, never crash).
* **ORPHANS** — isolated nodes (no inbound, no outbound refs/edges).

Deferred (decision:design/graph-build1-scope): connected components,
cross-vertex graph, interactive. Wired as a composition lens: ``sl read
<vertex> --lens graph``. The module-level ``fetch`` overrides the default fold
fetch; ``fold_view`` re-export routes ``--lens graph`` here.
"""

from __future__ import annotations

from painted import Block, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE, LoopsPalette
from ._grammar import (
    RAIL_LEGEND,
    card,
    card_width,
    rail_glyph,
    recency,
    rollup_line,
    stamp,
)
from ._grammar import block as _line


def fetch(vertex_path, kind=None, observer=None):
    """Lens-declared fetch — the ref/edge-graph projection."""
    from loops.commands.fetch import fetch_graph

    return fetch_graph(vertex_path, kind=kind, observer=observer)


def _counts_line(data: dict) -> str:
    """The shared stat spine — nodes · edges (typed) · orphans."""
    nodes = data.get("nodes", 0)
    edges = data.get("edges", 0)
    typed = data.get("typed_edges", 0)
    orphans = data.get("orphans", 0)
    return (
        f"{nodes} nodes · {edges} edges ({typed} typed) · {orphans} orphans"
    )


def _predicate_mix(predicates: list, top_n: int | None) -> str:
    """``ref 5 · stakeholder 2`` — the inbound predicate breakdown, top-N."""
    if top_n == 0:
        return ""  # fully shed — drop the mix, don't leave a bare "+N"
    items = predicates if top_n is None else predicates[:top_n]
    mix = " · ".join(f"{p} {n}" for p, n in items)
    if top_n is not None and len(predicates) > top_n:
        mix += (" · " if mix else "") + f"+{len(predicates) - top_n}"
    return mix


def _chain_line(path: list[str], width: int | None) -> str:
    """``a → b → c`` — shed middle segments to ``a → … → c`` before clipping."""
    full = " → ".join(path)
    if width is None or len(full) <= width or len(path) <= 2:
        return full
    return f"{path[0]} → … → {path[-1]}"


def graph_view(
    data: dict,
    zoom: Zoom,
    width: int | None,
    palette: LoopsPalette | None = None,
    *,
    piped: bool | None = None,
) -> Block:
    """Render the ref/edge-graph projection on both registers.

    ``piped=True`` forces width=None — the agent channel never clips, and every
    count (nodes/edges/typed/orphans/dangling), hub inbound, and full chain path
    is carried whole.
    """
    if piped:
        width = None

    p = palette or DEFAULT_PALETTE
    vertex = data.get("vertex", "")
    nodes = data.get("nodes", 0)
    hubs = data.get("hubs", [])
    chains = data.get("chains", [])
    orphans = data.get("orphans", 0)
    orphan_list = data.get("orphan_list", [])
    census = data.get("census", [])
    dangling = data.get("dangling", 0)

    if not nodes:
        return _line("No facts — no graph.", p.metadata, width)

    counts = _counts_line(data)
    rollup = rollup_line(
        vertex,
        [
            f"{nodes} nodes",
            f"{data.get('edges', 0)} edges ({data.get('typed_edges', 0)} typed)",
            f"{orphans} orphans",
        ],
        width=width,
        shed_from=1,
    )
    if zoom == Zoom.MINIMAL:
        return _line(rollup, p.metadata, width)

    dim = Style(dim=True)
    hub_n = len(hubs) if zoom >= Zoom.DETAILED else 10
    chain_n = len(chains) if zoom >= Zoom.FULL else 3

    rows: list[Block] = []

    if piped:
        # Flat sectioned ledger — full addresses, absolute stamps, whole mix.
        rows.append(_line("nodes:", p.header, None))
        for h in hubs[:hub_n]:
            mix = _predicate_mix(h.get("predicates", []), None)
            line = (
                f"  {h['address']}  ←{h['inbound']}  "
                f"{h.get('tier') or 'untiered':<8}"
            )
            if mix:
                line += f"  {mix}"
            if h.get("last") is not None:
                line += f"  {stamp(h['last'])}"
            rows.append(_line(line.rstrip(), Style(), None))
        if chains:
            rows.append(_line("chains:", p.header, None))
            for c in chains[:chain_n]:
                rows.append(_line(f"  {' → '.join(c)}", Style(), None))
        if orphan_list:
            rows.append(_line("orphans:", p.header, None))
            rows.append(
                _line("  " + " · ".join(orphan_list), Style(), None)
            )
        if census:
            rows.append(_line("edges:", p.header, None))
            for pred, count, typed in census:
                kind = "typed" if typed else "ref"
                rows.append(
                    _line(f"  {pred}  {count}  {kind}", Style(), None)
                )
        body = join_vertical(*rows)
        header = rollup_line(vertex, [counts, f"{dangling} dangling"])
        return join_vertical(_line(header, p.header, None), body)

    # --- TTY register ------------------------------------------------------
    if hubs:
        rows.append(_line("HUBS", p.header, width))
        # Cap the shared address column so a handful of very long addresses
        # don't pad every row into starving the predicate mix; longer ones sit
        # ragged past the cap rather than dragging the whole column right.
        name_w = min(44, max(len(h["address"]) for h in hubs[:hub_n]))
        in_w = max(len(str(h["inbound"])) for h in hubs[:hub_n])
        for h in hubs[:hub_n]:
            rec = recency(h.get("last"))
            preds = h.get("predicates", [])

            def _row(mix_n: int | None) -> str:
                mix = _predicate_mix(preds, mix_n)
                out = (
                    f"  {rail_glyph(h.get('tier', ''))} "
                    f"{h['address']:<{name_w}}  ←{h['inbound']:<{in_w}}"
                )
                if mix:
                    out += f"  {mix}"
                if rec:
                    out += f"   {rec}"
                return out

            # Shed predicate mix (full → 2 → 1 → 0) before letting the row clip.
            steps: tuple[int | None, ...] = (None, 2, 1, 0)
            text = _row(steps[0])
            if width is not None:
                for mix_n in steps:
                    text = _row(mix_n)
                    if len(text) <= width:
                        break
            style = Style(bold=True) if h.get("tier") == "high" else Style()
            rows.append(_line(text, style, width))

    if chains:
        rows.append(_line("", Style(), width))
        rows.append(_line("CHAINS", p.header, width))
        for c in chains[:chain_n]:
            rows.append(_line(f"  {_chain_line(c, width)}", Style(), width))

    if orphans:
        rows.append(_line("", Style(), width))
        if zoom >= Zoom.DETAILED and orphan_list:
            rows.append(_line(f"ORPHANS ({orphans})", p.header, width))
            for addr in orphan_list:
                rows.append(_line(f"  {addr}", dim, width))
        else:
            rows.append(_line(f"orphans: {orphans}", dim, width))

    if zoom >= Zoom.DETAILED and census:
        rows.append(_line("", Style(), width))
        rows.append(_line("EDGES", p.header, width))
        pred_w = max(len(c[0]) for c in census)
        cnt_w = max(len(str(c[1])) for c in census)
        for pred, count, typed in census:
            kind = "typed" if typed else "ref"
            rows.append(_line(
                f"  {pred:<{pred_w}}  {count:>{cnt_w}}  {kind}", dim, width
            ))

    body = join_vertical(*rows)

    sublines = [counts]
    if dangling:
        sublines.append(f"{dangling} dangling refs")
    title = f"{vertex} · graph"
    card_w = card_width(body, title, sublines, width)
    return join_vertical(
        card(title, sublines, card_w, p=p),
        body,
        _line(RAIL_LEGEND, dim, width),
    )


# ``--lens graph`` on the read/fold path resolves ``fold_view`` in this module
# (the composition-lens re-export pattern, see lenses/confluence.py).
fold_view = graph_view
