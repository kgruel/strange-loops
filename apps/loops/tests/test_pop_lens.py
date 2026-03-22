"""Tests for population lens — zoom-level rendering."""

from painted import Zoom

from .helpers import block_text as _text


def test_pop_no_header():
    from loops.lenses.pop import pop_view
    assert "No population" in _text(pop_view({"header": [], "rows": []}, Zoom.SUMMARY, 80))

def test_pop_minimal():
    from loops.lenses.pop import pop_view
    data = {"header": ["host", "port"], "rows": [{"host": "a", "port": "80"}]}
    t = _text(pop_view(data, Zoom.MINIMAL, 80))
    assert "host:" in t
    assert "1 entries" in t

def test_pop_summary():
    from loops.lenses.pop import pop_view
    data = {"header": ["host", "port"], "rows": [{"host": "server1", "port": "8080"}]}
    t = _text(pop_view(data, Zoom.SUMMARY, 80))
    assert "host" in t
    assert "server1" in t

def test_pop_empty_rows():
    from loops.lenses.pop import pop_view
    data = {"header": ["host", "port"], "rows": []}
    t = _text(pop_view(data, Zoom.SUMMARY, 80))
    assert "(empty)" in t

def test_pop_narrow_width():
    from loops.lenses.pop import pop_view
    data = {"header": ["host", "port", "description"], "rows": [
        {"host": "s1", "port": "80", "description": "A very long description that would overflow"}
    ]}
    block = pop_view(data, Zoom.SUMMARY, 40)
    assert block is not None  # doesn't crash on narrow width
