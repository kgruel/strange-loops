"""loops seal — the deliberately drawn attestation boundary.

Seal dissolves into emit (kind=seal) + the vertex's declared
``boundary when="seal"`` — the observer driver riding the fact-stream
machinery. Must-fire semantics: seal refuses when the vertex declares
no seal boundary. The seal fact (reason) is the last fact inside the
window it seals.

All tests use the ``loops_env`` fixture (LOOPS_HOME + chdir): bare
vertex names resolve LOCAL-FIRST, so a test running from the repo
root would otherwise write to the real .loops/project.vertex
(friction/test-isolation-not-enforced — it happened).

Design anchors: thread/manual-tick-emission,
decision/architecture/boundaries-as-driven-conditions,
decision/design/chain-witness-order.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from loops.main import main


def _write_vertex(home: Path, *, boundary: str | None = 'boundary when="seal"',
                  name: str = "project") -> Path:
    vdir = home / name
    vdir.mkdir(parents=True)
    vertex_path = vdir / f"{name}.vertex"
    lines = [
        f'name "{name}"',
        'store "./data/project.db"',
        "loops {",
        '  decision { fold { items "by" "topic" } }',
        '  session  { fold { items "by" "name" } }',
        '  seal     { fold { items "collect" 10 } }',
    ]
    if boundary:
        lines.append(f"  {boundary}")
    lines.append("}")
    vertex_path.write_text("\n".join(lines) + "\n")
    return vertex_path


def _db(home: Path, name: str = "project") -> Path:
    return home / name / "data" / "project.db"


class TestSeal:
    def test_seal_mints_tick_with_reason_as_last_fact(self, loops_env, capsys):
        """The seal fact is the LAST fact in the window it seals —
        the tick's fact_cursor IS the seal fact's id."""
        _write_vertex(loops_env)

        assert main(["emit", "project", "decision", "topic=x", "message=work"]) == 0
        assert main(["seal", "project", "-m", "checkpoint before surgery"]) == 0

        out = capsys.readouterr()
        assert "tick:" in out.out + out.err  # boundary fired

        conn = sqlite3.connect(_db(loops_env))
        cursor, window_start = conn.execute(
            "SELECT fact_cursor, window_start FROM ticks"
        ).fetchone()
        seal_id, seal_payload = conn.execute(
            "SELECT id, payload FROM facts WHERE kind = 'seal'"
        ).fetchone()
        assert cursor == seal_id  # reason sealed inside its own window
        assert window_start == ""  # first tick in a new store covers all
        assert json.loads(seal_payload)["message"] == "checkpoint before surgery"

    def test_seal_refuses_without_boundary(self, loops_env, capsys):
        """A seal that cannot mint a tick is not a seal."""
        _write_vertex(loops_env, boundary=None)

        assert main(["seal", "project", "-m", "nope"]) == 1
        err = capsys.readouterr().err
        assert "declares no seal boundary" in err
        assert 'boundary when="seal"' in err

        # And nothing was emitted — refusal happens before the fact.
        assert not _db(loops_env).exists()

    def test_seal_session_close_boundary_does_not_satisfy(self, loops_env, capsys):
        """The old session-close declaration is not a seal boundary —
        the dissolution runs the other way (hook emits seal)."""
        _write_vertex(loops_env, boundary='boundary when="session" status="closed"')

        assert main(["seal", "project"]) == 1
        assert "declares no seal boundary" in capsys.readouterr().err

    def test_seal_match_props_folded_into_payload(self, loops_env):
        """Declared match properties ride the emitted payload so the
        boundary always fires — must-fire under matched declarations."""
        _write_vertex(loops_env, boundary='boundary when="seal" scope="full"')

        assert main(["seal", "project", "-m", "scoped"]) == 0
        conn = sqlite3.connect(_db(loops_env))
        assert conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1
        payload = json.loads(conn.execute(
            "SELECT payload FROM facts WHERE kind = 'seal'"
        ).fetchone()[0])
        assert payload["scope"] == "full"

    def test_seal_dry_run_emits_nothing(self, loops_env, capsys):
        _write_vertex(loops_env)

        assert main(["seal", "project", "-m", "preview", "--dry-run"]) == 0
        d = json.loads(capsys.readouterr().out)
        assert d["kind"] == "seal"
        assert d["payload"]["message"] == "preview"
        assert not _db(loops_env).exists()

    def test_seal_vertex_first_form(self, loops_env):
        """``sl project seal -m ...`` — vertex-first dispatch."""
        _write_vertex(loops_env)

        assert main(["project", "seal", "-m", "vertex-first"]) == 0
        conn = sqlite3.connect(_db(loops_env))
        assert conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1

    def test_session_close_shape(self, loops_env):
        """The SessionEnd hook shape: session bookkeeping fact, then seal.
        Both land inside the sealed window; the chain verifies."""
        _write_vertex(loops_env)

        assert main([
            "emit", "project", "session",
            "name=kyle/loops-claude", "status=closed",
        ]) == 0
        assert main([
            "seal", "project", "-m", "session close: kyle/loops-claude",
        ]) == 0

        from atoms import Fact
        from engine import SqliteStore

        store = SqliteStore(
            path=_db(loops_env),
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        )
        report = store.verify_chain()
        assert report["ok"] is True
        assert report["chained"] == 1
        assert report["covered_facts"] == 2  # session fact + seal reason
        assert report["uncovered_facts"] == 0
