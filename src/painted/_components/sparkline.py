"""Sparkline: single-row visualization of numeric sequences.

Renders a list of values as vertical bar characters showing relative magnitude.

Usage:
    from painted.views import sparkline
    from painted import Style

    values = [12, 15, 23, 45, 67, 89, 95, 87, 76, 65]
    block = sparkline(values, width=20, style=Style(fg="cyan"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .._sparkline_core import sparkline_text
from ..block import Block
from ..cell import Style

if TYPE_CHECKING:
    from ..icon_set import IconSet
    from ..palette import Palette


def sparkline(
    values: list[float],
    width: int,
    *,
    style: Style | None = None,
    empty_char: str = "─",
    palette: Palette | None = None,
    icons: IconSet | None = None,
) -> Block:
    """Render values as a sparkline bar.

    Args:
        values: Sequence of numeric values to visualize.
        width: Target width in characters.
        style: Style for sparkline characters.
        empty_char: Character for empty/leading space when padding.
        palette: Optional Palette override (uses ambient if None).
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Single-row Block with sparkline visualization.

    If len(values) < width, pads left with empty_char.
    If len(values) > width, uses last `width` values.
    """
    if width <= 0:
        return Block.empty(0, 1)

    from ..icon_set import current_icons
    from ..palette import current_palette

    p = palette or current_palette()
    ic = icons or current_icons()
    style = style or p.muted
    chars = ic.sparkline

    if not values:
        return Block.text(empty_char * width, style, width=width)

    text = sparkline_text(
        values,
        width,
        chars=chars,
        sampling="tail",
        range_source="all",
        pad_left=True,
        pad_char=empty_char,
    )
    return Block.text(text, style, width=width)


def sparkline_with_range(
    values: list[float],
    width: int,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    style: Style | None = None,
    empty_char: str = "─",
    palette: Palette | None = None,
    icons: IconSet | None = None,
) -> Block:
    """Sparkline with explicit value range.

    Use when comparing multiple sparklines on the same scale.

    Args:
        values: Sequence of numeric values to visualize.
        width: Target width in characters.
        min_val: Explicit minimum for normalization (default: min of values).
        max_val: Explicit maximum for normalization (default: max of values).
        style: Style for sparkline characters.
        empty_char: Character for empty/leading space.
        palette: Optional Palette override (uses ambient if None).
        icons: Optional IconSet override (uses ambient if None).

    Returns:
        Single-row Block with sparkline visualization.
    """
    if width <= 0:
        return Block.empty(0, 1)

    from ..icon_set import current_icons
    from ..palette import current_palette

    p = palette or current_palette()
    ic = icons or current_icons()
    style = style or p.muted
    chars = ic.sparkline

    if not values:
        return Block.text(empty_char * width, style, width=width)

    # Use explicit range or derive from values
    lo = min_val if min_val is not None else min(values)
    hi = max_val if max_val is not None else max(values)

    text = sparkline_text(
        values,
        width,
        chars=chars,
        sampling="tail",
        lo=lo,
        hi=hi,
        clamp=True,
        pad_left=True,
        pad_char=empty_char,
    )
    return Block.text(text, style, width=width)
