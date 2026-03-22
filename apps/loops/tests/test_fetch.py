"""Tests for commands/fetch.py — duration parsing, key splitting, fold/stream fetch."""

import pytest
from loops.commands.fetch import (
    _fact_matches_key,
    _get_key_field,
    _item_matches_key,
    _parse_duration,
    _split_kind_key,
)


class TestParseDuration:
    def test_days(self):
        assert _parse_duration("7d") == 7 * 86400

    def test_hours(self):
        assert _parse_duration("24h") == 24 * 3600

    def test_minutes(self):
        assert _parse_duration("30m") == 30 * 60

    def test_seconds(self):
        assert _parse_duration("60s") == 60

    def test_invalid(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            _parse_duration("5x")


class TestSplitKindKey:
    def test_no_key(self):
        kind, key = _split_kind_key("heartbeat")
        assert kind == "heartbeat"
        assert key is None

    def test_with_key(self):
        kind, key = _split_kind_key("thread/fix-bug")
        assert kind == "thread"
        assert key == "fix-bug"

    def test_none(self):
        kind, key = _split_kind_key(None)
        assert kind is None
        assert key is None

    def test_slashed_key(self):
        kind, key = _split_kind_key("decision/design/api")
        assert kind == "decision"
        assert key == "design/api"


class TestKeyMatchingHelpers:
    def test_item_matches_key_field_case_insensitive(self):
        from atoms import FoldItem
        item = FoldItem(payload={"service": "API"}, ts=1.0)
        assert _item_matches_key(item, "service", "api") is True

    def test_item_matches_fallback_name(self):
        from atoms import FoldItem
        item = FoldItem(payload={"name": "deploy"}, ts=1.0)
        assert _item_matches_key(item, None, "DEPLOY") is True

    def test_fact_matches_key_field_case_insensitive(self):
        fact = {"payload": {"service": "API"}}
        assert _fact_matches_key(fact, "service", "api") is True

    def test_fact_matches_fallback_topic(self):
        fact = {"payload": {"topic": "design/api"}}
        assert _fact_matches_key(fact, None, "design/api") is True


class TestGetKeyField:
    def test_fold_by_kind(self, tmp_path):
        from engine.builder import vertex, fold_by
        vpath = tmp_path / "t.vertex"
        vertex("t").store("./t.db").loop("metric", fold_by("service")).write(vpath)
        assert _get_key_field(vpath, "metric") == "service"

    def test_non_fold_by_kind(self, tmp_path):
        from engine.builder import vertex, fold_count
        vpath = tmp_path / "t.vertex"
        vertex("t").store("./t.db").loop("ping", fold_count("n")).write(vpath)
        assert _get_key_field(vpath, "ping") is None


class TestFetchIntegration:
    def test_fetch_fold_basic(self, tmp_path):
        from engine.builder import fold_by, vertex
        from loops.commands.fetch import fetch_fold

        b = vertex("t").store("./t.db").loop("metric", fold_by("service"))
        b.write(tmp_path / "t.vertex")

        from loops.main import cmd_emit
        import argparse
        for svc in ["api", "web"]:
            cmd_emit(argparse.Namespace(
                vertex=None, kind="metric", parts=[f"service={svc}", "val=1"],
                observer="", dry_run=False,
            ), vertex_path=tmp_path / "t.vertex")

        state = fetch_fold(tmp_path / "t.vertex")
        assert state is not None
        assert state.vertex == "t"

    def test_fetch_fold_kind_key_filter(self, tmp_path):
        from engine.builder import fold_by, vertex
        from loops.commands.fetch import fetch_fold
        from loops.main import cmd_emit
        import argparse

        vpath = tmp_path / "t.vertex"
        vertex("t").store("./t.db").loop("metric", fold_by("service")).write(vpath)
        for svc in ["api", "web", "api"]:
            cmd_emit(argparse.Namespace(
                vertex=None, kind="metric", parts=[f"service={svc}", "val=1"],
                observer="", dry_run=False,
            ), vertex_path=vpath)

        state = fetch_fold(vpath, kind="metric/api")
        assert len(state.sections) == 1
        assert state.sections[0].kind == "metric"
        assert all(item.payload["service"] == "api" for item in state.sections[0].items)

    def test_fetch_stream_basic(self, tmp_path):
        from engine.builder import fold_count, vertex
        from loops.commands.fetch import fetch_stream

        b = vertex("t").store("./t.db").loop("ping", fold_count("n"))
        b.write(tmp_path / "t.vertex")

        from loops.main import cmd_emit
        import argparse
        cmd_emit(argparse.Namespace(
            vertex=None, kind="ping", parts=["x=1"],
            observer="", dry_run=False,
        ), vertex_path=tmp_path / "t.vertex")

        result = fetch_stream(tmp_path / "t.vertex")
        assert isinstance(result, dict)
        assert "facts" in result
        assert len(result["facts"]) >= 1
        assert result["vertex"] == "t"
        assert "ping" in result["fold_meta"]

    def test_fetch_stream_kind_key_filter(self, tmp_path):
        from engine.builder import fold_by, vertex
        from loops.commands.fetch import fetch_stream
        from loops.main import cmd_emit
        import argparse

        vpath = tmp_path / "t.vertex"
        vertex("t").store("./t.db").loop("metric", fold_by("service")).write(vpath)
        for svc in ["api", "web", "api"]:
            cmd_emit(argparse.Namespace(
                vertex=None, kind="metric", parts=[f"service={svc}", "val=1"],
                observer="", dry_run=False,
            ), vertex_path=vpath)

        result = fetch_stream(vpath, kind="metric/api")
        assert len(result["facts"]) >= 1
        assert all(f["payload"]["service"] == "api" for f in result["facts"])

    def test_fetch_stream_query_path(self, tmp_path):
        from engine.builder import fold_collect, vertex
        from loops.commands.fetch import fetch_stream
        from loops.main import cmd_emit
        import argparse

        vpath = tmp_path / "t.vertex"
        vertex("t").store("./t.db").loop("event", fold_collect("items", max_items=100), search=["message"]).write(vpath)
        cmd_emit(argparse.Namespace(
            vertex=None, kind="event", parts=["message=deploy api"],
            observer="", dry_run=False,
        ), vertex_path=vpath)
        cmd_emit(argparse.Namespace(
            vertex=None, kind="event", parts=["message=other"],
            observer="", dry_run=False,
        ), vertex_path=vpath)

        result = fetch_stream(vpath, query="deploy")
        assert len(result["facts"]) >= 1
        assert any("deploy" in f["payload"].get("message", "") for f in result["facts"])


class TestFetchMissLines:
    """Targeted tests for remaining miss lines in commands/fetch.py."""

    def test_fetch_fold_key_filter_multi_kind_skips_section(self, tmp_path):
        """fetch_fold with key filter skips non-matching kind sections (L82)."""
        import argparse
        from engine.builder import fold_by, vertex
        from loops.commands.fetch import fetch_fold
        from loops.main import cmd_emit

        vpath = tmp_path / "t.vertex"
        # Two kinds: metric and event
        (vertex("t").store("./t.db")
            .loop("metric", fold_by("service"))
            .loop("event", fold_by("name"))
            .write(vpath))

        for args in [("metric", "service=api"), ("event", "name=deploy")]:
            cmd_emit(argparse.Namespace(
                vertex=None, kind=args[0], parts=[args[1]],
                observer="", dry_run=False,
            ), vertex_path=vpath)

        # kind="metric/api" → key_filter="api", kind_filter="metric"
        # The "event" section hits section.kind != "metric" → L82 (continue)
        result = fetch_fold(vpath, kind="metric/api")
        section_kinds = [s.kind for s in result.sections]
        assert "metric" in section_kinds
        assert "event" not in section_kinds

    def test_fetch_ticks_fold_collect_items_dict(self, tmp_path):
        """fetch_ticks with fold_collect vertex covers L246-247 (items dict path)."""
        import argparse
        from engine.builder import fold_collect, vertex
        from loops.commands.fetch import fetch_ticks
        from loops.main import cmd_emit

        vpath = tmp_path / "t.vertex"
        (vertex("t").store("./t.db")
            .loop("event", fold_collect("items", max_items=100), boundary_every=1)
            .write(vpath))

        # Emit facts to create ticks
        for i in range(2):
            cmd_emit(argparse.Namespace(
                vertex=None, kind="event", parts=[f"msg=e{i}"],
                observer="", dry_run=False,
            ), vertex_path=vpath)

        result = fetch_ticks(vpath)
        # fold_collect stores as {"items": [...]} → hits L246-247
        assert result is not None
