"""Tests for Cadence store predicate."""

import time

from atoms import Fact
from engine import Cadence
from engine import EventStore


def _make_store():
    return EventStore(serialize=Fact.to_dict, deserialize=Fact.from_dict)


class TestCadenceAlways:
    def test_always_returns_true(self):
        store = _make_store()
        assert Cadence.always().should_run(store) is True

    def test_always_true_even_with_facts(self):
        store = _make_store()
        store.append(Fact.of("anything", "obs"))
        assert Cadence.always().should_run(store) is True


class TestCadenceElapsed:
    def test_never_run_returns_true(self):
        store = _make_store()
        cadence = Cadence.elapsed("disk", 60.0)
        assert cadence.should_run(store) is True

    def test_recently_run_returns_false(self):
        store = _make_store()
        store.append(Fact.of("disk.complete", "obs", status="ok"))
        cadence = Cadence.elapsed("disk", 60.0)
        assert cadence.should_run(store) is False

    def test_interval_elapsed_returns_true(self):
        store = _make_store()
        now = time.time()
        old_fact = Fact("disk.complete", now - 120, {"status": "ok"}, "obs")
        store.append(old_fact)
        cadence = Cadence.elapsed("disk", 60.0)
        assert cadence.should_run(store, now=now) is True

    def test_interval_not_elapsed_returns_false(self):
        store = _make_store()
        now = time.time()
        recent_fact = Fact("disk.complete", now - 30, {"status": "ok"}, "obs")
        store.append(recent_fact)
        cadence = Cadence.elapsed("disk", 60.0)
        assert cadence.should_run(store, now=now) is False


class TestCadenceTriggered:
    def test_no_trigger_no_complete_returns_false(self):
        store = _make_store()
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store) is False

    def test_trigger_exists_no_complete_returns_true(self):
        store = _make_store()
        store.append(Fact.of("minute", "timer"))
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store) is True

    def test_trigger_after_complete_returns_true(self):
        store = _make_store()
        now = time.time()
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        store.append(Fact("minute", now - 5, {}, "timer"))
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store, now=now) is True

    def test_no_trigger_after_complete_returns_false(self):
        store = _make_store()
        now = time.time()
        store.append(Fact("minute", now - 15, {}, "timer"))
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store, now=now) is False

    def test_multi_trigger_or_semantics(self):
        store = _make_store()
        now = time.time()
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        store.append(Fact("deploy.complete", now - 5, {}, "ci"))
        cadence = Cadence.triggered(("minute", "deploy.complete"), "disk")
        assert cadence.should_run(store, now=now) is True

    def test_multi_trigger_none_match(self):
        store = _make_store()
        now = time.time()
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        cadence = Cadence.triggered(("minute", "deploy.complete"), "disk")
        assert cadence.should_run(store, now=now) is False

    def test_single_string_trigger(self):
        store = _make_store()
        store.append(Fact.of("minute", "timer"))
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store) is True


class TestCadenceErrorDoesNotResetClock:
    """Failed completions (status='error') should not reset the cadence clock."""

    def test_elapsed_ignores_error_completion(self):
        store = _make_store()
        now = time.time()
        # Successful completion 120s ago
        store.append(Fact("disk.complete", now - 120, {"status": "ok"}, "obs"))
        # Recent failed completion — should NOT reset the clock
        store.append(Fact("disk.complete", now - 5, {"status": "error", "error": "timeout"}, "obs"))
        cadence = Cadence.elapsed("disk", 60.0)
        # 120s since last OK > 60s interval → should run
        assert cadence.should_run(store, now=now) is True

    def test_elapsed_respects_ok_completion(self):
        store = _make_store()
        now = time.time()
        # Recent OK completion
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        # Even older error
        store.append(Fact("disk.complete", now - 5, {"status": "error"}, "obs"))
        cadence = Cadence.elapsed("disk", 60.0)
        # 10s since last OK < 60s interval → should NOT run
        assert cadence.should_run(store, now=now) is False

    def test_triggered_ignores_error_completion(self):
        store = _make_store()
        now = time.time()
        # Trigger arrived at -15
        store.append(Fact("minute", now - 15, {}, "timer"))
        # Error completion at -10 — should NOT count as "completed"
        store.append(Fact("disk.complete", now - 10, {"status": "error"}, "obs"))
        cadence = Cadence.triggered("minute", "disk")
        # No OK completion → trigger at -15 still qualifies
        assert cadence.should_run(store, now=now) is True

    def test_triggered_respects_ok_completion(self):
        store = _make_store()
        now = time.time()
        # Trigger at -15, OK completion at -10 → trigger consumed
        store.append(Fact("minute", now - 15, {}, "timer"))
        store.append(Fact("disk.complete", now - 10, {"status": "ok"}, "obs"))
        cadence = Cadence.triggered("minute", "disk")
        assert cadence.should_run(store, now=now) is False

    def test_never_succeeded_with_errors_still_retries(self):
        store = _make_store()
        now = time.time()
        # Only errors, never succeeded
        store.append(Fact("disk.complete", now - 30, {"status": "error"}, "obs"))
        store.append(Fact("disk.complete", now - 10, {"status": "error"}, "obs"))
        cadence = Cadence.elapsed("disk", 60.0)
        # No OK completion ever → should run
        assert cadence.should_run(store, now=now) is True


class TestStoreLatestByKindWhere:
    def test_event_store_filters_by_payload(self):
        store = _make_store()
        store.append(Fact.of("a.complete", "obs", status="ok", v=1))
        store.append(Fact.of("a.complete", "obs", status="error", v=2))
        store.append(Fact.of("a.complete", "obs", status="ok", v=3))

        result = store.latest_by_kind_where("a.complete", "status", "ok")
        assert result is not None
        assert result.payload["v"] == 3

        result = store.latest_by_kind_where("a.complete", "status", "error")
        assert result is not None
        assert result.payload["v"] == 2

        assert store.latest_by_kind_where("a.complete", "status", "missing") is None

    def test_sqlite_store_filters_by_payload(self, tmp_path):
        from engine import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("a.complete", "obs", status="ok", v=1))
        store.append(Fact.of("a.complete", "obs", status="error", v=2))
        store.append(Fact.of("a.complete", "obs", status="ok", v=3))

        result = store.latest_by_kind_where("a.complete", "status", "ok")
        assert result is not None
        assert result.payload["v"] == 3

        result = store.latest_by_kind_where("a.complete", "status", "error")
        assert result is not None
        assert result.payload["v"] == 2

        assert store.latest_by_kind_where("a.complete", "status", "missing") is None
        store.close()


class TestCompileSource:
    def test_elapsed_from_every(self):
        from engine import compile_source
        from lang import parse_loop

        ast = parse_loop(
            'source "echo hi"\n'
            'kind "test"\n'
            'observer "obs"\n'
            'every "30m"\n'
        )
        source, cadence = compile_source(ast)
        assert source.kind == "test"
        assert cadence._mode == "elapsed"
        assert cadence._interval == 1800.0

    def test_triggered_from_on(self):
        from engine import compile_source
        from lang import parse_loop

        ast = parse_loop(
            'source "echo hi"\n'
            'kind "test"\n'
            'observer "obs"\n'
            'on "minute"\n'
        )
        source, cadence = compile_source(ast)
        assert cadence._mode == "triggered"
        assert cadence._trigger_kinds == ("minute",)

    def test_always_from_nothing(self):
        from engine import compile_source
        from lang import parse_loop

        ast = parse_loop(
            'source "echo hi"\n'
            'kind "test"\n'
            'observer "obs"\n'
        )
        source, cadence = compile_source(ast)
        assert cadence._mode == "always"


class TestStoreLatestByKind:
    def test_sqlite_store_latest_by_kind(self, tmp_path):
        from engine import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("a", "obs", v=1))
        store.append(Fact.of("b", "obs", v=2))
        store.append(Fact.of("a", "obs", v=3))

        latest = store.latest_by_kind("a")
        assert latest is not None
        assert latest.payload["v"] == 3

        assert store.latest_by_kind("missing") is None
        store.close()

    def test_event_store_latest_by_kind(self):
        store = _make_store()
        store.append(Fact.of("a", "obs", v=1))
        store.append(Fact.of("b", "obs", v=2))
        store.append(Fact.of("a", "obs", v=3))

        latest = store.latest_by_kind("a")
        assert latest is not None
        assert latest.payload["v"] == 3
        assert store.latest_by_kind("missing") is None


class TestStoreHasKindSince:
    def test_sqlite_store_has_kind_since(self, tmp_path):
        from engine import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        now = time.time()
        store.append(Fact("a", now - 20, {"v": 1}, "obs"))
        store.append(Fact("b", now - 10, {"v": 2}, "obs"))
        store.append(Fact("a", now - 5, {"v": 3}, "obs"))

        assert store.has_kind_since("a", now - 15) is True
        assert store.has_kind_since("a", now - 3) is False
        assert store.has_kind_since("b", now - 15) is True
        assert store.has_kind_since("b", now - 5) is False
        store.close()

    def test_event_store_has_kind_since(self):
        store = _make_store()
        now = time.time()
        store.append(Fact("a", now - 20, {"v": 1}, "obs"))
        store.append(Fact("b", now - 10, {"v": 2}, "obs"))
        store.append(Fact("a", now - 5, {"v": 3}, "obs"))

        assert store.has_kind_since("a", now - 15) is True
        assert store.has_kind_since("a", now - 3) is False
        assert store.has_kind_since("b", now - 15) is True
        assert store.has_kind_since("b", now - 5) is False
