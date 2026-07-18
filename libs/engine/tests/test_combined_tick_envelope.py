"""Combined tick drill carries real per-member envelopes (0.8.0 session 1, E3/N4).

Before 0.8.0 an aggregate `vertex_ticks(with_envelope=True)` returned a blank
`chained=False` envelope for EVERY tick — so an aggregate `--ticks` drill could
never anchor, even for chained member ticks. This proves the honest
pass-through: each member's real envelope (chain / signature / fact_cursor,
resolved against that member's own store) rides through, tagged with `member`
so a consumer knows which store the cursor is a witness handle into (A1/A9 —
witness order is per-member, no shared aggregate order exists).

Scratch stores in tmp_path only; never touches a live store.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from atoms import Fact

from engine import vertex_ticks
from engine.sqlite_store import SqliteStore, gen_id

_VERTEX_KDL = '''name "{name}"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
'''


def _fresh_store(store: Path) -> None:
    SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()


def _member(tmp_path: Path, name: str, tick_ts: float) -> tuple[Path, str]:
    """A member vertex+store with one chained tick; returns (vertex_path, cursor_id)."""
    store = tmp_path / f"{name}.db"
    vpath = tmp_path / f"{name}.vertex"
    vpath.write_text(_VERTEX_KDL.format(name=name, store=store))
    _fresh_store(store)
    conn = sqlite3.connect(str(store))
    cursor_id = gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, 'decision', ?, 'kyle', '', ?, NULL)",
        (cursor_id, tick_ts - 1, json.dumps({"topic": name})),
    )
    # A chained tick (non-null window_hash) sealing that fact.
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, "
        "window_start, fact_cursor, window_hash) "
        "VALUES (?, ?, ?, 0.0, '', '{}', '', ?, 'deadbeef')",
        (gen_id(), name, tick_ts, cursor_id),
    )
    conn.commit()
    conn.close()
    return vpath, cursor_id


def test_combined_ticks_pass_member_envelopes_through(tmp_path):
    a_v, a_cursor = _member(tmp_path, "alpha", tick_ts=200.0)
    b_v, b_cursor = _member(tmp_path, "beta", tick_ts=100.0)

    agg = tmp_path / "agg.vertex"
    agg.write_text(f'name "agg"\ncombine {{\n  vertex "{a_v}"\n  vertex "{b_v}"\n}}\n')

    pairs = vertex_ticks(agg, 0.0, 1e9, with_envelope=True)
    assert len(pairs) == 2
    # Merge-sorted by ts across members: beta (100) then alpha (200).
    assert [t.name for t, _ in pairs] == ["beta", "alpha"]

    env_by_member = {env["member"]: env for _, env in pairs}
    assert set(env_by_member) == {"alpha", "beta"}
    # Real per-member envelopes — chained, with the member's own fact_cursor,
    # NOT the old blank placeholder.
    assert env_by_member["alpha"]["chained"] is True
    assert env_by_member["alpha"]["fact_cursor"] == a_cursor
    assert env_by_member["beta"]["fact_cursor"] == b_cursor


def test_combined_ticks_without_envelope_unchanged(tmp_path):
    # The fast path (no envelope) stays a plain Tick list — no member tagging.
    a_v, _ = _member(tmp_path, "alpha", tick_ts=200.0)
    agg = tmp_path / "agg.vertex"
    agg.write_text(f'name "agg"\ncombine {{\n  vertex "{a_v}"\n}}\n')
    ticks = vertex_ticks(agg, 0.0, 1e9)
    assert [t.name for t in ticks] == ["alpha"]


def _member_in(
    dir_path: Path, vname: str, store_stem: str, tick_ts: float
) -> tuple[Path, str]:
    """A member whose STORE stem is ``store_stem`` under ``dir_path`` — lets two
    members share a store stem (e.g. a/events.db, b/events.db)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    store = dir_path / f"{store_stem}.db"
    vpath = dir_path / f"{vname}.vertex"
    vpath.write_text(_VERTEX_KDL.format(name=vname, store=store))
    _fresh_store(store)
    conn = sqlite3.connect(str(store))
    cursor_id = gen_id()
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, 'decision', ?, 'kyle', '', ?, NULL)",
        (cursor_id, tick_ts - 1, json.dumps({"topic": vname})),
    )
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload, "
        "window_start, fact_cursor, window_hash) "
        "VALUES (?, ?, ?, 0.0, '', '{}', '', ?, 'deadbeef')",
        (gen_id(), vname, tick_ts, cursor_id),
    )
    conn.commit()
    conn.close()
    return vpath, cursor_id


def test_combined_ticks_member_labels_are_collision_free(tmp_path):
    # Review finding 3: a/events.db and b/events.db both stem to "events".
    # Member labels must stay DISTINCT so a consumer resolves each fact_cursor
    # against the right member store.
    a_v, a_cursor = _member_in(tmp_path / "a", "amember", "events", tick_ts=200.0)
    b_v, b_cursor = _member_in(tmp_path / "b", "bmember", "events", tick_ts=100.0)

    agg = tmp_path / "agg.vertex"
    agg.write_text(f'name "agg"\ncombine {{\n  vertex "{a_v}"\n  vertex "{b_v}"\n}}\n')

    pairs = vertex_ticks(agg, 0.0, 1e9, with_envelope=True)
    assert len(pairs) == 2
    members = [env["member"] for _, env in pairs]
    assert len(set(members)) == 2, f"colliding member labels: {members}"
    # Each distinct label maps to a distinct member's cursor.
    label_by_cursor = {env["fact_cursor"]: env["member"] for _, env in pairs}
    assert label_by_cursor[a_cursor] != label_by_cursor[b_cursor]
