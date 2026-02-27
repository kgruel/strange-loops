"""Views that consume IconSet for glyph vocabulary."""
from __future__ import annotations

from painted.cell import Style
from painted.icon_set import ASCII_ICONS, reset_icons, use_icons
from painted._components.spinner import SpinnerState, spinner
from painted.views import tree_lens, chart_lens


def test_spinner_ambient_icons():
    reset_icons()
    use_icons(ASCII_ICONS)
    state = SpinnerState()
    block = spinner(state)
    # ASCII spinner: ("-", "\\", "|", "/") — frame 0 is "-"
    assert block.row(0)[0].char == "-"
    reset_icons()


def test_spinner_explicit_icons():
    state = SpinnerState()
    block = spinner(state, icons=ASCII_ICONS)
    assert block.row(0)[0].char == "-"


def test_spinner_style_kwarg_still_works():
    state = SpinnerState()
    block = spinner(state, style=Style(fg="red"))
    assert block.row(0)[0].style.fg == "red"


def test_tree_lens_explicit_icons():
    data = {"root": {"child": "leaf"}}
    block = tree_lens(data, zoom=2, width=40, icons=ASCII_ICONS)
    text = "".join(c.char for c in block.row(1))
    # ASCII tree uses "+-- " for branches
    assert "+--" in text or "`--" in text


def test_chart_lens_explicit_icons():
    data = [10, 20, 30, 40, 50]
    block = chart_lens(data, zoom=1, width=10, icons=ASCII_ICONS)
    row = block.row(0)
    # ASCII sparkline chars should all be ASCII
    for cell in row:
        assert ord(cell.char) < 128

