"""Golden coverage for ``sync_view`` — previously guarded by NO byte golden at
all (S3 amendment C1-2: stream/ticks/ls/sync/population had none before S0).

``sync_view`` has no ``piped`` kwarg — it is not a register-split lens, it
just honours whatever ``width`` its caller passes (``commands/sync.py``'s
renderer threads painted's offered width straight through, so piped ⇒
width=None already, per the run_cli offered-width ratchet in
``apps/loops/tests/test_architecture.py``). Both width=80 and width=None are
locked here so a future refactor can't silently reintroduce a hardcoded
width for either register.

Skip lines render ages through ``_grammar.recency``, which reads the wall
clock, so old fixture timestamps alone do not make this deterministic — the
clock is pinned below, at the same ``_grammar`` seam ``test_grammar_parity``
pins. (Before the 010 fork consolidation the lens carried its own
``_format_ago``/``_format_interval`` ladder and the pin was lens-local.)
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.sync import sync_view

from .fixtures import (
    REF_TS,
    SAMPLE_SYNC_AGGREGATION,
    SAMPLE_SYNC_EMPTY,
    SAMPLE_SYNC_INSTANCE,
)
from .helpers import block_to_text

# A few minutes after the freshest "skipped" timestamp in the fixtures, so
# recency() renders stable, small, positive "Nm" spans.
_FIXED_NOW = REF_TS + 300


@pytest.fixture(autouse=True)
def _pin_clock(monkeypatch):
    monkeypatch.setattr("loops.lenses._grammar.time.time", lambda: _FIXED_NOW)


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_instance_tty(golden, zoom):
    block = sync_view(SAMPLE_SYNC_INSTANCE, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_instance_piped(golden, zoom):
    block = sync_view(SAMPLE_SYNC_INSTANCE, zoom, width=None)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_aggregation_tty(golden, zoom):
    block = sync_view(SAMPLE_SYNC_AGGREGATION, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_aggregation_piped(golden, zoom):
    block = sync_view(SAMPLE_SYNC_AGGREGATION, zoom, width=None)
    golden.assert_match(block_to_text(block), "output")


def test_nothing_configured(golden):
    block = sync_view(SAMPLE_SYNC_EMPTY, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")
