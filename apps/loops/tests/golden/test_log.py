"""Golden tests for the log command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.log import log_view

from .fixtures import SAMPLE_LOG
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_log_demo(golden, zoom):
    block = log_view(SAMPLE_LOG, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
