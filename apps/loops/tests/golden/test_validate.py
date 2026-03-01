"""Golden tests for the validate command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.validate import validate_view

from .fixtures import SAMPLE_VALIDATE
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_validate_demo(golden, zoom):
    block = validate_view(SAMPLE_VALIDATE, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
