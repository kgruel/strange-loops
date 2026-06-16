"""Golden tests for fold-lens paths the basic fold golden doesn't exercise.

test_status.py covers the heuristic fold render. This locks the
preview-fields path: an explicit per-kind ``preview_fields`` decl drives
the body instead of the first-field heuristic.

The walked-items path (``--refs N`` graph walk → ``WalkedItem`` tuples) is
deferred to the fold-scoping session — it's part of the fold lens whose
``_render_item_line`` structural badge is the open residue of the
record_line dissolution (decision:design/record-line-dissolution-splits).
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.fold import fold_view

from .fixtures import SAMPLE_FOLD_PREVIEW
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_fold_preview_fields(golden, zoom):
    block = fold_view(SAMPLE_FOLD_PREVIEW, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
