"""Golden tests for the fold command (was: status)."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.fold import fold_view

from .fixtures import SAMPLE_FOLD
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_status_demo(golden, zoom):
    block = fold_view(SAMPLE_FOLD, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
