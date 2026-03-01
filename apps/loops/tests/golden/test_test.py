"""Golden tests for the test command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.test import test_view as _test_view

from .fixtures import SAMPLE_TEST
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_test_demo(golden, zoom):
    block = _test_view(SAMPLE_TEST, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
