"""Golden coverage for ``kind_stat_view`` (``ls <vertex> --kind <kind>``).

test_grammar_parity.py already byte-goldens this lens (as "ls-kind") over a
real store fixture. This file locks it independent of that store-fixture
builder, plus the ``--key <prefix>`` narrowing view the store-fixture golden
doesn't exercise (S3 amendment C1-2 — ls was among the surfaces the panel
found under-covered relative to the migration's blast radius).
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.declarations import kind_stat_view

from .fixtures import SAMPLE_KIND_STAT, SAMPLE_KIND_STAT_DRILLED
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_kind_stat_tty(golden, zoom):
    block = kind_stat_view(SAMPLE_KIND_STAT, zoom, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_kind_stat_piped(golden, zoom):
    block = kind_stat_view(SAMPLE_KIND_STAT, zoom, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_kind_stat_drilled_tty(golden):
    """--key design/ narrowing — the 'under design/' card subline."""
    block = kind_stat_view(SAMPLE_KIND_STAT_DRILLED, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_kind_stat_drilled_piped(golden):
    block = kind_stat_view(
        SAMPLE_KIND_STAT_DRILLED, Zoom.SUMMARY, width=None, piped=True,
    )
    golden.assert_match(block_to_text(block), "output")
