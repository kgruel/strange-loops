"""Golden tests for the ls (population) command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.pop import pop_view

from .fixtures import SAMPLE_LS
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_ls_demo(golden, zoom):
    block = pop_view(SAMPLE_LS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
