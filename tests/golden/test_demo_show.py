"""Golden integration test for the primitives/show.py demo.

show.py writes directly to stdout via show(). We capture stdout and compare
against committed golden output.
"""

from __future__ import annotations

from pathlib import Path

from tools.capture import capture_demo

_PROJECT = Path(__file__).resolve().parent.parent.parent


def test_show_demo(golden):
    out = capture_demo(_PROJECT / "demos" / "primitives" / "show.py", "demo", width=80)
    assert isinstance(out, str)
    golden.assert_match(out, "output")
