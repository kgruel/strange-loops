"""Emit-side cross-store refs: topology resolution plus unresolved typed pins."""

from __future__ import annotations

import argparse
from pathlib import Path

from engine import vertex_fold
from engine.store_reader import StoreReader
from loops.main import cmd_emit
from loops.surface import project


def _ns(kind: str, parts: list[str], *, strict: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        vertex=None,
        kind=kind,
        parts=parts,
        observer="",
        dry_run=False,
        strict=strict,
        quiet=False,
        verbose=0,
        json=False,
        declare_observer=False,
        stdin=None,
        file=None,
    )


def _emit(vpath: Path, kind: str, *, strict: bool = False, **payload: str) -> int:
    return cmd_emit(
        _ns(kind, [f"{key}={value}" for key, value in payload.items()], strict=strict),
        vertex_path=vpath,
    )


def _latest_payload(store_path: Path, kind: str) -> dict:
    with StoreReader(store_path) as reader:
        facts = reader.recent_facts(kind, 1)
    assert facts
    return facts[0]["payload"]


def _latest_id(store_path: Path, kind: str) -> str:
    with StoreReader(store_path) as reader:
        facts = reader.recent_facts(kind, 1)
    assert facts
    return facts[0]["id"]


def _write_cross_store_topology(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    home = tmp_path / "home"
    home.mkdir()

    painted_dir = tmp_path / "painted"
    painted_dir.mkdir()
    painted_v = painted_dir / "painted.vertex"
    painted_v.write_text(
        'name "painted"\n'
        'store "./painted.db"\n'
        'loops { observation { fold { items "by" "topic" } } }\n'
    )

    loops_dir = tmp_path / "loops"
    loops_dir.mkdir()
    loops_v = loops_dir / "loops.vertex"
    loops_v.write_text(
        'name "loops"\n'
        'store "./loops.db"\n'
        'loops { decision { fold { items "by" "topic" } } }\n'
    )

    agg_dir = home / "project"
    agg_dir.mkdir()
    agg_v = agg_dir / "project.vertex"
    agg_v.write_text(
        'name "project"\n'
        "combine {\n"
        f'  vertex "{painted_v}" as="painted"\n'
        f'  vertex "{loops_v}" as="loops"\n'
        "}\n"
    )

    return painted_v, painted_dir / "painted.db", loops_v, loops_dir / "loops.db", agg_v


def test_cross_store_ref_resolves_through_config_topology(
    tmp_path, monkeypatch, capsys
):
    painted_v, painted_store, loops_v, loops_store, _agg_v = _write_cross_store_topology(
        tmp_path
    )
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    assert _emit(
        loops_v,
        "decision",
        topic="architecture/spine",
        message="load-bearing",
    ) == 0
    target_id = _latest_id(loops_store, "decision")
    capsys.readouterr()

    assert _emit(
        painted_v,
        "observation",
        topic="obs/cross-store",
        ref="decision:architecture/spine",
        message="pins loops decision",
    ) == 0

    err = capsys.readouterr().err
    payload = _latest_payload(painted_store, "observation")
    assert payload["ref"] == "decision:architecture/spine"
    assert payload["ref_ref"] == target_id
    assert "_unresolved_refs" not in payload
    assert "refs: 1 resolved" in err
    assert "did not resolve" not in err


def test_cross_store_ref_to_unmounted_store_persists_typed_unresolved_pin(
    tmp_path, monkeypatch, capsys
):
    painted_v, painted_store, _loops_v, _loops_store, _agg_v = _write_cross_store_topology(
        tmp_path
    )
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    assert _emit(
        painted_v,
        "observation",
        topic="obs/offline",
        ref="decision:architecture/offline",
        message="target store is not mounted",
    ) == 0

    err = capsys.readouterr().err
    payload = _latest_payload(painted_store, "observation")
    assert "ref_ref" not in payload
    assert payload["_unresolved_refs"] == [
        {
            "field": "ref",
            "addr": "decision:architecture/offline",
            "kind": "decision",
            "key": "architecture/offline",
        }
    ]
    assert "typed unresolved pin" in err
    assert "dropped" not in err


def test_unresolved_ref_lights_up_when_target_store_is_later_mounted(
    tmp_path, monkeypatch, capsys
):
    painted_v, painted_store, loops_v, _loops_store, agg_v = _write_cross_store_topology(
        tmp_path
    )
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    assert _emit(
        painted_v,
        "observation",
        topic="obs/deferred",
        ref="decision:architecture/later",
        message="target will appear later",
    ) == 0
    payload = _latest_payload(painted_store, "observation")
    assert "_unresolved_refs" in payload
    capsys.readouterr()

    assert _emit(
        loops_v,
        "decision",
        topic="architecture/later",
        message="now mounted",
    ) == 0

    surface = project(vertex_fold(agg_v))
    target = next(
        row
        for row in surface.rows
        if row.kind == "decision" and row.key == "architecture/later"
    )
    assert target.inbound == 1
    assert target.inbound_predicates == (("ref", 1),)


def test_local_ref_behavior_unchanged(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    vpath = tmp_path / "local.vertex"
    vpath.write_text(
        'name "local"\n'
        'store "./local.db"\n'
        "loops {\n"
        '  decision { fold { items "by" "topic" } }\n'
        '  observation { fold { items "by" "topic" } }\n'
        "}\n"
    )
    store = tmp_path / "local.db"

    assert _emit(vpath, "decision", topic="local/ref", message="target") == 0
    target_id = _latest_id(store, "decision")
    capsys.readouterr()

    assert _emit(
        vpath,
        "observation",
        topic="obs/local",
        ref="decision:local/ref",
    ) == 0

    err = capsys.readouterr().err
    payload = _latest_payload(store, "observation")
    assert payload["ref_ref"] == target_id
    assert "_unresolved_refs" not in payload
    assert "refs: 1 resolved" in err
    assert "typed unresolved pin" not in err


def test_strict_refuses_unresolved_cross_store_pin(tmp_path, monkeypatch, capsys):
    painted_v, painted_store, _loops_v, _loops_store, _agg_v = _write_cross_store_topology(
        tmp_path
    )
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    rc = _emit(
        painted_v,
        "observation",
        strict=True,
        topic="obs/strict",
        ref="decision:architecture/offline",
    )

    err = capsys.readouterr().err
    assert rc == 2
    assert "ERROR: ref 'decision:architecture/offline' did not resolve" in err
    assert "stored:" not in err
    assert not painted_store.exists()


def test_ambiguous_ambient_topology_stores_pin_instead_of_guessing(
    tmp_path, monkeypatch, capsys
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("LOOPS_HOME", str(home))
    monkeypatch.chdir(tmp_path)

    painted_dir = tmp_path / "painted"
    painted_dir.mkdir()
    painted_v = painted_dir / "painted.vertex"
    painted_v.write_text(
        'name "painted"\n'
        'store "./painted.db"\n'
        'loops { observation { fold { items "by" "topic" } } }\n'
    )
    painted_store = painted_dir / "painted.db"

    loops_a_dir = tmp_path / "loops-a"
    loops_a_dir.mkdir()
    loops_a_v = loops_a_dir / "loops.vertex"
    loops_a_v.write_text(
        'name "loops-a"\n'
        'store "./loops-a.db"\n'
        'loops { decision { fold { items "by" "topic" } } }\n'
    )

    loops_b_dir = tmp_path / "loops-b"
    loops_b_dir.mkdir()
    loops_b_v = loops_b_dir / "loops.vertex"
    loops_b_v.write_text(
        'name "loops-b"\n'
        'store "./loops-b.db"\n'
        'loops { decision { fold { items "by" "topic" } } }\n'
    )

    for name, loops_v in (("alpha", loops_a_v), ("beta", loops_b_v)):
        agg_dir = home / name
        agg_dir.mkdir()
        (agg_dir / f"{name}.vertex").write_text(
            f'name "{name}"\n'
            "combine {\n"
            f'  vertex "{painted_v}" as="painted"\n'
            f'  vertex "{loops_v}" as="loops"\n'
            "}\n"
        )

    assert _emit(
        loops_a_v,
        "decision",
        topic="architecture/ambiguous",
        message="one possible target",
    ) == 0
    capsys.readouterr()

    assert _emit(
        painted_v,
        "observation",
        topic="obs/ambiguous",
        ref="decision:architecture/ambiguous",
    ) == 0

    err = capsys.readouterr().err
    payload = _latest_payload(painted_store, "observation")
    assert "ref_ref" not in payload
    assert payload["_unresolved_refs"] == [
        {
            "field": "ref",
            "addr": "decision:architecture/ambiguous",
            "kind": "decision",
            "key": "architecture/ambiguous",
        }
    ]
    assert "typed unresolved pin" in err
