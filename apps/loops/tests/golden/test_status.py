"""Golden tests for the status command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.status import status_view

from .fixtures import SAMPLE_STATUS
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_status_demo(golden, zoom):
    block = status_view(SAMPLE_STATUS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
