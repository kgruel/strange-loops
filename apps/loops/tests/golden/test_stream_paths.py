"""Golden coverage for stream-lens paths the base goldens never exercised.

test_log.py locks the plain fact list (TTY + piped, no tier/tick/id-lookup/
honesty branches). These lock the paths the 0.8.0 lens-signature migration's
render_row consolidation lands hardest on (S3 amendment C1-2,
docs/scratch/080-overnight/s3-codex-advisor-panel-s3-constraints.md):

- tiered rows (rail glyph on TTY, tier WORD on piped) — test_parity_stream_
  ticks.py content-checks this but never byte-locks it
- tick drill-down (single tick and range forms) — the ``_tick``/``_tick_error``
  branches, unreachable from any live CLI wiring today (S7 relocated ticks
  under ``store ticks``, drilled through ``fold_view`` instead of ``stream_
  view``) but still live code this migration will touch
- ``--id`` single-fact lookup (forces the FULL graft regardless of zoom)
- the ontology honesty callout (SPEC §9.2/§9.5)
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.stream import stream_view

from .fixtures import (
    SAMPLE_STREAM_ID_LOOKUP,
    SAMPLE_STREAM_ONTOLOGY_NOTICE,
    SAMPLE_STREAM_TICK_DRILL,
    SAMPLE_STREAM_TICK_ERROR,
    SAMPLE_STREAM_TICK_RANGE,
    SAMPLE_STREAM_TIERED,
)
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_tiered_tty(golden, zoom):
    """Rail glyph gutter (◆ high-tier, blank untiered) on the TTY register."""
    block = stream_view(SAMPLE_STREAM_TIERED, zoom, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_tiered_piped(golden, zoom):
    """Tier WORD column (``high``/``untiered``) on the piped ledger."""
    block = stream_view(SAMPLE_STREAM_TIERED, zoom, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_tick_drill(golden, zoom):
    """Single-tick drill-down: tick_drill_rows header, no vertex card."""
    block = stream_view(SAMPLE_STREAM_TICK_DRILL, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_tick_range_drill(golden):
    """Range drill-down (0:3 form): 'Ticks #N:M of T' + observer trigger list."""
    block = stream_view(SAMPLE_STREAM_TICK_RANGE, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_tick_error(golden):
    """Out-of-range tick drill — the plain error block, no facts rendered."""
    block = stream_view(SAMPLE_STREAM_TICK_ERROR, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_id_lookup(golden, zoom):
    """--id mode: id/observer/origin graft at every zoom that renders facts
    (SUMMARY/DETAILED/FULL — is_id_lookup forces rec_zoom=FULL for the record
    itself, which is why those three golden files come out byte-identical).
    MINIMAL has its own early-return (a plain count line) before the
    id-lookup branch is ever consulted, so it carries no graft."""
    block = stream_view(SAMPLE_STREAM_ID_LOOKUP, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_ontology_notice_tty(golden):
    """SPEC §9.2/§9.5 honesty callout — rendered above the rows, TTY
    register."""
    block = stream_view(
        SAMPLE_STREAM_ONTOLOGY_NOTICE, Zoom.SUMMARY, width=80, piped=False,
    )
    golden.assert_match(block_to_text(block), "output")


def test_ontology_notice_piped(golden):
    """Same callout on the piped register — stream_view recurses through the
    same code path regardless of ``piped``, but this exercises it rather
    than asserting it by comment."""
    block = stream_view(
        SAMPLE_STREAM_ONTOLOGY_NOTICE, Zoom.SUMMARY, width=None, piped=True,
    )
    golden.assert_match(block_to_text(block), "output")
