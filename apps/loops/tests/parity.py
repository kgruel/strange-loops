"""Channel-parity harness — one fetch, many render channels, agreeing content.

Resolves ``friction:two-surface-claims-lack-parity-tests`` (and its instance
``friction:register-split-piped-faithfulness-untested``). The bug CLASS: two
surfaces assert the same truth with no parity check between them, so the green
suite passes because each surface is tested in isolation.

The pattern here checks the opposite: render ONE fetched ``data`` dict through
BOTH registers of a register-split lens (``piped=True`` terse/agent, and
``piped=False`` rich/TTY) and assert both carry the same *load-bearing
information content* — after chrome (ANSI, box-drawing, meters, sparklines,
containment glyphs, alignment padding) is stripped.

The invariant (precisely)
--------------------------
For a lens rendered over one fetch, every *load-bearing token* — counts, entity
names, relative timestamps, and numeric flags (signed ratio, share %, span)
derived from the fetch — must appear in the chrome-stripped text of BOTH the
terse (piped, width-free) render and the rich (TTY, styled, width-bounded)
render. Additionally the piped render must never truncate (no ``…`` ellipsis
marker), because the agent channel inherits ``COLUMNS`` and a width-driven clip
silently drops information.

It is deliberately NOT byte equality: the two registers may *encode* the same
fact differently (type word ``instance`` vs glyph ``◆``; ``updated 2h ago`` vs
bare ``2h ago``). Parity is over the shared load-bearing set the extractors
below build from ``data`` — the tokens both registers are contracted to carry.

Adopting parity for a new register-split surface is ~3 lines::

    data = fetch_thing(...)             # or a representative dict
    assert_register_parity(thing_view, data, load_bearing=[...])

See ``tests/README.md`` for the full adoption note.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable

from painted import Block, Zoom

from .helpers import block_to_text

# ---------------------------------------------------------------------------
# Chrome stripping — reduce a rendered Block to its information content
# ---------------------------------------------------------------------------

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Decorative glyphs that carry no information a parity check should compare:
# box-drawing (U+2500–257F), block elements / meters / sparklines (U+2580–259F),
# containment + type glyphs, bullets, and the ellipsis marker.
_CHROME_CHARS = (
    "".join(chr(c) for c in range(0x2500, 0x25A0))  # box + block + sparkline
    + "◆◇◈⊃⊳•·…├┤"
)
_CHROME_TABLE = {ord(ch): " " for ch in _CHROME_CHARS}

_WS = re.compile(r"\s+")


def information_text(block: Block) -> str:
    """Chrome-stripped, whitespace-collapsed text of a rendered Block.

    ANSI removed, decorative glyphs blanked, runs of whitespace collapsed to a
    single space. What survives is the load-bearing content — the thing two
    channels must agree on.
    """
    raw = block_to_text(block, use_ansi=False)
    raw = _ANSI.sub("", raw)
    raw = raw.translate(_CHROME_TABLE)
    return _WS.sub(" ", raw).strip()


def raw_text(block: Block) -> str:
    """Rendered text WITHOUT chrome stripping (ANSI removed only).

    Used to detect the ``…`` ellipsis truncation marker before it is stripped.
    """
    return _ANSI.sub("", block_to_text(block, use_ansi=False))


# ---------------------------------------------------------------------------
# The parity assertion
# ---------------------------------------------------------------------------

# A register-split lens: (data, zoom, width, *, piped) -> Block
Lens = Callable[..., Block]


def _missing(tokens: Iterable[str], text: str) -> list[str]:
    return [t for t in tokens if str(t) not in text]


def assert_register_parity(
    lens: Lens,
    data: dict[str, Any],
    *,
    load_bearing: Iterable[str],
    zoom: Zoom = Zoom.SUMMARY,
    tty_width: int = 100,
    piped_width: int = 40,
) -> None:
    """Assert both registers of ``lens`` carry every load-bearing token.

    - Renders ``lens(data, zoom, tty_width, piped=False)`` (rich TTY) and
      ``lens(data, zoom, piped_width, piped=True)`` (terse agent channel).
    - ``piped_width`` is intentionally NARROW to simulate a pipe that inherited
      ``COLUMNS``: a faithful piped register forces ``width=None`` internally
      and renders untruncated regardless.
    - Every ``load_bearing`` token must appear in the chrome-stripped text of
      BOTH renders.
    - The piped render must contain no ``…`` (truncation would drop info).
    """
    tty = lens(data, zoom, tty_width, piped=False)
    piped = lens(data, zoom, piped_width, piped=True)

    tty_info = information_text(tty)
    piped_info = information_text(piped)
    tokens = list(load_bearing)

    miss_piped = _missing(tokens, piped_info)
    miss_tty = _missing(tokens, tty_info)

    assert "…" not in raw_text(piped), (
        "piped register truncated (found '…') at width="
        f"{piped_width} — the agent channel must force width=None.\n"
        f"piped:\n{raw_text(piped)}"
    )
    assert not miss_piped, (
        f"terse/piped register dropped load-bearing tokens {miss_piped}.\n"
        f"piped info-text:\n{piped_info}"
    )
    assert not miss_tty, (
        f"rich/TTY register dropped load-bearing tokens {miss_tty}.\n"
        f"tty info-text:\n{tty_info}"
    )


def assert_render_carries(
    lens: Lens,
    data: dict[str, Any],
    *,
    load_bearing: Iterable[str],
    zoom: Zoom = Zoom.SUMMARY,
    width: int = 100,
    piped: bool | None = None,
) -> None:
    """Single-channel variant — assert one render carries the load-bearing set.

    Use for plain-vs-``--json`` parity: ``--json`` faithfully serialises the
    fetch ``data`` by construction, so the check reduces to "the plain render
    also carries these dict-derived tokens." ``piped=None`` renders lenses that
    take no ``piped`` kwarg (store/stats/ticks views).
    """
    if piped is None:
        block = lens(data, zoom, width)
    else:
        block = lens(data, zoom, width, piped=piped)
    miss = _missing(load_bearing, information_text(block))
    assert not miss, (
        f"render dropped load-bearing tokens {miss}.\n"
        f"info-text:\n{information_text(block)}"
    )


# ---------------------------------------------------------------------------
# Compact fixture builders + load-bearing extractors, per surface
# ---------------------------------------------------------------------------


def vrow(
    name: str,
    *,
    facts: int | None = None,
    kind_count: int | None = None,
    mtime: float | None = None,
    preview: list[str] | None = None,
    vtype: str = "instance",
    combine: list[str] | None = None,
) -> dict[str, Any]:
    """A single vertex row for ``vertices_view`` (``sl ls`` root)."""
    v: dict[str, Any] = {"name": name, "kind": vtype}
    if facts is not None:
        v["facts"] = facts
    if kind_count is not None:
        v["kind_count"] = kind_count
    if mtime is not None:
        v["mtime"] = mtime
    if preview:
        v["kind_stats"] = [{"kind": k, "count": 1} for k in preview]
    if combine is not None:
        v["combine"] = combine
    return v


def ls_root_tokens(data: dict[str, Any]) -> list[str]:
    """Load-bearing tokens for ``vertices_view`` — the shared set both the TTY
    line-row and the piped row are contracted to carry: vertex names, fact
    counts, kind counts, relative mtimes, and preview kind names. (Type is
    encoded divergently — word vs glyph — so it is intentionally excluded.)
    """
    from loops.lenses.store import _format_count
    from loops.lenses.vertices import _rel_mtime

    rows = list(data.get("local_vertices", [])) + list(data.get("vertices", []))
    tokens: list[str] = []
    for v in rows:
        tokens.append(v["name"])
        if v.get("facts") is not None:
            tokens.append(f"{_format_count(v['facts'])} facts")
        if v.get("kind_count"):
            tokens.append(f"{v['kind_count']} kinds")
        if v.get("mtime") is not None:
            tokens.append(_rel_mtime(v["mtime"]))
        for k in v.get("kind_stats", []):
            tokens.append(k["kind"])
    return tokens


def decl_header_tokens(data: dict[str, Any]) -> list[str]:
    """Load-bearing tokens for ``declarations_view`` header (``sl ls <v>``):
    name, fact count, kind count, kind names, and the signed ratio (the field
    that shipped a piped-faithfulness bug)."""
    from loops.lenses.store import _format_count

    tokens = [data["vertex_name"]]
    if data.get("facts") is not None:
        tokens.append(f"{_format_count(data['facts'])} facts")
    if data.get("kind_count"):
        tokens.append(f"{data['kind_count']} kinds")
    signed = data.get("signed")
    if signed:
        tokens.append(f"signed {_format_count(signed[0])}/{_format_count(signed[1])}")
    for k in data.get("kinds", []):
        tokens.append(k["name"])
    return tokens


def kind_stat_tokens(data: dict[str, Any]) -> list[str]:
    """Load-bearing tokens for ``kind_stat_view`` (``sl ls <v> --kind K``):
    kind name, share-of-vertex, entry keys + counts, and the span (the
    share/span fields shipped a piped-faithfulness bug)."""
    from loops.lenses.store import _format_count

    tokens = [data.get("kind", "?")]
    if "share" in data and "vertex_name" in data:
        tokens.append(f"{data['share']:.1f}% of {data['vertex_name']}")
    for e in data.get("entries", []):
        tokens.append(str(e["key"]))
        tokens.append(_format_count(e["count"]))
    return tokens
