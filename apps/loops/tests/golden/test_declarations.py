"""Golden tests for the declarations lens (sl vertices).

Also locks the preview_fields declaration rendering — the lens surfaces
each by-kind's preview= decl at DETAILED+.
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.declarations import declarations_view

from .fixtures import SAMPLE_DECLARATIONS
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_declarations(golden, zoom):
    block = declarations_view(SAMPLE_DECLARATIONS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
