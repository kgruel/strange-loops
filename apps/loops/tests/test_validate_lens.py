"""Tests for validate lens — all zoom levels."""

from painted import Block, Zoom


def _text(block: Block) -> str:
    return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)


def test_validate_empty():
    from loops.lenses.validate import validate_view
    assert "No .loop" in _text(validate_view({"results": []}, Zoom.SUMMARY, 80))

def test_validate_minimal():
    from loops.lenses.validate import validate_view
    data = {"results": [{"path": "x.loop", "valid": True}], "checked": 1, "errors": 0}
    assert "1 valid" in _text(validate_view(data, Zoom.MINIMAL, 80))

def test_validate_summary_valid():
    from loops.lenses.validate import validate_view
    data = {"results": [{"path": "x.loop", "valid": True}], "checked": 1, "errors": 0}
    t = _text(validate_view(data, Zoom.SUMMARY, 80))
    assert "\u2713" in t
    assert "x.loop" in t

def test_validate_summary_error():
    from loops.lenses.validate import validate_view
    data = {"results": [{"path": "bad.loop", "valid": False, "error": "Parse error\ndetail"}],
            "checked": 1, "errors": 1}
    t = _text(validate_view(data, Zoom.SUMMARY, 80))
    assert "\u2717" in t
    assert "Parse error" in t

def test_validate_detailed_error():
    from loops.lenses.validate import validate_view
    data = {"results": [{"path": "bad.loop", "valid": False, "error": "Parse error\ndetail"}],
            "checked": 1, "errors": 1}
    t = _text(validate_view(data, Zoom.DETAILED, 80))
    assert "Parse error" in t

def test_validate_full_with_resolved():
    from loops.lenses.validate import validate_view
    data = {"results": [
        {"path": "x.loop", "valid": True},
        {"path": "bad.loop", "valid": False, "error": "Parse error"},
    ], "checked": 2, "errors": 1}
    t = _text(validate_view(data, Zoom.FULL, 80))
    assert "\u2713" in t
    assert "\u2717" in t
