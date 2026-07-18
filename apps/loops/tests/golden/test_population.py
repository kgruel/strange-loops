"""Golden coverage for ``vertices_view`` over ``_run_ls_root``'s real fetch
shape (``sl ls`` — the "population" surface, S3 amendment C1-2).

test_grammar_parity.py already byte-goldens ``vertices_view`` as "ls-root",
but only over a single vertex (no local/config layering, no shadowing, no
aggregation/hybrid vertex, no ``--all``/``-1`` toggles) — the shape
``_run_ls_root`` actually assembles in commands/population.py. This file
locks the fuller shape directly against the fixture dict (no store needed,
matching every other golden in this directory).
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.vertices import vertices_view

from .fixtures import SAMPLE_LS_ROOT
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_ls_root_tty(golden, zoom):
    """Default: local layer stat'd, config collapsed to a count-line hint."""
    block = vertices_view(SAMPLE_LS_ROOT, zoom, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_ls_root_piped(golden, zoom):
    block = vertices_view(SAMPLE_LS_ROOT, zoom, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_ls_root_expanded_tty(golden):
    """--all: config layer expands past the count-line into full stat rows."""
    data = {**SAMPLE_LS_ROOT, "expand_config": True}
    block = vertices_view(data, Zoom.DETAILED, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_ls_root_expanded_piped(golden):
    data = {**SAMPLE_LS_ROOT, "expand_config": True}
    block = vertices_view(data, Zoom.DETAILED, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_ls_root_terse(golden):
    """-1: names-only listing, local then config, no stats."""
    data = {**SAMPLE_LS_ROOT, "terse": True}
    block = vertices_view(data, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")
