"""Golden tests for the trace lens (sl read … --diff and lifecycle).

Covers both trace modes: the normal lifecycle (which delegates to
stream_view) and the cumulative scalar-delta --diff render (loops-side).
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.trace import trace_view

from .fixtures import SAMPLE_TRACE, SAMPLE_TRACE_DIFF
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_trace_lifecycle(golden, zoom):
    block = trace_view(SAMPLE_TRACE, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_trace_diff(golden, zoom):
    block = trace_view(SAMPLE_TRACE_DIFF, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
