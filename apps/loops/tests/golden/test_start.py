"""Golden tests for the start command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.start import start_view

from .fixtures import SAMPLE_START
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_start_demo(golden, zoom):
    block = start_view(SAMPLE_START, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
