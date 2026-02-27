"""Sparkline rendering with Palette and IconSet."""

from __future__ import annotations

from painted._components.sparkline import sparkline, sparkline_with_range
from painted.cell import Style
from painted.icon_set import ASCII_ICONS, reset_icons, use_icons
from painted.palette import MONO_PALETTE, reset_palette


def test_sparkline_default():
    reset_palette()
    reset_icons()
    block = sparkline([1, 2, 3], width=3)
    assert block.width == 3
    assert block.height == 1


def test_sparkline_explicit_palette():
    block = sparkline([1, 2, 3], width=3, palette=MONO_PALETTE)
    # MONO_PALETTE.muted is Style(dim=True) — default sparkline style
    assert block.row(0)[0].style.dim is True
    assert block.row(0)[0].style.fg is None


def test_sparkline_explicit_icons():
    block = sparkline([0, 50, 100], width=3, icons=ASCII_ICONS)
    row = block.row(0)
    # ASCII sparkline chars: ("_", ".", "-", "~", "^", "*", "#", "@")
    # All chars should be from ASCII set
    for cell in row:
        assert ord(cell.char) < 128


def test_sparkline_ambient_icons():
    reset_icons()
    use_icons(ASCII_ICONS)
    block = sparkline([0, 50, 100], width=3)
    row = block.row(0)
    for cell in row:
        assert ord(cell.char) < 128
    reset_icons()


def test_sparkline_with_range_palette():
    block = sparkline_with_range(
        [10, 50, 90],
        width=3,
        min_val=0,
        max_val=100,
        palette=MONO_PALETTE,
    )
    assert block.row(0)[0].style.dim is True


def test_sparkline_with_range_empty_values_uses_empty_char():
    block = sparkline_with_range([], width=4, empty_char=".")
    assert "".join(c.char for c in block.row(0)) == "...."


def test_sparkline_with_range_zero_width_returns_empty_block():
    block = sparkline_with_range([1, 2, 3], width=0)
    assert block.width == 0
    assert block.height == 1


def test_sparkline_with_range_explicit_range_affects_output():
    class FakeIcons:
        sparkline = ("0", "1")

    values = [0.0, 10.0]
    full_scale = sparkline_with_range(
        values,
        width=2,
        min_val=0.0,
        max_val=10.0,
        style=Style(),
        icons=FakeIcons(),  # type: ignore[arg-type]
    )
    half_scale = sparkline_with_range(
        values,
        width=2,
        min_val=0.0,
        max_val=20.0,
        style=Style(),
        icons=FakeIcons(),  # type: ignore[arg-type]
    )

    assert "".join(c.char for c in full_scale.row(0)) == "01"
    assert "".join(c.char for c in half_scale.row(0)) == "00"


def test_sparkline_style_overrides_palette():
    custom = Style(fg="magenta")
    block = sparkline([1, 2, 3], width=3, style=custom, palette=MONO_PALETTE)
    assert block.row(0)[0].style.fg == "magenta"
