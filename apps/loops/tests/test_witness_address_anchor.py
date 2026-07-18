"""resolve_at_address preserves the snapped tick as the anchor (finding 7a wiring).

The engine mechanism (resolve_witness_position anchor= override) is covered in
libs/engine/tests; this proves the CLI address resolver WIRES it: a wall-clock
snap where a later tick seals the same fact_cursor must still report the FLOOR
tick as the position's anchor, not the later one a re-derivation would pick.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact

from engine.sqlite_store import SqliteStore, gen_id
from loops.cli.witness_address import resolve_at_address


def _fresh(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _append(store: Path, ts: float) -> str:
    conn = sqlite3.connect(str(store))
    fid = gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, 'decision', ?, 'kyle', '', ?, NULL)",
        (fid, ts, json.dumps({"topic": "a"})),
    )
    conn.commit()
    conn.close()
    return fid


def _tick(store: Path, name: str, ts: float, cursor: str) -> None:
    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, fact_cursor) "
        "VALUES (?, ?, ?, 0.0, '', '{}', ?)",
        (gen_id(), name, ts, cursor),
    )
    conn.commit()
    conn.close()


def test_wallclock_anchor_names_the_floor_tick(tmp_path):
    store = tmp_path / "t.db"
    _fresh(store)
    floor_ts = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    later_ts = datetime(2026, 3, 1, tzinfo=UTC).timestamp()
    f1 = _append(store, floor_ts - 60)
    _tick(store, "floor", floor_ts, f1)
    _tick(store, "later", later_ts, f1)  # after the mark, same cursor

    pos = resolve_at_address(store, "2026-02-01")  # mark between the two ticks
    assert pos.anchor is not None
    assert pos.anchor.name == "floor"
    assert pos.fact_id == f1
