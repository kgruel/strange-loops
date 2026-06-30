"""Tests for `sl ls <vertex> --kind <K>` — the kind stat view.

decision:design/ls-as-stat-over-containment reverses decision-B: ``--kind``
descends one containment level (to the kind's *entries* — fold-key namespaces /
leaf keys / observers), as a stat view, and no longer aliases to ``read``.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest
from engine.builder import fold_by, fold_collect, vertex
from loops.commands.ls import (
    _rollup_entries,
    _run_kind_stat,
    detect_kind_descent,
    fetch_kind_stat,
)
from loops.main import cmd_emit


def _dt(day: int) -> datetime:
    return datetime(2026, 1, day, tzinfo=timezone.utc)


def _raw(spec: dict) -> dict:
    """{key: count} → the {key: {count, earliest, latest}} shape fact_key_stats
    returns. latest is staggered by count so ordering is deterministic."""
    return {
        k: {"count": c, "earliest": _dt(1), "latest": _dt(c + 1)}
        for k, c in spec.items()
    }


# ---------------------------------------------------------------------------
# _rollup_entries — the pure namespace/leaf rollup
# ---------------------------------------------------------------------------


class TestRollupEntries:
    def test_rolls_namespaces_to_next_level(self):
        raw = _raw({"design/a": 2, "design/b": 1, "arch/x": 1, "flat": 1})
        by = {e["key"]: e for e in _rollup_entries(raw, None, "topic")}
        assert by["design/"]["count"] == 3
        assert by["design/"]["leaf"] is False  # namespace — drillable
        assert by["arch/"]["count"] == 1
        assert by["flat"]["leaf"] is True       # bare key — a leaf

    def test_orphan_bucket_at_top_level(self):
        raw = _raw({"design/a": 1})
        raw[None] = {"count": 3, "earliest": _dt(1), "latest": _dt(2)}
        by = {e["key"]: e for e in _rollup_entries(raw, None, "topic")}
        assert by["(no topic)"]["count"] == 3

    def test_drill_strips_to_subtree_and_excludes_orphan(self):
        raw = _raw({"design/a": 2, "design/sub/x": 1, "arch/y": 1})
        raw[None] = {"count": 9, "earliest": _dt(1), "latest": _dt(2)}
        keys = {e["key"] for e in _rollup_entries(raw, "design/", "topic")}
        assert "design/a" in keys        # leaf under the prefix
        assert "design/sub/" in keys     # a deeper namespace under the prefix
        assert "arch/y" not in keys      # outside the prefix
        assert "(no topic)" not in keys  # orphans aren't under any prefix

    def test_count_descending(self):
        raw = _raw({"a/": 1, "b/": 5, "c/": 3})
        counts = [e["count"] for e in _rollup_entries(raw, None, "topic")]
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# fetch_kind_stat — integration over a real emitted store
# ---------------------------------------------------------------------------


@pytest.fixture
def statproj(loops_home) -> Path:
    """A vertex with a by-topic decision kind and a collect log kind."""
    vdir = loops_home / "statproj"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "statproj.vertex"
    (
        vertex("statproj")
        .store("./data/statproj.db")
        .loop("decision", fold_by("topic"))
        .loop("log", fold_collect("items", max_items=50))
        .write(vpath)
    )

    def emit(kind, **payload):
        parts = [f"{k}={v}" for k, v in payload.items()]
        ns = argparse.Namespace(
            vertex=None, kind=kind, parts=parts, observer="", dry_run=False
        )
        assert cmd_emit(ns, vertex_path=vpath) == 0

    emit("decision", topic="design/a", message="one")
    emit("decision", topic="design/b", message="two")
    emit("decision", topic="arch/x", message="three")
    emit("decision", message="orphan — no topic")  # orphan
    emit("log", message="r1")
    emit("log", message="r2")
    return vpath


class TestFetchKindStat:
    def test_namespace_rollup_and_orphan(self, statproj):
        data = fetch_kind_stat("statproj", "decision")
        assert data["by"] == "key"
        assert data["key_field"] == "topic"
        by = {e["key"]: e for e in data["entries"]}
        assert by["design/"]["count"] == 2
        assert by["arch/"]["count"] == 1
        assert by["(no topic)"]["count"] == 1
        assert data["count"] == 4  # whole kind

    def test_drill_scopes_header_and_entries(self, statproj):
        data = fetch_kind_stat("statproj", "decision", key_prefix="design/")
        assert data["key_prefix"] == "design/"
        assert data["count"] == 2  # subtree, not the whole kind
        keys = {e["key"] for e in data["entries"]}
        assert keys == {"design/a", "design/b"}
        assert "(no topic)" not in keys

    def test_collect_fold_degrades_to_observer(self, statproj):
        data = fetch_kind_stat("statproj", "log")
        assert data["by"] == "observer"
        assert data["key_field"] is None
        assert data["count"] == 2

    def test_key_on_collect_fold_errors(self, statproj):
        """--key on a keyless kind is rejected, not silently ignored."""
        data = fetch_kind_stat("statproj", "log", key_prefix="foo/")
        assert "error" in data
        assert "collect-fold" in data["error"]

    def test_timestamps_are_epoch_floats(self, statproj):
        """--json contract: latest/earliest are epoch floats (like read/listing),
        not datetimes (which serialise as non-ISO strings)."""
        data = fetch_kind_stat("statproj", "decision")
        assert isinstance(data["latest"], float)
        assert isinstance(data["earliest"], float)
        assert all(isinstance(e["latest"], float) for e in data["entries"])

    def test_missing_vertex_errors(self, loops_home):
        # An unresolvable vertex surfaces an error inline, not a crash.
        data = fetch_kind_stat("does-not-exist", "decision")
        assert "error" in data


# ---------------------------------------------------------------------------
# Render robustness — the rich TTY tables honour the width budget
# ---------------------------------------------------------------------------


class TestTableHonoursWidth:
    def _kinds(self):
        return [
            {"name": "decision", "fold_op": "by topic", "count": 800, "share": 47.0,
             "latest": None, "trend": [1, 2, 3, 4, 5, 6, 7, 8]},
            {"name": "thread", "fold_op": "by name", "count": 500, "share": 29.4,
             "latest": None, "trend": [2, 3, 2, 5, 6, 1, 0, 4]},
            {"name": "observation", "fold_op": "by topic", "count": 403, "share": 23.6,
             "latest": None, "trend": [1, 1, 2, 3, 2, 0, 0, 5]},
        ]

    def test_kind_table_fits_common_widths(self):
        from loops.lenses._statview import palette_of
        from loops.lenses.declarations import _kind_table
        p = palette_of(None)
        for w in (53, 60, 70, 80, 120):
            assert _kind_table(self._kinds(), w, p).width <= w, f"overflow at {w}"

    def test_entry_table_fits_common_widths(self):
        from loops.lenses._statview import palette_of
        from loops.lenses.declarations import _entry_table
        p = palette_of(None)
        data = {
            "by": "key", "count": 100, "kind": "decision", "vertex_name": "proj",
            "entries": [
                {"key": "design/credential-is-grant-in-envelope", "count": 40,
                 "latest": None, "leaf": True},
                {"key": "arch/", "count": 30, "latest": None, "leaf": False},
            ],
        }
        for w in (44, 60, 80, 120):
            assert _entry_table(data, w, p)[0].width <= w, f"overflow at {w}"


# ---------------------------------------------------------------------------
# Dispatch reversal — `--kind VALUE` routes to the stat view, not to read
# ---------------------------------------------------------------------------


class TestDispatchReversal:
    def test_descent_recognised(self):
        descent = detect_kind_descent(["statproj", "--kind", "decision"])
        assert descent == ("statproj", "decision", [])

    def test_bare_kind_is_not_a_descent(self):
        # Bare --kind (no value) stays on the listing path.
        assert detect_kind_descent(["statproj", "--kind"]) is None

    def test_kind_value_renders_stat_view_not_facts(self, statproj, capsys):
        rc = _run_kind_stat("statproj", "decision", [])
        out = capsys.readouterr().out
        assert rc == 0
        # The stat view lists fold-key entries (the namespace rollup), not the
        # decision fact bodies.
        assert "design/" in out
        assert "one" not in out  # the fact message body must NOT appear
