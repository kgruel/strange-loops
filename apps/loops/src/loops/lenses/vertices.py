"""Vertices lens — stat-over-containment rendering for `sl ls`.

`sl ls` is the resumption orient at the front door
(decision:design/ls-as-stat-over-containment): each vertex is a directory in
the containment tree (vertex ⊃ kind ⊃ fact), rendered with uniform stat columns
— size (Σfacts), mtime (last update), type (instance/aggregation/hybrid). The
mtime column answers "where did I leave off?" before any lens runs.

The local layer (cwd, verbs resolve first) always carries stats and is
foregrounded; the config layer collapses to a drillable count-line unless
``--all`` expands it. ``-1`` is the terse names-only opt-out.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from painted import Block, Line, Span, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE
from ._helpers import elide
from ._statview import freshness_style
from .store import _format_count, _relative_time


def _fmt_mtime(mtime: float | None) -> str:
    """'updated 2h ago' from an epoch float, or '—' when unknown/empty."""
    if mtime is None:
        return "—"
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return f"updated {_relative_time(dt)}"


def _fmt_size(v: dict[str, Any]) -> str:
    """The size column — '2.7k facts' for instances, 'combines N' for aggs."""
    if v["kind"] == "aggregation":
        n = len(v.get("combine", []))
        return f"combines {n}" if n else "—"
    facts = v.get("facts")
    if facts is None:
        return "—"  # store not materialized yet, or stats not fetched
    return f"{_format_count(facts)} facts"


def _lead_kinds(v: dict[str, Any], limit: int = 3) -> str:
    """Preview line — the lead kinds by count (the 'what's inside' glance)."""
    kind_stats = v.get("kind_stats")
    if kind_stats:
        names = [k["kind"] for k in kind_stats[:limit]]
        return " · ".join(names)
    # Aggregations carry their summary in the size column already — no preview.
    if v["kind"] == "aggregation":
        return ""
    # Fallback to declared loop names when stats absent (terse/unstat'd).
    return " · ".join(lp["name"] for lp in v.get("loops", []))


def vertices_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render the stat-over-containment vertex listing.

    data: {
      "vertices":       [...],          # config layer
      "local_vertices": [...]?,         # cwd layer — verbs resolve first
      "cwd":            str?,
      "expand_config":  bool?,          # --all
      "terse":          bool?,          # -1
    }

    Zoom: MINIMAL = count line · SUMMARY = stat rows + preview · DETAILED =
    + per-loop detail · FULL = + store paths, combine, discover.
    """
    vertices = data.get("vertices", [])
    local = data.get("local_vertices", [])
    expand_config = data.get("expand_config", False)
    terse = data.get("terse", False)

    if terse:
        names = [v["name"] for v in local] + [v["name"] for v in vertices]
        if not names:
            return Block.text("", Style(), width=width)
        return join_vertical(
            *(Block.text(n, Style(), width=width) for n in names)
        )

    if zoom == Zoom.MINIMAL:
        n = len(vertices)
        if local:
            m = len(local)
            return Block.text(
                f"{m} local + {n} config vertices", Style(), width=width,
            )
        label = "vertex" if n == 1 else "vertices"
        return Block.text(f"{n} {label}", Style(), width=width)

    if not vertices and not local:
        return Block.text(
            "No vertices discovered.", Style(dim=True), width=width,
        )

    dim = Style(dim=True)

    # Column widths computed across whichever groups render rows, so the stat
    # columns line up. Config rows contribute only when expanded (or sole).
    rendered = [*local]
    if expand_config or not local:
        rendered += vertices
    max_name = max((len(v["name"]) for v in rendered), default=4)
    max_kind = max((len(v["kind"]) for v in rendered), default=8)

    if not local:
        # Outside a project — config is the primary listing.
        rows: list[Block] = [
            Block.text("config — ~/.config/loops", dim, width=width),
            *_stat_rows(vertices, zoom, width, max_name, max_kind, dim),
        ]
        return join_vertical(*rows)

    rows = [
        Block.text("local — cwd, verbs resolve these first", dim, width=width),
        *_stat_rows(local, zoom, width, max_name, max_kind, dim),
    ]
    if expand_config:
        rows.append(Block.text("config — ~/.config/loops", dim, width=width))
        rows.extend(_stat_rows(vertices, zoom, width, max_name, max_kind, dim))
    else:
        n = len(vertices)
        label = "vertex" if n == 1 else "vertices"
        hint = "sl ls --all"
        line = f"config — ~/.config/loops · {n} {label}"
        pad = max(2, width - len(line) - len(hint))
        rows.append(Block.text(f"{line}{' ' * pad}{hint}", dim, width=width))
    return join_vertical(*rows)


def _mtime_style(p, mtime: float | None) -> Style:
    """Freshness-graded style for the `updated …` column (the resumption cue)."""
    if mtime is None:
        return p.metadata
    return freshness_style(p, datetime.fromtimestamp(mtime, tz=timezone.utc))


def _preview_line(indent: str, preview: str, width: int, p) -> Block:
    """The lead-kinds preview, each kind name in its own hue."""
    full = indent + preview
    if width and len(full) > width:
        return Block.text(elide(full, width), p.metadata, width=width)
    spans = [Span(indent, Style())]
    for i, nm in enumerate(preview.split(" · ")):
        if i:
            spans.append(Span(" · ", p.chrome))
        spans.append(Span(nm, p.kind_style(nm)))
    return Line(tuple(spans)).to_block(width)


def _stat_rows(
    vertices: list[dict[str, Any]],
    zoom: Zoom,
    width: int,
    max_name: int,
    max_kind: int,
    dim: Style,
) -> list[Block]:
    """Stat rows for one group — the `ls -l` columns plus a preview line.

    Layout is identical across registers; the TTY register adds colour on top
    (vertex name hued, ``updated`` on the freshness gradient, the shadow marker
    and lead-kind preview tinted). Colour strips at the writer on a pipe, so the
    piped bytes are unchanged.
    """
    p = DEFAULT_PALETTE
    rows: list[Block] = []

    for v in vertices:
        name = v["name"].ljust(max_name)
        kind = v["kind"].ljust(max_kind)
        size = _fmt_size(v)
        kc = v.get("kind_count")
        kinds_col = f"{kc} kinds" if kc else ""
        mtime = _fmt_mtime(v.get("mtime"))

        # Truncation priority for the resumption orient: mtime ("where did I
        # leave off?") and the shadow marker must survive; the kinds column is
        # the expendable one and drops first when the row won't fit.
        marker = "  ⊳ shadows" if v.get("shadows") else ""
        essential = f"  {name}  {kind}  {size}   {mtime}"
        budget = (width or len(essential) + len(marker)) - len(marker)
        full = f"  {name}  {kind}  {size}" + (
            f"   {kinds_col}" if kinds_col else ""
        ) + f"   {mtime}"
        if len(full) <= budget:
            # Build the row as styled spans (text identical to ``full + marker``).
            mid = f"  {kind}  {size}" + (f"   {kinds_col}" if kinds_col else "") + "   "
            spans = [
                Span("  ", Style()),
                Span(name, p.kind_style(v["name"])),
                Span(mid, p.metadata),
                Span(mtime, _mtime_style(p, v.get("mtime"))),
            ]
            if marker:
                spans.append(Span(marker, Style(fg="yellow")))
            rows.append(Line(tuple(spans)).to_block(width))
        else:
            rows.append(Block.text(elide(essential, budget) + marker, Style(), width=width))

        # Preview line — the lead kinds (what's inside), kind-tinted and indented.
        preview = _lead_kinds(v)
        if preview:
            indent = "  " + " " * max_name + "  "
            rows.append(_preview_line(indent, preview, width, p))

        if zoom >= Zoom.DETAILED:
            for lp in v.get("loops", []):
                folds_str = ", ".join(lp["folds"]) if lp["folds"] else "no folds"
                detail = elide(f"    {lp['name']} ({folds_str})", width)
                rows.append(Block.text(detail, dim, width=width))

        if zoom >= Zoom.FULL:
            if "store" in v:
                rows.append(Block.text(f"    store: {v['store']}", dim, width=width))
            if "combine" in v:
                rows.append(Block.text(f"    combine: {', '.join(v['combine'])}", dim, width=width))
            if "discover" in v:
                rows.append(Block.text(f"    discover: {v['discover']}", dim, width=width))

    return rows
