"""Cursor rendering — mode-line (text) + machine-readable field (JSON), 0.8.0 C1/A11.

Dispatch-level: exercises the render_context["cursor"] contract directly
against a hand-built FoldState via ``dispatch()`` — no store/vertex needed,
since this is purely about the render/JSON plumbing (cli.views.fold's
resolution of --at/--as-of into a WitnessPosition is covered separately,
end-to-end, in test_fold_view_cursor.py).

Guards: cursor=None (every pre-0.8.0 caller) must render byte-identical to
before (golden tests already lock this); cursor set must prepend the mode
line in text and merge a "cursor" key into JSON, in both gate-pass (Surface)
and gate-fail (raw dump) JSON shapes.
"""

from __future__ import annotations

import json

from painted.cli import Format

from atoms import FoldItem, FoldSection, FoldState
from loops.cli.dispatch import dispatch
from loops.cli.operation import Operation
from loops.cli.output import BufferReporter

from .golden.helpers import block_to_text


def _state() -> FoldState:
    return FoldState(
        sections=(
            FoldSection(
                kind="decision",
                items=(
                    FoldItem(payload={"topic": "a", "message": "alpha"}, ts=100.0),
                ),
                fold_type="by",
                key_field="topic",
            ),
        ),
        vertex="t",
    )


_WITNESS_CURSOR = {
    "mode": "witness",
    "address": "head",
    "status": "file-pre-genesis",
    "fact_id": "01JFACTID000000000000000000",
    "seq": 3,
    "unadopted": True,
    "lineage": None,
    "anchor": None,
}

_AS_OF_CURSOR = {
    "mode": "as_of",
    "address": "30d",
    "status": "file-pre-genesis",
    "as_of": 1720000000.0,
}


class TestTextModeLine:
    def test_witness_mode_line_prepended(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold",
            render_context={"cursor": _WITNESS_CURSOR},
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        text = block_to_text(reporter.blocks[0])
        assert "witness cursor" in text
        assert "01JFACTID000000000000000000" in text
        assert "seq 3" in text
        assert "unadopted store" in text
        # file-pre-genesis status renders its honesty notice too.
        assert "ontology" in text and "current file" in text

    def test_as_of_mode_line_prepended(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold",
            render_context={"cursor": _AS_OF_CURSOR},
        )
        reporter = BufferReporter()
        dispatch(op, reporter=reporter)
        text = block_to_text(reporter.blocks[0])
        assert "event-time projection" in text

    def test_store_status_has_no_ontology_notice(self):
        cursor = {**_WITNESS_CURSOR, "status": "store", "unadopted": False}
        op = Operation(
            verb="read", fn=_state, render_lens="fold",
            render_context={"cursor": cursor},
        )
        reporter = BufferReporter()
        dispatch(op, reporter=reporter)
        text = block_to_text(reporter.blocks[0])
        assert "witness cursor" in text
        assert "⚠ ontology" not in text


class TestJsonCursorField:
    def test_gate_pass_json_carries_cursor(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
            render_context={"cursor": _WITNESS_CURSOR},
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        payload = json.loads(reporter.out_lines[0])
        assert "rows" in payload  # the Surface (gate-pass) shape
        assert payload["cursor"] == _WITNESS_CURSOR

    def test_gate_fail_json_carries_cursor(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
            lens_override="autoresearch",  # resolvable, != built-in → gate fails
            render_context={"cursor": _AS_OF_CURSOR},
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        payload = json.loads(reporter.out_lines[0])
        # Non-dict gate-fail data (a raw FoldState) wraps under "data"
        # alongside the merged extras — no top level to merge into directly.
        assert "sections" in payload["data"]
        assert payload["cursor"] == _AS_OF_CURSOR

    def test_no_cursor_key_omits_field(self):
        op = Operation(
            verb="read", fn=_state, render_lens="fold", format=Format.JSON,
        )
        reporter = BufferReporter()
        dispatch(op, reporter=reporter)
        payload = json.loads(reporter.out_lines[0])
        assert "cursor" not in payload
