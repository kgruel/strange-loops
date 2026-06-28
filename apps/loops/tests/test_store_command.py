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


class TestStoreVerify:
    """sl store verify — tick hash chain verification at the CLI surface."""

    def _make_vertex(self, tmp_path: Path) -> Path:
        from engine.builder import fold_count, vertex
        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop("ping", fold_count("n"), boundary_every=1).write(vpath)
        return vpath

    def test_intact_chain_exits_zero(self, tmp_path, capsys):
        from loops.commands.store import _run_verify
        vpath = self._make_vertex(tmp_path)
        _emit(vpath, "ping", service="api", status="up")
        _emit(vpath, "ping", service="api", status="up")

        rc = _run_verify([str(vpath)])
        assert rc == 0
        assert "chain intact" in capsys.readouterr().out

    def test_tampered_fact_exits_one(self, tmp_path, capsys):
        import sqlite3
        from loops.commands.store import _run_verify
        vpath = self._make_vertex(tmp_path)
        _emit(vpath, "ping", service="api", status="up")
        _emit(vpath, "ping", service="api", status="up")

        conn = sqlite3.connect(str(tmp_path / "x.db"))
        conn.execute("UPDATE facts SET payload = '{\"service\": \"forged\"}'")
        conn.commit()
        conn.close()

        rc = _run_verify([str(vpath)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "CHAIN BROKEN" in out
        assert "window_hash" in out

    def test_json_report(self, tmp_path, capsys):
        import json
        from loops.commands.store import _run_verify
        vpath = self._make_vertex(tmp_path)
        _emit(vpath, "ping", service="api", status="up")

        capsys.readouterr()  # discard emit receipt noise
        rc = _run_verify([str(vpath), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["ok"] is True
        assert report["chained"] >= 1

    def test_help_exits_zero(self, capsys):
        # `store verify -h` is now owned by argparse (add_help=True): the
        # parser prints help and raises SystemExit(0) natively, replacing the
        # hand-rolled `return 0` block (decision:design/devtools-help-args-idiom).
        import pytest
        from loops.commands.store import _run_verify
        with pytest.raises(SystemExit) as exc:
            _run_verify(["--help"])
        assert exc.value.code == 0
        assert "usage:" in capsys.readouterr().out

    def test_verify_routes_through_run_store(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = self._make_vertex(tmp_path)
        _emit(vpath, "ping", service="api", status="up")

        rc = _run_store(["verify", str(vpath)])
        assert rc == 0
        assert "chain intact" in capsys.readouterr().out


def _make_boundary_vertex(tmp_path: Path) -> Path:
    """Project-shaped vertex with a vertex-level boundary on session.closed.

    The builder doesn't expose vertex-level boundaries (test_fetch mirrors
    this), so write the KDL directly — vertex-level ticks are named after
    the vertex ("project"), which is what fetch_tick_windows resolves to.
    """
    vpath = tmp_path / "project.vertex"
    vpath.write_text(
        'name "project"\n'
        'store "./project.db"\n'
        '\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '  thread   { fold { items "by" "name" } }\n'
        '  session  { fold { items "by" "name" } }\n'
        '\n'
        '  boundary when="session" status="closed"\n'
        '}\n'
    )
    return vpath


def _seed_two_ticks(vpath: Path) -> None:
    """Two vertex-level chain ticks via two session-close boundaries."""
    _emit(vpath, "decision", topic="auth", message="JWT")
    _emit(vpath, "session", name="kyle", status="closed")
    _emit(vpath, "decision", topic="storage", message="SQLite")
    _emit(vpath, "session", name="kyle", status="closed")


class TestStoreTicks:
    """sl store ticks [--chain] — the attestation read surface."""

    def test_chain_renders_attestation_rows(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _seed_two_ticks(vpath)
        capsys.readouterr()  # discard emit receipts
        rc = _run_store(["ticks", "--chain", str(vpath)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 ticks" in out
        assert "linked" in out      # fresh stores chain their ticks
        assert "unsigned" in out    # no signing key configured
        assert "chained" in out     # rollup line

    def test_default_density_projection(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _seed_two_ticks(vpath)
        capsys.readouterr()
        rc = _run_store(["ticks", str(vpath)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "2 ticks" in out
        assert "linked" not in out  # density mode omits attestation columns

    def test_json_is_structured(self, tmp_path, capsys):
        import json
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _seed_two_ticks(vpath)
        capsys.readouterr()
        rc = _run_store(["ticks", "--chain", str(vpath), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["chain"]["ticks"] == 2
        assert report["chain"]["chained"] == 2
        assert len(report["windows"]) == 2
        assert report["windows"][0]["chained"] is True

    def test_requires_vertex_target(self, tmp_path):
        from loops.commands.store import _run_store_ticks
        # A .db can't resolve a named tick series — refuse, don't guess.
        with pytest.raises(ValueError, match="requires a .vertex"):
            _run_store_ticks([str(tmp_path / "x.db")])

    def test_empty_store_renders_cleanly(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="a")  # db exists, 0 ticks
        capsys.readouterr()
        rc = _run_store(["ticks", "--chain", str(vpath)])
        assert rc == 0
        assert "No ticks" in capsys.readouterr().out

    def test_refuses_aggregate_vertex(self, tmp_path):
        # A combine/discover aggregate has no own store/chain — vertex_ticks
        # returns empty envelopes for it, so --chain would render a real
        # signed chain as a false "all legacy". Refuse, like the siblings do.
        from loops.commands.store import _run_store_ticks
        agg = tmp_path / "agg.vertex"
        agg.write_text('name "agg"\ncombine {\n  vertex "./child.vertex"\n}\n')
        with pytest.raises(ValueError, match="aggregate vertex"):
            _run_store_ticks([str(agg)])

    def test_chain_spans_all_series_density_scopes(self, tmp_path, capsys):
        # Loop-level boundary → ticks named "ping", not the vertex "x".
        # --chain (all_names) spans the full chain and sees them; the density
        # default is name-scoped to "x" and correctly shows none — the
        # documented scope difference that keeps --chain agreeing with verify.
        import json

        from engine.builder import fold_count, vertex
        from loops.commands.store import _run_store
        vpath = tmp_path / "x.vertex"
        vertex("x").store("./x.db").loop(
            "ping", fold_count("n"), boundary_every=1
        ).write(vpath)
        _emit(vpath, "ping", service="api")
        _emit(vpath, "ping", service="web")

        capsys.readouterr()
        rc = _run_store(["ticks", "--chain", str(vpath), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["chain"]["ticks"] == 2
        assert {w["name"] for w in report["windows"]} == {"ping"}

        capsys.readouterr()
        rc = _run_store(["ticks", str(vpath)])  # density, name-scoped to "x"
        assert rc == 0
        assert "No ticks" in capsys.readouterr().out


class TestStoreStats:
    """sl store stats [--by-kind] — the count surface (.db or .vertex)."""

    def test_by_kind_renders_count_desc(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="a")
        _emit(vpath, "decision", topic="storage", message="b")
        _emit(vpath, "thread", name="t1", status="open")
        capsys.readouterr()
        rc = _run_store(["stats", "--by-kind", str(vpath)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "decision" in out and "thread" in out
        assert out.index("decision") < out.index("thread")  # count-desc

    def test_works_on_db_path(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="a")
        capsys.readouterr()
        rc = _run_store(["stats", "--by-kind", str(tmp_path / "project.db")])
        assert rc == 0
        assert "decision" in capsys.readouterr().out

    def test_default_is_topline_only(self, tmp_path, capsys):
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="a")
        _emit(vpath, "thread", name="t1", status="open")
        capsys.readouterr()
        rc = _run_store(["stats", str(vpath)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "facts" in out          # rollup present
        assert "thread" not in out     # no per-kind table without --by-kind

    def test_json_kinds_sorted_desc(self, tmp_path, capsys):
        import json
        from loops.commands.store import _run_store
        vpath = _make_boundary_vertex(tmp_path)
        _emit(vpath, "decision", topic="auth", message="a")
        _emit(vpath, "decision", topic="storage", message="b")
        _emit(vpath, "thread", name="t1", status="open")
        capsys.readouterr()
        rc = _run_store(["stats", "--by-kind", str(vpath), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        counts = [k["count"] for k in report["kinds"]]
        assert counts == sorted(counts, reverse=True)
        assert report["total_facts"] >= 3


class TestStoreErrorBoundary:
    """The store view boundary renders operator-facing refusals as clean
    errors (reporter.err + exit 1), never raw tracebacks.

    Regression for reanchor's no-vertex / no-key refusal escaping as an
    uncaught ``ValueError`` — which read as a crash and made the refusal
    look like a verdict contradicting ``store verify`` (the smoke-test's
    "verify-vs-reanchor opposite verdict" turned out to be exactly this
    rendering gap, not an integrity divergence).
    """

    @staticmethod
    def _ctx_with_reporter():
        from loops.cli.invocation import Invocation
        from loops.cli.output import BufferReporter

        reporter = BufferReporter()
        return Invocation(reporter=reporter, vertex_path=None), reporter

    def test_reanchor_db_target_is_clean_error(self, tmp_path):
        # reanchor refuses a raw .db (keys + registry live with the .vertex).
        # The suffix guard fires before any existence check, so the db need
        # not exist. Must surface as a clean reporter error, not a traceback.
        from loops.cli.views.store import run

        ctx, reporter = self._ctx_with_reporter()
        rc = run(["reanchor", str(tmp_path / "x.db")], ctx)
        assert rc == 1
        assert any("requires a .vertex" in line for line in reporter.err_lines)

    def test_missing_store_is_clean_error(self, tmp_path):
        # A .vertex with no store directive raises ValueError("No store
        # configured") deep in resolve_store_path — also operator-facing.
        from loops.cli.views.store import run

        vpath = tmp_path / "x.vertex"
        vpath.write_text('name "x"\nloops { ping { fold { n "inc" } } }\n')
        ctx, reporter = self._ctx_with_reporter()
        rc = run(["verify", str(vpath)], ctx)
        assert rc == 1
        assert any("No store configured" in line for line in reporter.err_lines)

    def test_unexpected_errors_still_propagate(self, monkeypatch):
        # The catch is scoped to operator-error types — a genuine bug
        # (e.g. RuntimeError) must still raise so it stays debuggable.
        import loops.commands.store as store_cmds
        from loops.cli.views.store import run

        def boom(*args, **kwargs):
            raise RuntimeError("genuine bug")

        monkeypatch.setattr(store_cmds, "_run_store", boom)
        ctx, _reporter = self._ctx_with_reporter()
        with pytest.raises(RuntimeError, match="genuine bug"):
            run(["reanchor", "/tmp/whatever.db"], ctx)
