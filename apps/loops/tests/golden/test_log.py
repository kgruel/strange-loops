"""Golden tests for the stream command (was: log)."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.stream import stream_view

from .fixtures import SAMPLE_STREAM
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_log_demo(golden, zoom):
    block = stream_view(SAMPLE_STREAM, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_log_demo_piped(golden, zoom):
    """The piped/agent register (width=None, piped=True) — S0 gap: the base
    goldens above only ever exercised the TTY register."""
    block = stream_view(SAMPLE_STREAM, zoom, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")
