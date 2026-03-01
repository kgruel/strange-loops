"""Golden tests for the status command."""
from __future__ import annotations

import pytest
from painted import Zoom
from painted.fidelity import Format, OutputMode
from painted import CliContext

from loops.commands.session import render_status

from .fixtures import SAMPLE_STATUS
from .helpers import block_to_text


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, format=Format.PLAIN,
        is_tty=False, width=80, height=24,
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_status_demo(golden, zoom):
    block = render_status(_ctx(zoom), SAMPLE_STATUS)
    golden.assert_match(block_to_text(block), "output")
