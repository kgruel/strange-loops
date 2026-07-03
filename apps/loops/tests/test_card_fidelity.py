"""Card fidelity-policy tests (spine G5).

Pins the ratified fidelity policy (4a = B, decision:design/spine-options-
ratified): the TTY header card renders at SUMMARY and above, is ABSENT at
MINIMAL (``-q`` stays a bare one-liner for embedding), and is ABSENT on the
piped channel (chrome never ships on the agent pipe — the information rides the
plain header lines instead).

Also extends register-parity to ``fold_view``: the card adds no fetched
information the piped ledger lacks (counts are per-kind aggregates already on
the ``## KIND (N)`` headers; the vertex name is the query context, not fetched
content), so both registers still carry the same load-bearing tokens.
"""

from __future__ import annotations

from painted import Zoom

from loops.lenses.fold import fold_view
from loops.lenses.store import tick_chain_view
from loops.lenses.stream import stream_view

from .golden.fixtures import SAMPLE_FOLD, SAMPLE_STREAM
from .helpers import block_to_text
from .parity import assert_register_parity

_CARD_TOP = "╭"


def _text(block) -> str:
    return block_to_text(block)


CHAIN_DATA = {
    "vertex": "demo",
    "chain_mode": False,
    "chain": {},
    "windows": [
        {
            "ts": 1736935920.0,
            "index": 0,
            "boundary_trigger": "session end",
            "items": 5,
            "facts": 12,
            "added": 12,
            "updated": 0,
        },
    ],
}


class TestFoldCardFidelity:
    def test_card_present_at_summary_tty(self):
        out = _text(fold_view(SAMPLE_FOLD, Zoom.SUMMARY, 80, piped=False))
        assert _CARD_TOP in out
        assert "session · fold" in out

    def test_card_absent_at_minimal(self):
        out = _text(fold_view(SAMPLE_FOLD, Zoom.MINIMAL, 80, piped=False))
        assert _CARD_TOP not in out

    def test_card_absent_when_piped(self):
        out = _text(fold_view(SAMPLE_FOLD, Zoom.SUMMARY, None, piped=True))
        assert _CARD_TOP not in out

    def test_register_parity(self):
        # fold_view is register-split; the card adds no piped-exclusive fetched
        # info, so both channels still carry the shared kind/key tokens.
        assert_register_parity(
            fold_view, SAMPLE_FOLD,
            load_bearing=[
                "Use SQLite for persistence", "KDL for config format",
                "vertex-routing", "implement fold",
            ],
        )


class TestStreamCardFidelity:
    def test_card_present_at_summary_tty(self):
        out = _text(stream_view(SAMPLE_STREAM, Zoom.SUMMARY, 80, piped=False))
        assert _CARD_TOP in out
        assert "session · stream" in out

    def test_card_absent_at_minimal(self):
        out = _text(stream_view(SAMPLE_STREAM, Zoom.MINIMAL, 80, piped=False))
        assert _CARD_TOP not in out

    def test_card_absent_when_piped(self):
        out = _text(stream_view(SAMPLE_STREAM, Zoom.SUMMARY, None, piped=True))
        assert _CARD_TOP not in out


class TestTickChainCardFidelity:
    def test_card_present_at_summary_tty(self):
        out = _text(tick_chain_view(CHAIN_DATA, Zoom.SUMMARY, 80, piped=False))
        assert _CARD_TOP in out
        assert "demo · ticks" in out

    def test_card_absent_at_minimal(self):
        out = _text(tick_chain_view(CHAIN_DATA, Zoom.MINIMAL, 80, piped=False))
        assert _CARD_TOP not in out

    def test_card_absent_when_piped(self):
        out = _text(tick_chain_view(CHAIN_DATA, Zoom.SUMMARY, 80, piped=True))
        assert _CARD_TOP not in out
        # The rollup header still carries vertex + tick count on the pipe.
        info = _text(tick_chain_view(CHAIN_DATA, Zoom.SUMMARY, 80, piped=True))
        assert "demo" in info and "1 ticks" in info
