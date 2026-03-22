"""Tests for compile lens — all zoom levels."""

from painted import Zoom

from .helpers import block_text as _text


# --- Loop rendering ---

def test_compile_loop_minimal():
    from loops.lenses.compile import compile_view
    data = {"type": "loop", "name": "echo test", "parse": ["skip 1"]}
    assert "echo test" in _text(compile_view(data, Zoom.MINIMAL, 80))
    assert "1 parse" in _text(compile_view(data, Zoom.MINIMAL, 80))

def test_compile_loop_summary():
    from loops.lenses.compile import compile_view
    data = {"type": "loop", "name": "cmd", "command": "echo", "kind": "m", "observer": "o", "format": "lines", "parse": ["skip 1"]}
    t = _text(compile_view(data, Zoom.SUMMARY, 80))
    assert "kind: m" in t
    assert "1 ops" in t

def test_compile_loop_detailed():
    from loops.lenses.compile import compile_view
    data = {"type": "loop", "name": "cmd", "command": "echo", "kind": "m", "observer": "o", "format": "lines", "parse": ["skip 1", "split ,"]}
    t = _text(compile_view(data, Zoom.DETAILED, 80))
    assert "1. skip 1" in t
    assert "2. split ," in t

def test_compile_loop_full():
    from loops.lenses.compile import compile_view
    data = {"type": "loop", "name": "cmd", "command": "echo", "kind": "m", "observer": "o", "format": "lines", "parse": [], "source_path": "/tmp/test.loop"}
    t = _text(compile_view(data, Zoom.FULL, 80))
    assert "path: /tmp/test.loop" in t


# --- Vertex rendering ---

def test_compile_vertex_minimal():
    from loops.lenses.compile import compile_view
    data = {"type": "vertex", "name": "proj", "specs": {"m": {}}, "routes": {"metric": "m"}}
    t = _text(compile_view(data, Zoom.MINIMAL, 80))
    assert "1 loops" in t
    assert "1 routes" in t

def test_compile_vertex_summary():
    from loops.lenses.compile import compile_view
    data = {"type": "vertex", "name": "proj", "specs": {
        "m": {"state_fields": ["n"], "folds": ["inc"], "boundary": None}
    }, "routes": {"metric": "m"}, "store": "/data/db", "discover": "*.vertex", "emit": "status"}
    t = _text(compile_view(data, Zoom.SUMMARY, 80))
    assert "store:" in t
    assert "metric -> m" in t

def test_compile_vertex_detailed():
    from loops.lenses.compile import compile_view
    data = {"type": "vertex", "name": "proj", "specs": {
        "m": {"state_fields": ["n"], "folds": ["inc", "sum"], "boundary": "after 10"}
    }, "routes": {}}
    t = _text(compile_view(data, Zoom.DETAILED, 80))
    assert "- inc" in t
    assert "boundary:" in t

def test_compile_unknown_type():
    from loops.lenses.compile import compile_view
    t = _text(compile_view({"type": "mystery"}, Zoom.SUMMARY, 80))
    assert "Unknown type" in t

def test_compile_vertex_full_with_path():
    """Vertex FULL zoom with source_path (L94-96)."""
    from loops.lenses.compile import compile_view
    data = {"type": "vertex", "name": "proj", "specs": {}, "routes": {},
            "source_path": "/etc/proj.vertex"}
    t = _text(compile_view(data, Zoom.FULL, 80))
    assert "path: /etc/proj.vertex" in t
