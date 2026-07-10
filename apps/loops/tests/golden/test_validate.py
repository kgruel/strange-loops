"""Golden tests for the validate command."""
from __future__ import annotations

import re

import pytest
from painted import Zoom

from loops.lenses.validate import validate_view

from .fixtures import SAMPLE_VALIDATE
from .helpers import block_to_text


def _scrub(text: str) -> str:
    for result in SAMPLE_VALIDATE["results"]:
        path = result["path"]
        if result["valid"]:
            header = f"✓ {path}"
        else:
            header = f"✗ {path}:"
        pattern = rf"(^" + re.escape(header) + r"\n)    /[^\n]*$"
        text = re.sub(
            pattern,
            r"\1    <ABS_PATH>",
            text,
            count=1,
            flags=re.MULTILINE,
        )
    return text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_validate_demo(golden, zoom):
    block = validate_view(SAMPLE_VALIDATE, zoom, width=80)
    golden.assert_match(_scrub(block_to_text(block)), "output")
