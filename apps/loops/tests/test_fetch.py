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


# ---------------------------------------------------------------------------
# TickWindow plumbing
# ---------------------------------------------------------------------------


class TestTickPayloadStats:
    """Density and per-key _n extraction from tick payloads."""

    def test_empty_payload(self):
        from loops.commands.fetch import _tick_payload_stats

        stats = _tick_payload_stats({})
        assert stats["total_items"] == 0
        assert stats["total_facts"] == 0
        assert stats["kind_counts"] == {}
        assert stats["kind_compression"] == {}
        assert stats["ref_count"] == 0
        assert stats["kind_items"] == {}

    def test_by_fold_single_kind(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {
            "decision": {
                "items": {
                    "auth": {"topic": "auth", "_n": 1},
                    "storage": {"topic": "storage", "_n": 3},
                },
            },
        }
        stats = _tick_payload_stats(payload)
        assert stats["total_items"] == 2
        assert stats["total_facts"] == 4  # 1 + 3
        assert stats["kind_counts"] == {"decision": 2}
        assert stats["kind_compression"] == {"decision": 2.0}
        assert stats["kind_items"]["decision"] == {"auth": 1, "storage": 3}

    def test_by_fold_defaults_missing_n_to_one(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {"thread": {"items": {"t1": {"name": "t1"}}}}
        stats = _tick_payload_stats(payload)
        assert stats["total_facts"] == 1
        assert stats["kind_items"]["thread"] == {"t1": 1}

    def test_collect_fold_has_empty_kind_items(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {
            "log": {"items": [{"message": "a"}, {"message": "b"}, {"message": "c"}]},
        }
        stats = _tick_payload_stats(payload)
        assert stats["kind_counts"] == {"log": 3}
        assert stats["total_items"] == 3
        assert stats["total_facts"] == 3
        # Collect-folds have no per-item identity
        assert stats["kind_items"]["log"] == {}

    def test_underscore_keys_ignored(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {
            "_boundary": {"name": "kyle", "status": "closed"},
            "_vertex_period_start": 999.0,
            "decision": {"items": {"auth": {"_n": 1}}},
        }
        stats = _tick_payload_stats(payload)
        assert stats["kind_counts"] == {"decision": 1}
        assert "_boundary" not in stats["kind_counts"]
        assert "_boundary" not in stats["kind_items"]

    def test_ref_count_counts_items_with_refs(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {
            "decision": {
                "items": {
                    "auth": {"_n": 1, "_refs": ["thread/loop"]},
                    "storage": {"_n": 1},
                    "ui": {"_n": 1, "_refs": ["decision/auth"]},
                },
            },
        }
        stats = _tick_payload_stats(payload)
        assert stats["ref_count"] == 2

    def test_mixed_fold_types(self):
        from loops.commands.fetch import _tick_payload_stats

        payload = {
            "decision": {"items": {"auth": {"_n": 2}}},          # by-fold
            "log": {"items": [{"m": "x"}, {"m": "y"}]},          # collect-fold
        }
        stats = _tick_payload_stats(payload)
        assert stats["kind_counts"] == {"decision": 1, "log": 2}
        assert stats["total_items"] == 3
        assert stats["total_facts"] == 4  # 2 + 1 + 1
        assert stats["kind_items"]["decision"] == {"auth": 2}
        assert stats["kind_items"]["log"] == {}  # collect has no keys

    def test_non_dict_kind_skipped(self):
        """Defensive: odd payload shapes should not crash."""
        from loops.commands.fetch import _tick_payload_stats

        payload = {"weird": "not-a-dict", "decision": {"items": {"x": {"_n": 1}}}}
        stats = _tick_payload_stats(payload)
        assert stats["kind_counts"] == {"decision": 1}


class TestTickDelta:
    """Added vs. updated distinction — by-folds use keys, collect-folds count growth."""

    def _stats(self, kind_items=None, kind_counts=None):
        return {
            "kind_items": kind_items or {},
            "kind_counts": kind_counts or {},
            "total_items": sum((kind_counts or {}).values()),
            "total_facts": sum(
                sum(v.values()) for v in (kind_items or {}).values()
            ),
            "kind_compression": {},
            "ref_count": 0,
        }

    def test_no_change(self):
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"decision": {"auth": 1}},
            kind_counts={"decision": 1},
        )
        prev = self._stats(
            kind_items={"decision": {"auth": 1}},
            kind_counts={"decision": 1},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 0
        assert updated == 0
        assert added_keys == {}
        assert updated_keys == {}

    def test_added_key_in_by_fold(self):
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"decision": {"auth": 1, "storage": 1}},
            kind_counts={"decision": 2},
        )
        prev = self._stats(
            kind_items={"decision": {"auth": 1}},
            kind_counts={"decision": 1},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 1
        assert updated == 0
        assert added_keys == {"decision": ("storage",)}
        assert updated_keys == {}

    def test_updated_key_when_n_grows(self):
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"decision": {"auth": 3}},
            kind_counts={"decision": 1},
        )
        prev = self._stats(
            kind_items={"decision": {"auth": 1}},
            kind_counts={"decision": 1},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 0
        assert updated == 1
        assert added_keys == {}
        assert updated_keys == {"decision": ("auth",)}

    def test_mixed_added_and_updated(self):
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={
                "decision": {"auth": 2, "storage": 1, "ui": 1},
                "thread": {"wrap-up": 5},
            },
            kind_counts={"decision": 3, "thread": 1},
        )
        prev = self._stats(
            kind_items={
                "decision": {"auth": 1, "storage": 1},
                "thread": {"wrap-up": 3},
            },
            kind_counts={"decision": 2, "thread": 1},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 1  # ui is new in decision
        assert updated == 2  # auth (1→2) and wrap-up (3→5)
        assert added_keys == {"decision": ("ui",)}
        assert updated_keys == {
            "decision": ("auth",),
            "thread": ("wrap-up",),
        }

    def test_n_shrink_is_not_updated(self):
        """Only growth counts as 'updated'. Shrinkage (which shouldn't happen
        in a well-formed upsert fold) is ignored."""
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"decision": {"auth": 1}},
            kind_counts={"decision": 1},
        )
        prev = self._stats(
            kind_items={"decision": {"auth": 5}},
            kind_counts={"decision": 1},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 0
        assert updated == 0

    def test_collect_fold_growth_counts_as_added(self):
        """Collect-folds have empty kind_items but contribute count growth."""
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"log": {}},
            kind_counts={"log": 8},
        )
        prev = self._stats(
            kind_items={"log": {}},
            kind_counts={"log": 5},
        )
        added, updated, added_keys, updated_keys = _tick_delta(curr, prev)
        assert added == 3
        assert updated == 0
        # No key-level detail for collect-folds
        assert "log" not in added_keys
        assert "log" not in updated_keys

    def test_collect_fold_shrink_ignored(self):
        """Collect-folds that shrank (rolled off) should not produce negatives."""
        from loops.commands.fetch import _tick_delta

        curr = self._stats(kind_items={"log": {}}, kind_counts={"log": 3})
        prev = self._stats(kind_items={"log": {}}, kind_counts={"log": 5})
        added, updated, _, _ = _tick_delta(curr, prev)
        assert added == 0
        assert updated == 0

    def test_keys_sorted_alphabetically(self):
        from loops.commands.fetch import _tick_delta

        curr = self._stats(
            kind_items={"decision": {"zebra": 1, "apple": 1, "mango": 1}},
            kind_counts={"decision": 3},
        )
        prev = self._stats(kind_items={"decision": {}}, kind_counts={"decision": 0})
        _, _, added_keys, _ = _tick_delta(curr, prev)
        assert added_keys["decision"] == ("apple", "mango", "zebra")

    def test_empty_vs_empty(self):
        from loops.commands.fetch import _tick_delta

        added, updated, added_keys, updated_keys = _tick_delta(
            self._stats(), self._stats(),
        )
        assert added == 0
        assert updated == 0
        assert added_keys == {}
        assert updated_keys == {}


def _write_project_vertex(tmp_path):
    """Write a project vertex with a vertex-level boundary on session.closed.

    The builder doesn't expose vertex-level boundaries, so we write the KDL
    directly — matching what `.loops/project.vertex` looks like in practice.
    """
    vpath = tmp_path / "project.vertex"
    vpath.write_text(
        'name "project"\n'
        'store "./project.db"\n'
        '\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '  thread   { fold { items "by" "name" } }\n'
        '  log      { fold { items "collect" 20 } }\n'
        '  session  { fold { items "by" "name" } }\n'
        '\n'
        '  boundary when="session" status="closed"\n'
        '}\n',
    )
    return vpath


def _emit(vpath, kind, **parts):
    from loops.main import cmd_emit
    import argparse

    cmd_emit(
        argparse.Namespace(
            vertex=None, kind=kind,
            parts=[f"{k}={v}" for k, v in parts.items()],
            observer="kyle", dry_run=False,
        ),
        vertex_path=vpath,
    )


class TestFetchTickWindows:
    """End-to-end fetch path against a real store with vertex-level boundary ticks."""

    def test_no_ticks_returns_empty(self, tmp_path):
        from loops.commands.fetch import fetch_tick_windows

        vpath = _write_project_vertex(tmp_path)
        windows = fetch_tick_windows(vpath)
        assert windows == ()

    def test_single_tick_has_zero_deltas(self, tmp_path):
        from loops.commands.fetch import fetch_tick_windows

        vpath = _write_project_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="JWT")
        _emit(vpath, "thread", name="wrap-up", status="open")
        # Trigger vertex-level boundary
        _emit(vpath, "session", name="kyle", status="closed")

        windows = fetch_tick_windows(vpath)
        assert len(windows) == 1
        w = windows[0]
        assert w.index == 0
        assert w.name == "project"
        assert w.observer == "kyle"
        assert w.boundary_trigger == "kyle closed"
        assert w.total_items >= 2  # at least decision + thread
        assert w.delta_added == 0  # oldest tick — no prior
        assert w.delta_updated == 0
        assert w.added_keys == {}
        assert w.updated_keys == {}

    def test_delta_across_two_sessions_added_and_updated(self, tmp_path):
        from loops.commands.fetch import fetch_tick_windows

        vpath = _write_project_vertex(tmp_path)

        # Session 1: emit auth decision, close
        _emit(vpath, "decision", topic="auth", message="JWT")
        _emit(vpath, "session", name="kyle", status="closed")

        # Session 2: re-emit auth (updates n), add storage (new key), close
        _emit(vpath, "decision", topic="auth", message="JWT v2")
        _emit(vpath, "decision", topic="storage", message="SQLite")
        _emit(vpath, "session", name="kyle", status="closed")

        windows = fetch_tick_windows(vpath)
        assert len(windows) == 2

        newest = windows[0]
        oldest = windows[1]

        # Newest — compared against older
        #   decision: 'storage' added (new key), 'auth' updated (n grew)
        #   session:  'kyle' updated (session fact itself is upserted at close)
        assert newest.added_keys.get("decision") == ("storage",)
        assert newest.updated_keys.get("decision") == ("auth",)
        assert newest.updated_keys.get("session") == ("kyle",)
        assert newest.delta_added == 1  # just 'storage'
        assert newest.delta_updated == 2  # 'auth' + 'kyle'

        # Oldest — no predecessor
        assert oldest.delta_added == 0
        assert oldest.delta_updated == 0

    def test_newest_first_ordering(self, tmp_path):
        from loops.commands.fetch import fetch_tick_windows

        vpath = _write_project_vertex(tmp_path)
        _emit(vpath, "decision", topic="a", message="x")
        _emit(vpath, "session", name="kyle", status="closed")
        _emit(vpath, "decision", topic="b", message="y")
        _emit(vpath, "session", name="kyle", status="closed")

        windows = fetch_tick_windows(vpath)
        assert len(windows) == 2
        assert windows[0].ts > windows[1].ts
        assert windows[0].index == 0
        assert windows[1].index == 1

