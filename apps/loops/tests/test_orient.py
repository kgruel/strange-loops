from __future__ import annotations

import sqlite3
from pathlib import Path

from loops.main import main


def _write_vertex(tmp_path: Path, *, name: str = "project", store_name: str | None = None) -> Path:
    vdir = tmp_path / name
    vdir.mkdir(parents=True)
    vertex_path = vdir / f"{name}.vertex"
    store_name = store_name or f"{name}.db"
    vertex_path.write_text(
        f'name "{name}"\n'
        f'store "./data/{store_name}"\n'
        "observers {\n"
        "  alice { }\n"
        "  bob { }\n"
        "}\n"
        "loops {\n"
        '  thread   { fold { items "by" "name" } }\n'
        '  friction { fold { items "by" "name" } }\n'
        '  decision { fold { items "by" "topic" } }\n'
        '  seal     { fold { items "collect" 10 } }\n'
        '  boundary when="seal"\n'
        "}\n"
    )
    return vertex_path


def _store_db(vertex_path: Path) -> Path:
    return next((vertex_path.parent / "data").glob("*.db"))


def _write_combine_vertex(tmp_path: Path, name: str, children: list[Path]) -> Path:
    vertex_path = tmp_path / f"{name}.vertex"
    entries = "".join(f'  vertex "{child}"\n' for child in children)
    vertex_path.write_text(f'name "{name}"\ncombine {{\n{entries}}}\n')
    return vertex_path


def test_orient_counts_open_work_and_warns_on_undeclared_seals(tmp_path, monkeypatch, capsys):
    vertex_path = _write_vertex(tmp_path)
    monkeypatch.chdir(vertex_path.parent)
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))

    assert main(["emit", str(vertex_path), "thread", "name=t1", "status=open", "message=thread one", "--observer", "alice"]) == 0
    assert main(["emit", str(vertex_path), "thread", "name=t2", "status=adopted", "message=thread two", "--observer", "bob"]) == 0
    assert main(["emit", str(vertex_path), "friction", "name=f1", "status=open", "message=friction one", "--observer", "alice"]) == 0
    assert main(["emit", str(vertex_path), "decision", "topic=design/seed", "message=decision one", "--observer", "alice"]) == 0
    assert main(["seal", str(vertex_path), "-m", "sealed by undeclared observer", "--observer", "carol"]) == 0

    # Pin "now" so the moved window covers the stored facts regardless of wall clock.
    conn = sqlite3.connect(_store_db(vertex_path))
    try:
        last_ts = conn.execute("SELECT MAX(ts) FROM facts").fetchone()[0]
    finally:
        conn.close()
    monkeypatch.setattr("loops.commands.orient.time.time", lambda: float(last_ts) + 60.0)

    assert main(["orient", str(vertex_path)]) == 0
    out = capsys.readouterr().out

    assert "== loops orient ==" in out
    assert "last seal: sealed by undeclared observer" in out
    assert "open: 1 threads · 1 frictions · 1 adopted-practices" in out
    assert "warning: 1 seal by undeclared observer carol" in out
    assert "declare in observers{} or seal as a declared observer" in out
    assert "[thread] t1: thread one" in out
    assert "[friction] f1: friction one" in out
    assert "[decision] design/seed: decision one" in out
    assert "open: 0 threads · 0 frictions" not in out


def test_orient_combined_vertex_uses_combined_seal_history(tmp_path):
    child_a = _write_vertex(tmp_path, name="alpha")
    child_b = _write_vertex(tmp_path, name="beta")
    parent = _write_combine_vertex(tmp_path, "portfolio", [child_a, child_b])

    assert main(["emit", str(child_a), "thread", "name=t1", "status=open", "message=alpha thread", "--observer", "alice"]) == 0
    assert main(["emit", str(child_b), "friction", "name=f1", "status=open", "message=beta friction", "--observer", "bob"]) == 0
    assert main(["seal", str(child_b), "-m", "beta seal", "--observer", "carol"]) == 0

    from engine import vertex_facts
    from loops.commands.orient import build_orient_summary, render_orient

    last_ts = max(fact["ts"].timestamp() for fact in vertex_facts(parent, 0.0, 4102444800.0))
    text = render_orient(build_orient_summary(parent, now_ts=last_ts + 60.0))

    assert "last seal: beta seal" in text
    assert "open: 1 threads · 1 frictions · 0 adopted-practices" in text
    assert "warning: 1 seal by undeclared observer carol" in text
