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
from pathlib import Path
from typing import Any, NamedTuple

from painted import Block, Line, Span, Style, Zoom, join_vertical

from ..palette import DEFAULT_PALETTE
from ._helpers import elide
from ._grammar import recency
from ._statview import freshness_style
from .store import _format_count


def _fmt_mtime(mtime: float | None) -> str:
    """'updated 2h ago' from an epoch float, or '—' when unknown/empty."""
    if mtime is None:
        return "—"
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return f"updated {recency(dt)}"


def _rel_mtime(mtime: float | None) -> str:
    """Bare '2h ago' for the TTY line-row — the column position carries the
    'updated' sense and the freshness gradient carries the urgency, so the
    'updated' word (kept on the piped register) is redundant chrome here."""
    if mtime is None:
        return "—"
    return recency(datetime.fromtimestamp(mtime, tz=timezone.utc))


# Vertex-type glyphs — the fill encodes "owns its own facts": ◆ instance (own
# store), ◇ aggregation (no store, only combines children), ◈ hybrid (both).
# Exactly one glyph per row, so inter-row column alignment holds regardless of
# the glyph's terminal cell width. TTY register only; piped keeps the word.
_TYPE_ICON = {"instance": "◆", "aggregation": "◇", "hybrid": "◈"}

# Cap the TTY name column so one pathologically long vertex name can't blow out
# the listing's alignment (the kinds table caps the same way at 22). Long names
# ellipsize; the piped register is left uncapped — it stays information-faithful.
_NAME_CAP = 28


def _icon_for(kind: str) -> str:
    return _TYPE_ICON.get(kind, "◆")


def _lead_kinds(v: dict[str, Any], limit: int = 3) -> str:
    """The ``⊃`` preview string — the top ``limit`` kinds by fact count (the
    'what's mostly inside' glance), consumed inline by the row builders. ``-v``
    expands this into the full per-kind census."""
    kind_stats = v.get("kind_stats")
    if kind_stats:
        names = [k["kind"] for k in kind_stats[:limit]]
        return " · ".join(names)
    # Aggregations carry their summary in the size column already — no preview.
    if v["kind"] == "aggregation":
        return ""
    # Fallback to declared loop names when stats absent (terse/unstat'd).
    return " · ".join(lp["name"] for lp in v.get("loops", []))


def vertices_view(
    data: dict[str, Any], zoom: Zoom, width: int | None, *, piped: bool = False
) -> Block:
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

    # The piped/agent register is information-faithful: never truncate or pad to
    # a terminal edge (ctx.width may still be a number when a pipe inherits
    # COLUMNS). Force width-free rendering so the ⊃ preview and stat payload are
    # carried in full (decision:design/presentation-register-keys-on-channel).
    if piped:
        width = None

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

    # All column widths are computed across whichever groups render rows, so the
    # stat columns — and the trailing ``⊃`` preview — line up across the local
    # and config sections under ``--all`` (config rows contribute only when
    # expanded or sole). _Cols carries the shared widths into _stat_rows.
    rendered = [*local]
    if expand_config or not local:
        rendered += vertices
    cols = _shared_cols(rendered, width, piped)

    if not local:
        # Outside a project — config is the primary listing.
        rows: list[Block] = [
            Block.text("config — ~/.config/loops", dim, width=width),
            *_stat_rows(vertices, zoom, width, cols, dim, piped=piped),
        ]
        return join_vertical(*rows)

    rows = [
        Block.text("local — cwd, verbs resolve these first", dim, width=width),
        *_stat_rows(local, zoom, width, cols, dim, piped=piped),
    ]
    if expand_config:
        rows.append(Block.text("config — ~/.config/loops", dim, width=width))
        rows.extend(_stat_rows(vertices, zoom, width, cols, dim, piped=piped))
    else:
        n = len(vertices)
        label = "vertex" if n == 1 else "vertices"
        hint = "sl ls --all"
        line = f"config — ~/.config/loops · {n} {label}"
        # Right-align the hint to the terminal edge on a TTY; when piped
        # (width None — no edge to pad to) just trail it after two spaces.
        pad = max(2, width - len(line) - len(hint)) if width else 2
        rows.append(Block.text(f"{line}{' ' * pad}{hint}", dim, width=width))
    return join_vertical(*rows)


def _mtime_style(p, mtime: float | None) -> Style:
    """Freshness-graded style for the `updated …` column (the resumption cue)."""
    if mtime is None:
        return p.metadata
    return freshness_style(p, datetime.fromtimestamp(mtime, tz=timezone.utc))


def _preview_spans(preview: str, p) -> list[Span]:
    """The lead-kinds preview as kind-tinted spans (each name in its own hue)."""
    spans: list[Span] = []
    for i, nm in enumerate(preview.split(" · ")):
        if i:
            spans.append(Span(" · ", p.chrome))
        spans.append(Span(nm, p.kind_style(nm)))
    return spans


def _spans_block(spans: list[Span], width: int | None) -> Block:
    """Styled block from spans on a TTY (``width`` is the terminal int); plain
    natural-width text when piped (``width is None``) — ``Line.to_block`` needs
    an int and the piped register strips colour anyway, so the bytes match."""
    if width is None:
        return Block.text("".join(s.text for s in spans), Style(), width=None)
    return Line(tuple(spans)).to_block(width)


def _size_str(v: dict[str, Any], count_w: int) -> str:
    """The size cell — fact count right-aligned + unit for instances/hybrids,
    ``combines N`` for aggregations, ``—`` for an unmaterialized store."""
    if v.get("kind") == "aggregation":
        n = len(v.get("combine", []))
        return f"combines {n}" if n else "—"
    facts = v.get("facts")
    if facts is None:
        return "—"
    return f"{_format_count(facts):>{count_w}} facts"


class _Cols(NamedTuple):
    """Shared column widths for the line-row, sized across all rendered groups
    so the stat columns and the trailing ``⊃`` preview align across sections."""
    name: int      # max name width (uncapped; the TTY register caps at _NAME_CAP)
    kind: int      # type-word column (piped register)
    size: int
    kinds: int     # 0 ⇒ no kinds column (none present, or TTY-dropped for width)
    count_w: int   # right-align width of the bare fact number
    mt: int
    cen_kind: int  # -v census: kind-name column, justified across all vertices
    cen_count: int  # -v census: count column, justified across all vertices


def _shared_cols(
    rendered: list[dict[str, Any]], width: int | None, piped: bool
) -> _Cols:
    """Compute the line-row column widths across every rendered vertex.

    mtime is padded to a common width so the ``⊃`` preview aligns ("1d ago" vs
    "33m ago"); register-specific (bare on TTY, "updated …" piped). On a TTY too
    narrow to seat the kinds column without crowding out the mtime (the
    resumption cue), the kinds column is dropped group-wide — the same uniform
    degradation the kinds table uses for TREND. The piped register never drops
    it (information-faithful; it renders width-free)."""
    max_name = max((len(v["name"]) for v in rendered), default=4)
    max_kind = max((len(v["kind"]) for v in rendered), default=8)
    count_w = max(
        (len(_format_count(v["facts"])) for v in rendered
         if v.get("kind") != "aggregation" and v.get("facts") is not None),
        default=1,
    )
    size_w = max((len(_size_str(v, count_w)) for v in rendered), default=1)
    kinds_w = max(
        (len(f"{v['kind_count']} kinds") for v in rendered if v.get("kind_count")),
        default=0,
    )
    mt_fmt = _fmt_mtime if piped else _rel_mtime
    mt_w = max((len(mt_fmt(v.get("mtime"))) for v in rendered), default=1)

    # -v census columns, justified across every rendered vertex so the kind /
    # count columns line up between sibling censuses (under -v and -v --all).
    census = [k for v in rendered for k in (v.get("kind_stats") or [])]
    cen_kind = max((len(k["kind"]) for k in census), default=0)
    cen_count = max((len(_format_count(k["count"])) for k in census), default=0)

    if not piped and kinds_w and width is not None:
        ncol = min(max_name, _NAME_CAP)
        seat = 2 + 2 + ncol + 2 + size_w + 2 + kinds_w + 2 + mt_w
        if seat > width:
            kinds_w = 0
    return _Cols(max_name, max_kind, size_w, kinds_w, count_w, mt_w,
                 cen_kind, cen_count)


def _stat_rows(
    vertices: list[dict[str, Any]],
    zoom: Zoom,
    width: int | None,
    cols: _Cols,
    dim: Style,
    *,
    piped: bool = False,
) -> list[Block]:
    """Stat rows for one group — one line per vertex: name · size · kinds ·
    updated · ``⊃`` lead-kinds (decision:rendering/ls-root-line-row).

    Two registers (decision:design/presentation-register-keys-on-channel): the
    TTY path flags the vertex type with a glyph (◆/◇/◈), hues the name, grades
    ``updated`` on the freshness gradient, and tints the inline preview; the
    piped path keeps the type *word* (information-faithful) in plain aligned
    text. The ``⊃`` ("contains") marker carries the containment relation the
    whole ``ls`` redesign is built on onto a single scannable row.
    """
    p = DEFAULT_PALETTE
    rows: list[Block] = []

    for v in vertices:
        if piped:
            rows.append(_piped_row(v, cols, width))
        else:
            rows.append(_tty_row(v, cols, width, p))

        # Shadow clarification (standard case, every zoom) — name what the local
        # vertex overrides, on its own line so line 1 stays a clean stat row.
        if v.get("shadows"):
            rows.append(_shadow_line(v, width, p))

        # DETAILED expands the ⊃ preview into the full per-kind census: every
        # kind by count + its fold op, indented under the vertex.
        if zoom >= Zoom.DETAILED:
            rows.extend(_detail_kind_rows(v, cols, width, p))

        if zoom >= Zoom.FULL:
            if "store" in v:
                rows.append(Block.text(f"      store: {v['store']}", dim, width=width))
            if "combine" in v:
                rows.append(Block.text(f"      combine: {', '.join(v['combine'])}", dim, width=width))
            if "discover" in v:
                rows.append(Block.text(f"      discover: {v['discover']}", dim, width=width))

    return rows


def _shadow_line(v: dict[str, Any], width: int | None, p) -> Block:
    """`⊳ shadows <path>` — the config vertex this local one overrides."""
    raw = v.get("shadows_path")
    if raw:
        home = str(Path.home())
        target = raw.replace(home, "~") if raw.startswith(home) else raw
    else:
        target = "the config vertex of the same name"
    return _spans_block([
        Span("      ", Style()),
        Span("⊳ ", Style(fg="yellow")),
        Span(f"shadows {target}", p.chrome),
    ], width)


def _detail_kind_rows(
    v: dict[str, Any], cols: _Cols, width: int | None, p
) -> list[Block]:
    """Per-kind census for ``-v`` — each kind (count-descending) with its live
    count and fold op, indented under the vertex. Kind/count columns are
    justified across *all* rendered vertices (``cols``) so sibling censuses line
    up. Falls back to declared loops when no live stats are present (freshly
    declared / unmaterialized store)."""
    stats = v.get("kind_stats") or []
    fold_map = {lp["name"]: ", ".join(lp["folds"]) for lp in v.get("loops", [])}
    if not stats:
        out: list[Block] = []
        for lp in v.get("loops", []):
            folds = ", ".join(lp["folds"]) if lp["folds"] else "no folds"
            txt = f"      {lp['name']} ({folds})"
            out.append(Block.text(
                elide(txt, width) if width else txt, p.metadata, width=width
            ))
        return out
    out = []
    for k in stats:
        name = k["kind"]
        spans = [
            Span("      ", Style()),
            Span(name.ljust(cols.cen_kind), p.kind_style(name)),
            Span("  ", Style()),
            Span(_format_count(k["count"]).rjust(cols.cen_count), p.metadata),
        ]
        fold = fold_map.get(name)
        if fold:
            spans.append(Span(f"  {fold}", p.chrome))
        out.append(_spans_block(spans, width))
    return out


def _tty_row(v: dict[str, Any], cols: _Cols, width: int | None, p) -> Block:
    """One TTY line-row — type glyph + hued name + stats + ``⊃`` tinted preview.
    The shadow marker is a separate sub-line (:func:`_shadow_line`)."""
    ncol = min(cols.name, _NAME_CAP)
    name = v["name"]
    name_disp = elide(name, ncol) if len(name) > ncol else name
    name_pad = " " * max(0, ncol - len(name_disp))
    size = _size_str(v, cols.count_w).ljust(cols.size)

    spans: list[Span] = [
        Span("  ", Style()),
        Span(_icon_for(v.get("kind", "instance")) + " ", p.chrome),
        Span(name_disp, p.kind_style(name)),  # hue keyed on the full name
        Span(name_pad + "  ", Style()),
        Span(size, p.metadata),
    ]
    # Fixed-width left part (icon counted as one cell — uniform per row, so the
    # columns stay mutually aligned even if a terminal renders it wider).
    left = 2 + 2 + ncol + 2 + cols.size
    if cols.kinds:
        kc = v.get("kind_count")
        spans.append(Span("  ", Style()))
        spans.append(Span((f"{kc} kinds" if kc else "").ljust(cols.kinds), p.metadata))
        left += 2 + cols.kinds
    # Right-aligned to mt width (matches the kinds-table UPDATED column) so the
    # preview column lands at the same offset on every row.
    mt = _rel_mtime(v.get("mtime")).rjust(cols.mt)
    spans.append(Span("  ", Style()))
    spans.append(Span(mt, _mtime_style(p, v.get("mtime"))))
    left += 2 + cols.mt

    preview = _lead_kinds(v)
    if preview:
        if width:
            preview = elide(preview, max(0, width - left - 4))  # 4 = "  ⊃ "
        if preview:
            spans.append(Span("  ⊃ ", p.chrome))
            spans.extend(_preview_spans(preview, p))
    return Line(tuple(spans)).to_block(width)


def _piped_row(v: dict[str, Any], cols: _Cols, width: int | None) -> Block:
    """One piped line-row — type *word*, plain aligned, ``⊃`` inline preview.
    The shadow marker is a separate sub-line (:func:`_shadow_line`)."""
    name = v["name"].ljust(cols.name)
    line = (
        f"  {name}  {v['kind'].ljust(cols.kind)}  "
        f"{_size_str(v, cols.count_w).ljust(cols.size)}"
    )
    if cols.kinds:
        kc = v.get("kind_count")
        line += f"  {(f'{kc} kinds' if kc else '').ljust(cols.kinds)}"
    # Left-aligned ("updated" word aligns) but padded to mt width so ``⊃`` aligns.
    line += f"  {_fmt_mtime(v.get('mtime')).ljust(cols.mt)}"
    preview = _lead_kinds(v)
    if preview:
        line += f"  ⊃ {preview}"
    else:
        line = line.rstrip()  # drop the mtime-pad on a preview-less (agg) row
    if width:
        line = elide(line, width)
    return Block.text(line, Style(), width=width)
