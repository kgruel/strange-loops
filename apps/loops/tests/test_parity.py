"""Channel-parity tests for the register-split lenses.

These are the regression harness for ``friction:register-split-piped-
faithfulness-untested`` — the class of bug where the terse (piped/agent) and
rich (TTY/human) registers of a lens silently disagree on load-bearing content
because each is tested in isolation. See ``parity.py`` for the invariant and
``tests/README.md`` for the adoption note.

Each test builds one representative fetch dict and asserts both registers carry
the same load-bearing tokens (and that the piped channel never truncates).
"""

from __future__ import annotations

import time


from loops.lenses.declarations import declarations_view, kind_stat_view
from loops.lenses.store import stats_view, store_view
from loops.lenses.vertices import vertices_view

from .parity import (
    assert_register_parity,
    assert_render_carries,
    decl_header_tokens,
    kind_stat_tokens,
    ls_root_tokens,
    vrow,
)

# A fixed-ish "recent" mtime so the relative-time token is stable within a run
# (the extractor derives the expected token via the same helper, so absolute
# wall-clock drift never makes the test brittle).
_MTIME = time.time() - 3 * 3600  # ~3h ago


# ---------------------------------------------------------------------------
# sl ls  (root) — vertices_view
# ---------------------------------------------------------------------------


class TestLsRootParity:
    def test_local_and_config_rows(self):
        data = {
            "local_vertices": [
                vrow("project", facts=1523, kind_count=8, mtime=_MTIME,
                     preview=["decision", "thread", "task"]),
            ],
            "vertices": [
                vrow("meta", facts=94, kind_count=5, mtime=_MTIME - 86400,
                     preview=["decision", "observation"]),
            ],
            "expand_config": True,
        }
        assert_register_parity(
            vertices_view, data, load_bearing=ls_root_tokens(data)
        )

    def test_narrow_pipe_does_not_clip_preview(self):
        # A long name + long preview: at a narrow piped width the TTY row would
        # elide the ⊃ preview, but the piped register must force width=None and
        # carry it in full. This is the exact shape of the shipped ls line-row
        # break (ctx.width inherits COLUMNS≈80).
        data = {
            "local_vertices": [
                vrow("agent-attestation", facts=812, kind_count=9, mtime=_MTIME,
                     preview=["decision", "thread", "observation"]),
            ],
            "vertices": [],
        }
        assert_register_parity(
            vertices_view, data, load_bearing=ls_root_tokens(data),
            piped_width=32,
        )

    def test_aggregation_row(self):
        data = {
            "local_vertices": [],
            "vertices": [
                vrow("root", vtype="aggregation", mtime=_MTIME,
                     combine=["a", "b", "c"]),
            ],
        }
        # Aggregation size cell is "combines 3" on both registers.
        assert_register_parity(
            vertices_view, data,
            load_bearing=["root", "combines 3"],
        )


# ---------------------------------------------------------------------------
# sl ls <vertex> — declarations_view (header + kinds table)
# ---------------------------------------------------------------------------


def _decl_data() -> dict:
    return {
        "vertex_name": "project",
        "vertex_kind": "instance",
        "facts": 1523,
        "kind_count": 3,
        "mtime": _MTIME,
        "signed": [1200, 1523],
        "observers": [{"name": "kyle"}, {"name": "alcove"}],
        "combine": [],
        "sources": [],
        "kinds": [
            {"name": "decision", "fold_op": 'by "topic"', "count": 800,
             "share": 52.5, "latest": _MTIME, "trend": [1, 2, 3, 4, 5, 6, 7, 8]},
            {"name": "thread", "fold_op": 'by "name"', "count": 500,
             "share": 32.8, "latest": _MTIME, "trend": [2, 3, 2, 5, 6, 1, 0, 4]},
            {"name": "observation", "fold_op": 'by "topic"', "count": 223,
             "share": 14.6, "latest": _MTIME, "trend": [1, 1, 2, 3, 2, 0, 0, 5]},
        ],
    }


class TestLsVertexParity:
    def test_header_and_kinds(self):
        data = _decl_data()
        assert_register_parity(
            declarations_view, data, load_bearing=decl_header_tokens(data)
        )

    def test_signed_ratio_on_both_registers(self):
        # signed is data, not chrome — a prior bug dropped it from the piped
        # header. Assert it survives both channels explicitly.
        data = _decl_data()
        assert_register_parity(
            declarations_view, data, load_bearing=["signed 1.2k/1.5k"]
        )

    def test_end_to_end_over_real_store(self, loops_home):
        # End-to-end: exercise the real fetch → lens pipeline (not a hand-built
        # dict) so a fetch path that drops a field on one channel is caught.
        from engine.builder import fold_by, fold_collect, vertex

        from loops.commands.ls import fetch_declarations

        from .builders import emit_fact

        vdir = loops_home / "e2eproj"
        vdir.mkdir(parents=True, exist_ok=True)
        vpath = vdir / "e2eproj.vertex"
        (
            vertex("e2eproj")
            .store("./data/e2eproj.db")
            .loop("decision", fold_by("topic"))
            .loop("thread", fold_by("name"))
            .loop("log", fold_collect("items", max_items=20))
            .write(vpath)
        )
        emit_fact(vpath, "decision", topic="design/a", message="one")
        emit_fact(vpath, "decision", topic="arch/x", message="two")
        emit_fact(vpath, "thread", name="wrap", status="open")

        data = fetch_declarations("e2eproj")
        assert "error" not in data
        assert data["facts"] == 3
        assert_register_parity(
            declarations_view, data, load_bearing=decl_header_tokens(data)
        )


# ---------------------------------------------------------------------------
# sl ls <vertex> --kind K — kind_stat_view
# ---------------------------------------------------------------------------


def _kind_stat_data() -> dict:
    return {
        "kind": "decision",
        "fold_op": "by topic",
        "by": "key",
        "key_field": "topic",
        "count": 800,
        "share": 52.5,
        "vertex_name": "project",
        "distinct_keys": 4,
        "earliest": _MTIME - 30 * 86400,
        "latest": _MTIME,
        "entries": [
            {"key": "design/", "count": 300, "latest": _MTIME, "leaf": False},
            {"key": "architecture/", "count": 240, "latest": _MTIME, "leaf": False},
            {"key": "rendering/", "count": 160, "latest": _MTIME, "leaf": False},
            {"key": "paradigm/", "count": 100, "latest": _MTIME, "leaf": False},
        ],
    }


class TestLsKindParity:
    def test_share_span_entries(self):
        data = _kind_stat_data()
        assert_register_parity(
            kind_stat_view, data, load_bearing=kind_stat_tokens(data)
        )

    def test_share_of_vertex_on_both(self):
        # share % + "of <vertex>" shipped a piped-faithfulness bug.
        data = _kind_stat_data()
        assert_register_parity(
            kind_stat_view, data, load_bearing=["52.5% of project"]
        )


# ---------------------------------------------------------------------------
# sl store stats --by-kind — plain vs --json parity (single register)
# ---------------------------------------------------------------------------


class TestStoreStatsJsonParity:
    def test_plain_carries_json_dict_tokens(self):
        # stats_view is not register-split, but plain-vs-json is the same bug
        # class (--json serialises the dict; plain must carry the same facts).
        data = {
            "vertex": "project",
            "by_kind": True,
            "total_facts": 1523,
            "total_ticks": 42,
            "kind_count": 3,
            "kinds": [
                {"kind": "decision", "count": 800},
                {"kind": "thread", "count": 500},
                {"kind": "observation", "count": 223},
            ],
        }
        load_bearing = [
            "project", "1.5k facts", "3 kinds", "42 ticks",
            "decision", "800", "thread", "500", "observation", "223",
        ]
        assert_render_carries(stats_view, data, load_bearing=load_bearing)


# ---------------------------------------------------------------------------
# sl store / sl store stats — register parity (piped forces width=None)
# ---------------------------------------------------------------------------
# Regression: both callsites passed ctx.width (always an int) into the lens
# with no register split, so a pipe inheriting COLUMNS clipped the agent
# channel — the class assert_register_parity exists for.


def _store_summary_data():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    long_title = "a substrate-defining announcement headline that overflows"
    return {
        "vertex": "project",
        "facts": {
            "total": 642,
            "kinds": {
                "decision": {
                    "count": 420,
                    "earliest": now - timedelta(days=30),
                    "latest": now - timedelta(hours=1),
                    "sample_payload": {"message": long_title},
                },
                "thread": {
                    "count": 222,
                    "earliest": now - timedelta(days=20),
                    "latest": now - timedelta(minutes=30),
                },
            },
        },
        "ticks": {"total": 15, "names": {}},
    }


class TestStoreViewRegisterParity:
    def test_summary_parity(self):
        assert_register_parity(
            store_view,
            _store_summary_data(),
            load_bearing=[
                "decision", "420", "thread", "222",
                # the long gist is what a COLUMNS-clipped pipe used to drop
                "a substrate-defining announcement headline that overflows",
            ],
        )

    def test_full_parity(self):
        from painted import Zoom

        assert_register_parity(
            store_view,
            _store_summary_data(),
            zoom=Zoom.FULL,
            load_bearing=[
                "decision", "420", "thread", "222",
                "2 kinds", "642 facts",  # border-title topline must survive piped
                "a substrate-defining announcement headline that overflows",
            ],
        )


class TestStatsViewRegisterParity:
    def test_by_kind_parity(self):
        data = {
            "vertex": "project",
            "by_kind": True,
            "total_facts": 1523,
            "total_ticks": 42,
            "kind_count": 3,
            "kinds": [
                {"kind": "decision", "count": 800},
                {"kind": "a-very-long-kind-name-that-would-clip", "count": 500},
                {"kind": "observation", "count": 223},
            ],
        }
        assert_register_parity(
            stats_view,
            data,
            load_bearing=[
                "project", "1.5k facts", "3 kinds", "42 ticks",
                "decision", "800",
                "a-very-long-kind-name-that-would-clip", "500",
            ],
        )
