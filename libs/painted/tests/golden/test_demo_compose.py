"""Golden integration test for the primitives/compose.py demo.

compose.py writes directly to stdout via print_block(). We capture stdout and
compare against committed golden output.
"""

from __future__ import annotations

from pathlib import Path

from tools.capture import capture_demo

_PROJECT = Path(__file__).resolve().parent.parent.parent


def test_compose_demo(golden):
    out = capture_demo(_PROJECT / "demos" / "primitives" / "compose.py", "demo", width=80)
    assert isinstance(out, str)
    golden.assert_match(out, "output")
