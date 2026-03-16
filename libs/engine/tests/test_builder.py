"""Tests for the vertex builder SDK."""

from pathlib import Path

import pytest

from engine.builder import (
    LoopBuilder,
    VertexBuilder,
    fold_avg,
    fold_by,
    fold_collect,
    fold_count,
    fold_latest,
    fold_max,
    fold_min,
    fold_sum,
    fold_window,
    vertex,
)
from lang.ast import (
    BoundaryAfter,
    BoundaryEvery,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
)


class TestFoldHelpers:
    def test_fold_count(self):
        fd = fold_count("n")
        assert fd.target == "n"
        assert isinstance(fd.op, FoldCount)

    def test_fold_by(self):
        fd = fold_by("service")
        assert fd.target == "service"
        assert isinstance(fd.op, FoldBy)
        assert fd.op.key_field == "service"

    def test_fold_collect(self):
        fd = fold_collect("items", max_items=50)
        assert isinstance(fd.op, FoldCollect)
        assert fd.op.max_items == 50

    def test_fold_latest(self):
        assert isinstance(fold_latest().op, FoldLatest)

    def test_fold_sum(self):
        fd = fold_sum("latency")
        assert isinstance(fd.op, FoldSum)
        assert fd.op.field == "latency"

    def test_fold_max(self):
        assert isinstance(fold_max("cpu").op, FoldMax)

    def test_fold_min(self):
        assert isinstance(fold_min("mem").op, FoldMin)

    def test_fold_avg(self):
        assert isinstance(fold_avg("temp").op, FoldAvg)

    def test_fold_window(self):
        fd = fold_window("readings", size=10)
        assert isinstance(fd.op, FoldWindow)
        assert fd.op.size == 10


class TestVertexBuilder:
    def test_minimal(self):
        v = vertex("test").store("./t.db").loop("ping", fold_count("n")).build()
        assert v.name == "test"
        assert v.store == Path("t.db")
        assert "ping" in v.loops
        assert len(v.loops["ping"].folds) == 1

    def test_multiple_loops(self):
        v = (vertex("multi")
            .store("./m.db")
            .loop("a", fold_count("n"))
            .loop("b", fold_by("key"), search=["x", "y"])
            .loop("c", fold_collect("items"))
            .build())
        assert len(v.loops) == 3
        assert v.loops["b"].search == ("x", "y")

    def test_boundary_every(self):
        v = vertex("b").store("./b.db").loop("x", fold_count("n"), boundary_every=5).build()
        assert isinstance(v.loops["x"].boundary, BoundaryEvery)
        assert v.loops["x"].boundary.count == 5

    def test_boundary_after(self):
        v = vertex("b").store("./b.db").loop("x", fold_count("n"), boundary_after=10).build()
        assert isinstance(v.loops["x"].boundary, BoundaryAfter)

    def test_routes(self):
        v = vertex("r").store("./r.db").loop("a", fold_count("n")).route("x", "a").build()
        assert v.routes == {"x": "a"}

    def test_observer_scoped(self):
        v = vertex("o").store("./o.db").loop("a", fold_count("n")).observer_scoped().build()
        assert v.observer_scoped is True

    def test_loop_builder(self):
        v = (vertex("lb")
            .store("./lb.db")
            .loop_builder("events", fold_collect("items"))
                .search("type", "source")
                .boundary_every(10)
                .done()
            .build())
        loop = v.loops["events"]
        assert loop.search == ("type", "source")
        assert isinstance(loop.boundary, BoundaryEvery)


class TestVertexWrite:
    def test_write_and_parse(self, tmp_path):
        """Round-trip: builder → KDL file → parse back."""
        b = (vertex("roundtrip")
            .store("./rt.db")
            .loop("heartbeat", fold_count("n"), search=["service"])
            .loop("metric", fold_by("service")))
        b.write(tmp_path / "test.vertex")

        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "test.vertex")
        assert ast.name == "roundtrip"
        assert "heartbeat" in ast.loops
        assert "metric" in ast.loops
        assert ast.loops["heartbeat"].search == ("service",)

    def test_write_with_boundary(self, tmp_path):
        b = (vertex("bnd")
            .store("./b.db")
            .loop("x", fold_count("n"), boundary_every=5))
        b.write(tmp_path / "b.vertex")

        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "b.vertex")
        assert isinstance(ast.loops["x"].boundary, BoundaryEvery)
        assert ast.loops["x"].boundary.count == 5

    def test_write_full_emit_cycle(self, tmp_path):
        """Builder → write → load_vertex_program → emit → read back."""
        b = (vertex("full")
            .store("./full.db")
            .loop("event", fold_collect("items", max_items=50)))
        b.write(tmp_path / "full.vertex")

        from engine import load_vertex_program
        from atoms import Fact

        vpath = tmp_path / "full.vertex"
        program = load_vertex_program(vpath, validate_ast=False)
        fact = Fact(kind="event", ts=1.0, payload={"msg": "hello"}, observer="test")
        program.vertex.receive(fact)
        if program.vertex._store:
            program.vertex._store.close()

        from engine import vertex_facts
        facts = vertex_facts(vpath, since_ts=0, until_ts=9999999999)
        assert len(facts) >= 1
        assert facts[0]["payload"]["msg"] == "hello"


class TestWriteAllFoldTypes:
    """Round-trip every fold type through KDL to verify serialization."""

    def test_sum_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_sum
        vertex("t").store("./t.db").loop("m", fold_sum("latency")).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].folds[0].op, FoldSum)

    def test_max_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_max
        vertex("t").store("./t.db").loop("m", fold_max("cpu")).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].folds[0].op, FoldMax)

    def test_min_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_min
        vertex("t").store("./t.db").loop("m", fold_min("mem")).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].folds[0].op, FoldMin)

    def test_avg_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_avg
        vertex("t").store("./t.db").loop("m", fold_avg("temp")).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].folds[0].op, FoldAvg)

    def test_window_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_window
        vertex("t").store("./t.db").loop("m", fold_window("readings", size=10)).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        op = ast.loops["m"].folds[0].op
        assert isinstance(op, FoldWindow)
        assert op.size == 10

    def test_latest_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_latest
        vertex("t").store("./t.db").loop("m", fold_latest()).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].folds[0].op, FoldLatest)

    def test_boundary_after_roundtrip(self, tmp_path):
        from engine.builder import vertex, fold_count
        vertex("t").store("./t.db").loop("m", fold_count("n"), boundary_after=5).write(tmp_path / "t.vertex")
        from lang import parse_vertex_file
        ast = parse_vertex_file(tmp_path / "t.vertex")
        assert isinstance(ast.loops["m"].boundary, BoundaryAfter)
        assert ast.loops["m"].boundary.count == 5
