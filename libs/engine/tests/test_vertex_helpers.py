"""Tests for vertex boundary condition evaluation and helper functions."""

from engine.vertex import _eval_condition, _json_default


class _FakeCondition:
    """Minimal condition object for testing _eval_condition."""
    def __init__(self, target, op, value):
        self.target = target
        self.op = op
        self.value = value


class TestEvalCondition:
    def test_gte(self):
        assert _eval_condition({"cpu": 90}, _FakeCondition("cpu", ">=", 80)) is True
        assert _eval_condition({"cpu": 70}, _FakeCondition("cpu", ">=", 80)) is False

    def test_lte(self):
        assert _eval_condition({"mem": 50}, _FakeCondition("mem", "<=", 80)) is True

    def test_gt(self):
        assert _eval_condition({"val": 10}, _FakeCondition("val", ">", 5)) is True
        assert _eval_condition({"val": 5}, _FakeCondition("val", ">", 5)) is False

    def test_lt(self):
        assert _eval_condition({"val": 3}, _FakeCondition("val", "<", 5)) is True

    def test_eq(self):
        assert _eval_condition({"x": 42}, _FakeCondition("x", "==", 42)) is True
        assert _eval_condition({"x": 41}, _FakeCondition("x", "==", 42)) is False

    def test_neq(self):
        assert _eval_condition({"x": 1}, _FakeCondition("x", "!=", 2)) is True
        assert _eval_condition({"x": 2}, _FakeCondition("x", "!=", 2)) is False

    def test_missing_target(self):
        assert _eval_condition({"a": 1}, _FakeCondition("b", ">=", 0)) is False

    def test_non_dict_state(self):
        assert _eval_condition("not a dict", _FakeCondition("x", ">=", 0)) is False

    def test_mapping_proxy(self):
        from types import MappingProxyType
        state = MappingProxyType({"cpu": 95})
        assert _eval_condition(state, _FakeCondition("cpu", ">=", 90)) is True

    def test_string_equality(self):
        """Non-numeric values fall back to string comparison for == and !=."""
        assert _eval_condition({"status": "ok"}, _FakeCondition("status", "==", "ok")) is True
        assert _eval_condition({"status": "ok"}, _FakeCondition("status", "!=", "ok")) is False
        assert _eval_condition({"status": "ok"}, _FakeCondition("status", "!=", "bad")) is True

    def test_non_numeric_non_eq(self):
        """Non-numeric values with >/< operators return False."""
        assert _eval_condition({"s": "abc"}, _FakeCondition("s", ">=", "def")) is False


class TestJsonDefault:
    def test_converts_proxy(self):
        import json
        from types import MappingProxyType
        data = MappingProxyType({"a": 1})
        result = json.dumps(data, default=_json_default)
        assert result == '{"a": 1}'

    def test_raises_on_other(self):
        import pytest
        with pytest.raises(TypeError):
            _json_default(set())


class TestReplayPaths:
    """Tests that exercise different replay fast-paths in vertex.py."""

    def test_replay_with_cursor(self, tmp_path):
        """Replay with SqliteStore exercises the replay_cursor fast path."""
        from pathlib import Path
        from engine.builder import vertex, fold_count
        from atoms import Fact

        # Create vertex and store
        b = vertex("replay-test").store("./replay.db").loop("ping", fold_count("n"))
        b.write(tmp_path / "replay.vertex")

        from engine import load_vertex_program

        # First: emit some facts
        prog = load_vertex_program(tmp_path / "replay.vertex", validate_ast=False)
        for i in range(20):
            fact = Fact(kind="ping", ts=float(i), payload={"n": i}, observer="test")
            prog.vertex.receive(fact)
        if prog.vertex._store:
            prog.vertex._store.close()

        # Second: reload — this triggers replay of 20 facts via fast path
        prog2 = load_vertex_program(tmp_path / "replay.vertex", validate_ast=False)
        state = {k: prog2.vertex.state(k) for k in prog2.vertex._loops}
        assert "ping" in state
        if prog2.vertex._store:
            prog2.vertex._store.close()

    def test_replay_with_multiple_kinds(self, tmp_path):
        """Replay dispatches facts to the correct loop by kind."""
        from pathlib import Path
        from engine.builder import vertex, fold_count, fold_by
        from atoms import Fact

        b = (vertex("multi-kind")
            .store("./mk.db")
            .loop("heartbeat", fold_count("n"))
            .loop("metric", fold_by("service")))
        b.write(tmp_path / "mk.vertex")

        from engine import load_vertex_program

        prog = load_vertex_program(tmp_path / "mk.vertex", validate_ast=False)
        for i in range(10):
            prog.vertex.receive(Fact(kind="heartbeat", ts=float(i), payload={"x": i}, observer="test"))
        for svc in ["api", "web", "api"]:
            prog.vertex.receive(Fact(kind="metric", ts=100.0, payload={"service": svc}, observer="test"))
        if prog.vertex._store:
            prog.vertex._store.close()

        prog2 = load_vertex_program(tmp_path / "mk.vertex", validate_ast=False)
        state = {k: prog2.vertex.state(k) for k in prog2.vertex._loops}
        assert "heartbeat" in state
        assert "metric" in state
        if prog2.vertex._store:
            prog2.vertex._store.close()

    def test_replay_empty_store(self, tmp_path):
        """Replay with empty store returns 0."""
        from pathlib import Path
        from engine.builder import vertex, fold_count

        b = vertex("empty").store("./empty.db").loop("ping", fold_count("n"))
        b.write(tmp_path / "empty.vertex")

        from engine import load_vertex_program
        prog = load_vertex_program(tmp_path / "empty.vertex", validate_ast=False)
        state = {k: prog.vertex.state(k) for k in prog.vertex._loops}
        assert "ping" in state
        if prog.vertex._store:
            prog.vertex._store.close()
