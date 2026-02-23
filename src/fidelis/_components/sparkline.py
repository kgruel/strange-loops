"""Sparkline: single-row visualization of numeric sequences.

Renders a list of values as vertical bar characters showing relative magnitude.

Usage:
    from fidelis.widgets import sparkline
    from fidelis import Style

    values = [12, 15, 23, 45, 67, 89, 95, 87, 76, 65]
    block = sparkline(values, width=20, style=Style(fg="cyan"))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..block import Block
from ..cell import Style
from ..component_theme import ComponentTheme, component_theme

if TYPE_CHECKING:
    pass


def sparkline(
    values: list[float],
    width: int,
    *,
    style: Style | None = None,
    empty_char: str = "─",
    theme: ComponentTheme | None = None,
) -> Block:
    """Render values as a sparkline bar.

    Args:
        values: Sequence of numeric values to visualize.
        width: Target width in characters.
        style: Style for sparkline characters.
        empty_char: Character for empty/leading space when padding.
        theme: Optional theme (uses theme.icons.sparkline chars).

    Returns:
        Single-row Block with sparkline visualization.

    If len(values) < width, pads left with empty_char.
    If len(values) > width, uses last `width` values.
    """
    if width <= 0:
        return Block.empty(0, 1)

    t = theme or component_theme()
    style = style or t.muted
    chars = t.icons.sparkline

    if not values:
        return Block.text(empty_char * width, style, width=width)

    # Normalize to 0-1 range
    min_v = min(values)
    max_v = max(values)
    rng = max_v - min_v if max_v != min_v else 1.0

    # Sample or truncate to width
    if len(values) > width:
        sampled = values[-width:]
    else:
        sampled = values

    # Map each value to a character
    result_chars = []
    for v in sampled:
        normalized = (v - min_v) / rng
        idx = min(int(normalized * (len(chars) - 1)), len(chars) - 1)
        result_chars.append(chars[idx])

    # Pad left if needed
    result = "".join(result_chars).rjust(width, empty_char)
    return Block.text(result, style, width=width)


def sparkline_with_range(
    values: list[float],
    width: int,
    *,
    min_val: float | None = None,
    max_val: float | None = None,
    style: Style | None = None,
    empty_char: str = "─",
    theme: ComponentTheme | None = None,
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
        theme: Optional theme.

    Returns:
        Single-row Block with sparkline visualization.
    """
    if width <= 0:
        return Block.empty(0, 1)

    t = theme or component_theme()
    style = style or t.muted
    chars = t.icons.sparkline

    if not values:
        return Block.text(empty_char * width, style, width=width)

    # Use explicit range or derive from values
    lo = min_val if min_val is not None else min(values)
    hi = max_val if max_val is not None else max(values)
    rng = hi - lo if hi != lo else 1.0

    # Sample or truncate to width
    if len(values) > width:
        sampled = values[-width:]
    else:
        sampled = values

    # Map each value to a character, clamping to range
    result_chars = []
    for v in sampled:
        # Clamp value to range
        v_clamped = max(lo, min(hi, v))
        normalized = (v_clamped - lo) / rng
        idx = min(int(normalized * (len(chars) - 1)), len(chars) - 1)
        result_chars.append(chars[idx])

    # Pad left if needed
    result = "".join(result_chars).rjust(width, empty_char)
    return Block.text(result, style, width=width)
