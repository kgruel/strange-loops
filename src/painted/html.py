"""HTML rendering for Blocks.

Renders Blocks into <pre> output suitable for docs. Mirrors the traversal
pattern in painted.writer._write_block_ansi (row-by-row, coalescing runs
of identical style).
"""

from __future__ import annotations

import html as _html

from .block import Block
from .cell import NAMED_COLORS, Style
from .writer import _idx_to_rgb


def _color_to_css(color: str | int | None) -> str | None:
    if color is None:
        return None
    if isinstance(color, int):
        r, g, b = _idx_to_rgb(color)
        return f"#{r:02x}{g:02x}{b:02x}"
    if isinstance(color, str):
        if color.startswith("#") and len(color) == 7:
            return color
        if color.lower() in NAMED_COLORS:
            return color.lower()
    return None


def _style_to_css(style: Style) -> str:
    fg = style.fg
    bg = style.bg
    if style.reverse:
        fg, bg = bg, fg

    parts: list[str] = []
    fg_css = _color_to_css(fg)
    bg_css = _color_to_css(bg)
    if fg_css is not None:
        parts.append(f"color: {fg_css}")
    if bg_css is not None:
        parts.append(f"background-color: {bg_css}")
    if style.bold:
        parts.append("font-weight: bold")
    if style.italic:
        parts.append("font-style: italic")
    if style.underline:
        parts.append("text-decoration: underline")
    if style.dim:
        parts.append("opacity: 0.6")
    return "; ".join(parts)


def render_html(block: Block) -> str:
    """Render a Block into HTML.

    Returns a <pre class="painted-output"> wrapper containing optional
    <span style="..."> runs for styled cells.
    """
    out: list[str] = ['<pre class="painted-output">']

    for row_idx in range(block.height):
        last_css: str | None = None
        span_open = False

        for cell in block.row(row_idx):
            css = _style_to_css(cell.style)
            if not css:
                if span_open:
                    out.append("</span>")
                    span_open = False
                    last_css = None
                out.append(_html.escape(cell.char))
                continue

            if css != last_css:
                if span_open:
                    out.append("</span>")
                out.append(f'<span style="{_html.escape(css, quote=True)}">')
                span_open = True
                last_css = css

            out.append(_html.escape(cell.char))

        if span_open:
            out.append("</span>")
        out.append("\n")

    out.append("</pre>\n")
    return "".join(out)
