"""Tests for loops.commands.store fetchers and path resolution."""

import argparse
from pathlib import Path

import pytest

from loops.commands.store import make_fidelity_fetcher, make_fetcher, resolve_store_path


def _emit(vertex_path: Path, kind: str, **payload):
    from loops.main import cmd_emit
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(vertex=None, kind=kind, parts=parts, observer="", dry_run=False)
    return cmd_emit(ns, vertex_path=vertex_path)


class TestResolveStorePath:
    def test_db_path(self, tmp_path):
        db = tmp_path / "x.db"
        assert resolve_store_path(db) == db.resolve()

    def test_vertex_path(self, tmp_path):
        from engine.builder import vertex, fold_count
        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop("ping", fold_count("n")).write(vpath)
        assert resolve_store_path(vpath) == (tmp_path / "x.db").resolve()

    def test_vertex_without_store(self, tmp_path):
        vpath = tmp_path / "x.vertex"
        vpath.write_text('name "x"\nloops { ping { fold { n "inc" } } }\n')
        with pytest.raises(ValueError, match="No store configured"):
            resolve_store_path(vpath)

    def test_bad_suffix(self, tmp_path):
        with pytest.raises(ValueError, match="Expected .vertex or .db"):
            resolve_store_path(tmp_path / "x.txt")


class TestStoreFetchers:
    def test_make_fetcher_zoom_levels(self, tmp_path):
        from engine.builder import vertex, fold_count

        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop("ping", fold_count("n"), boundary_every=1).write(vpath)
        _emit(vpath, "ping", service="api", status="up")
        _emit(vpath, "ping", service="api", status="up")

        data0 = make_fetcher(vpath, 0)()
        assert data0["facts"]["total"] >= 2

        data1 = make_fetcher(vpath, 1)()
        tick_info = next(iter(data1["ticks"]["names"].values()))
        assert "sparkline" in tick_info
        assert "payload_keys" in tick_info
        fact_info = next(iter(data1["facts"]["kinds"].values()))
        assert "sample_payload" in fact_info

        data2 = make_fetcher(vpath, 2)()
        tick_info2 = next(iter(data2["ticks"]["names"].values()))
        assert "latest_payload" in tick_info2
        assert "latest_ts" in tick_info2

        data3 = make_fetcher(vpath, 3)()
        fact_info3 = next(iter(data3["facts"]["kinds"].values()))
        assert "recent" in fact_info3
        assert isinstance(fact_info3["recent"], list)

    def test_make_fetcher_db_path(self, tmp_path):
        from engine.builder import vertex, fold_count

        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop("ping", fold_count("n")).write(vpath)
        _emit(vpath, "ping", service="api")
        db_path = tmp_path / "x.db"
        data = make_fetcher(db_path, 1)()
        assert data["facts"]["total"] >= 1

    def test_make_fidelity_fetcher(self, tmp_path):
        from engine.builder import vertex, fold_count
        from engine import vertex_facts

        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop("ping", fold_count("n")).write(vpath)
        _emit(vpath, "ping", service="api")
        _emit(vpath, "ping", service="web")

        facts = vertex_facts(vpath, since_ts=0, until_ts=9999999999)
        ts_values = [f["ts"].timestamp() if hasattr(f["ts"], "timestamp") else f["ts"] for f in facts]
        fetch = make_fidelity_fetcher(vpath)
        result = fetch(min(ts_values) - 1, max(ts_values) + 1, kind="ping")
        assert len(result) >= 2
