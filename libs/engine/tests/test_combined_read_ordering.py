"""_combined_read under a DECLARED ordering (Cut C, Q2).

'arrival' is single-store-only: a combine-of-one reads on the arrival axis by
default, an aggregate of several reads on the ``(ts, id)`` lens, and declaring
``Arrival()`` on an aggregate is refused.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from atoms import Arrival, ByKey, OrderingError

from engine.vertex_reader import _combined_read, resolve_ordering

from .test_vertex_reader import _seed_facts, _setup_combine_env


# Backdated ts against append order: fact ids ascend with rowid, ts does NOT.
# Row 0 lands first but carries the LATEST ts, so arrival order and (ts, id)
# order disagree on every adjacent pair — the fixture discriminates.
_INTERLEAVED = [
    {"id": "F0", "kind": "decision", "ts": 4000.0, "payload": {"topic": "t", "seq": 0}},
    {"id": "F1", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "seq": 1}},
    {"id": "F2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "seq": 2}},
    {"id": "F3", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t", "seq": 3}},
]

_ARRIVAL_IDS = ["F0", "F1", "F2", "F3"]
_TS_IDS = ["F1", "F3", "F2", "F0"]


def _single_member_vertex(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """A combine-of-ONE aggregate — the shape the old rowid sort served."""
    home = tmp_path / "loops_home"
    solo_dir = home / "solo"
    solo_dir.mkdir(parents=True)
    (solo_dir / "solo.vertex").write_text(
        'name "solo"\nstore "./store.db"\n'
        'loops {\n  decision { fold { items "collect" 10 } }\n}\n'
    )
    combine = tmp_path / "combined.vertex"
    combine.write_text(
        'name "combined"\ncombine {\n    vertex "solo"\n}\n'
        'loops {\n  decision { fold { items "collect" 10 } }\n}\n'
    )
    monkeypatch.setenv("LOOPS_HOME", str(home))
    return combine, solo_dir / "store.db"


def _fold_ids(vertex_path: Path, **kwargs) -> list[str]:
    """Replay ids in the order _combined_read handed them to the fold."""
    from engine.compiler import compile_vertex
    from engine.declaration import load_declaration

    ast = load_declaration(vertex_path)
    _, payloads = _combined_read(
        ast, vertex_path, compile_vertex(ast), return_payloads=True, **kwargs
    )
    return [p["_id"] for p in payloads["decision"]]


def _rowid_ids_by_direct_sqlite(db_path: Path) -> list[str]:
    """The OLD single-store semantics, read straight off sqlite.

    Independent of production code: the pin compares against this, not against
    anything the new path computes.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT id, rowid FROM facts").fetchall()
    finally:
        conn.close()
    rows.sort(key=lambda r: r[1])
    return [r[0] for r in rows]


class TestSingleStoreArrivalEquivalence:
    """GATE item 3: single-store Arrival() ≡ the old rowid sequence."""

    def test_the_fixture_discriminates_arrival_from_event_time(self, tmp_path, monkeypatch):
        """Guard on the pin below: ts order must NOT equal arrival order."""
        _, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _rowid_ids_by_direct_sqlite(db) == _ARRIVAL_IDS
        conn = sqlite3.connect(str(db))
        try:
            ts_order = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY ts, id")]
        finally:
            conn.close()
        assert ts_order == _TS_IDS
        assert ts_order != _ARRIVAL_IDS

    def test_declared_arrival_reproduces_the_old_rowid_sequence(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        expected = _rowid_ids_by_direct_sqlite(db)
        assert _fold_ids(vpath, ordering=Arrival()) == expected

    def test_the_single_store_default_is_arrival(self, tmp_path, monkeypatch):
        """No declared ordering ≡ declared Arrival() ≡ the old sequence."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath) == _rowid_ids_by_direct_sqlite(db) == _ARRIVAL_IDS

    def test_a_single_store_may_declare_bykey_instead(self, tmp_path, monkeypatch):
        """Arrival is the default, not the only option, on one store."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=ByKey("ts")) == _TS_IDS


class TestAggregateOrdering:
    """GATE item 4: aggregates are ByKey; Arrival() on one refuses loudly."""

    def test_the_aggregate_default_is_event_time(self, tmp_path, monkeypatch):
        vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"id": "A1", "kind": "decision", "ts": 4000.0, "payload": {"topic": "t"}},
            {"id": "A2", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t"}},
        ])
        _seed_facts(beta_db, [
            {"id": "B1", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t"}},
            {"id": "B2", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
        ])

        assert _fold_ids(vpath) == ["A2", "B2", "B1", "A1"]

    def test_declaring_arrival_on_an_aggregate_refuses(self, tmp_path, monkeypatch):
        vpath, alpha_db, beta_db = _setup_combine_env(tmp_path, monkeypatch)
        _seed_facts(alpha_db, [
            {"id": "A1", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t"}},
        ])
        _seed_facts(beta_db, [
            {"id": "B1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
        ])

        with pytest.raises(OrderingError) as excinfo:
            _fold_ids(vpath, ordering=Arrival())

        message = str(excinfo.value)
        # Names the REASON...
        assert "dense per-log" in message
        assert "no cross-store" in message or "has no cross-store" in message
        # ...and the ALTERNATIVE.
        assert "ByKey" in message


class TestResolveOrdering:
    """The one place the Q2 defaults and the refusal are defined."""

    def test_defaults(self):
        assert resolve_ordering(None, single_store=True) == Arrival()
        assert resolve_ordering(None, single_store=False) == ByKey("ts")

    def test_declared_orderings_pass_through(self):
        assert resolve_ordering(Arrival(), single_store=True) == Arrival()
        assert resolve_ordering(ByKey("ts"), single_store=True) == ByKey("ts")
        assert resolve_ordering(ByKey("seq"), single_store=False) == ByKey("seq")

    def test_arrival_on_an_aggregate_refuses(self):
        with pytest.raises(OrderingError, match="dense per-log"):
            resolve_ordering(Arrival(), single_store=False)


class TestRowAccessors:
    """Column-backed keys read off the tuple; payload keys cost a parse."""

    def test_bykey_on_a_payload_field(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, [
            {"id": "P0", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "n": 3}},
            {"id": "P1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t", "n": 1}},
            {"id": "P2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "n": 2}},
        ])

        assert _fold_ids(vpath, ordering=ByKey("n")) == ["P1", "P2", "P0"]

    def test_bykey_on_id_reads_the_id_column(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=ByKey("id")) == ["F0", "F1", "F2", "F3"]

    def test_a_fact_missing_the_declared_key_is_not_in_the_projection(
        self, tmp_path, monkeypatch
    ):
        """Exclusion-by-declaration reaches the FOLD INPUT, not just the page."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, [
            {"id": "K0", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t", "n": 2}},
            {"id": "K1", "kind": "decision", "ts": 2000.0, "payload": {"topic": "t"}},
            {"id": "K2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t", "n": 1}},
        ])

        assert _fold_ids(vpath, ordering=ByKey("n")) == ["K2", "K0"]

    @pytest.mark.parametrize("column", ["kind", "observer", "origin"])
    def test_non_envelope_columns_resolve_against_the_payload(
        self, column: str, tmp_path, monkeypatch
    ):
        """Only ts/id are envelope keys — the other columns are NOT candidates.

        The family rule (SPEC §9, ``atoms.resolve_key_field``) envelope-resolves
        ``ts`` and ``id`` and nothing else, so ``ByKey('kind')`` here is an
        ordinary declared key that happens to share a column's name. It reads
        the PAYLOAD: the one fact carrying it in its payload is the whole
        projection, and the three that don't are excluded by non-membership.

        The fixture discriminates. Resolving the column instead would put every
        fact in the projection (each row's envelope always carries all three),
        ordered ``(column, id ASC)`` — and since these facts share a kind,
        observer and origin, that is all four ids in id order.
        """
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, [
            {"id": "C0", "kind": "decision", "ts": 1000.0, "payload": {"topic": "t"}},
            {"id": "C1", "kind": "decision", "ts": 2000.0,
             "payload": {"topic": "t", column: "in-the-payload"}},
            {"id": "C2", "kind": "decision", "ts": 3000.0, "payload": {"topic": "t"}},
            {"id": "C3", "kind": "decision", "ts": 4000.0, "payload": {"topic": "t"}},
        ])

        assert _fold_ids(vpath, ordering=ByKey(column)) == ["C1"]


class TestTheFetchMaterializesNativeOrder:
    """The row source, not the ordering, owns native order.

    A plain single-table SELECT happens to come back in rowid order today, so a
    fixture built on a real store CANNOT tell the rowid sort apart from sqlite's
    incidental scan order — drop the sort and the equivalence pin still passes.
    That would leave Arrival() resting on an sqlite implementation detail. These
    pin the contract directly: whatever order the query hands back, one store
    yields arrival order and several yield rows as read.
    """

    class _StubConn:
        def __init__(self, rows):
            self._rows = rows
            self.sql = None

        def execute(self, sql, params=()):
            self.sql = sql
            return self

        def fetchall(self):
            return list(self._rows)

    @staticmethod
    def _row(fact_id: str, ts: float, rowid: int) -> tuple:
        return (fact_id, "decision", ts, "test", "", "{}", rowid)

    def test_one_store_is_sorted_into_arrival_order(self):
        from engine.vertex_reader import _fetch_combined_rows

        shuffled = [
            self._row("F2", 3000.0, 3),
            self._row("F0", 4000.0, 1),
            self._row("F3", 2000.0, 4),
            self._row("F1", 1000.0, 2),
        ]
        rows = _fetch_combined_rows(self._StubConn(shuffled), ["main"], None, Arrival())
        assert [r[0] for r in rows] == _ARRIVAL_IDS
        assert [r[6] for r in rows] == [1, 2, 3, 4]

    def test_one_store_under_by_key_is_left_as_read(self):
        """ByKey totalizes on (K, id); a rowid sort first would be discarded."""
        from engine.vertex_reader import _fetch_combined_rows

        shuffled = [
            self._row("F2", 3000.0, 3),
            self._row("F0", 4000.0, 1),
            self._row("F3", 2000.0, 4),
            self._row("F1", 1000.0, 2),
        ]
        rows = _fetch_combined_rows(
            self._StubConn(shuffled), ["main"], None, ByKey("ts")
        )
        assert [r[0] for r in rows] == ["F2", "F0", "F3", "F1"]

    def test_several_stores_are_left_as_read(self):
        """rowid is per-store across members, so sorting on it would be a lie."""
        from engine.vertex_reader import _fetch_combined_rows

        # Rowids chosen so a rowid sort would REORDER these — otherwise the
        # assertion could not tell "left alone" from "sorted".
        as_read = [
            self._row("A1", 4000.0, 2),
            self._row("B1", 1000.0, 1),
            self._row("A2", 3000.0, 3),
        ]
        assert [r[0] for r in sorted(as_read, key=lambda r: r[6])] != ["A1", "B1", "A2"]

        rows = _fetch_combined_rows(
            self._StubConn(as_read), ["main", "s1"], None, ByKey("ts")
        )
        assert [r[0] for r in rows] == ["A1", "B1", "A2"]

    def test_until_ts_reaches_the_sql(self):
        from engine.vertex_reader import _fetch_combined_rows

        conn = self._StubConn([])
        _fetch_combined_rows(conn, ["main"], 2500.0, Arrival())
        assert "WHERE ts <= ?" in conn.sql
        conn2 = self._StubConn([])
        _fetch_combined_rows(conn2, ["main"], None, Arrival())
        assert "WHERE" not in conn2.sql


class TestUntilTsStillCaps:
    """The event-time cursor is orthogonal to the declared ordering."""

    def test_until_ts_caps_under_arrival(self, tmp_path, monkeypatch):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED)

        assert _fold_ids(vpath, ordering=Arrival(), until_ts=2500.0) == ["F1", "F3"]

    def test_payload_shape_is_untouched(self, tmp_path, monkeypatch):
        """The ordering rewrite did not disturb the _-prefixed row projection."""
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        _seed_facts(db, _INTERLEAVED[:1])

        from engine.compiler import compile_vertex
        from engine.declaration import load_declaration

        ast = load_declaration(vpath)
        _, payloads = _combined_read(
            ast, vpath, compile_vertex(ast), return_payloads=True
        )
        p = payloads["decision"][0]
        assert p["_id"] == "F0"
        assert p["_ts"] == 4000.0
        assert p["_observer"] == "test"
        assert p["_origin"] == ""
        assert p["seq"] == 0
        assert json.loads(json.dumps(p))  # plain JSON, no tuple leakage


class TestNonMappingPayloads:
    """A payload that is not a mapping has no fields — non-member, not a crash.

    `Fact` permits any JSON payload and `SqliteStore` persists one, so these
    build the member store through the REAL append path rather than seeding
    rows: the point is that an ordinary emitter can produce the record that
    used to take the combined read down with an AttributeError.
    """

    @staticmethod
    def _member_store(db_path: Path, payloads: list) -> None:
        from atoms import Fact

        from engine import SqliteStore

        store = SqliteStore(
            path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        )
        for i, payload in enumerate(payloads):
            store.append(
                Fact(kind="decision", ts=float(i + 1), observer="test", payload=payload)
            )
        store.close()

    def test_a_scalar_payload_fact_is_excluded_from_a_payload_key_projection(
        self, tmp_path, monkeypatch
    ):
        vpath, db = _single_member_vertex(tmp_path, monkeypatch)
        self._member_store(db, ["raw", {"topic": "t", "n": 1}])

        from engine.compiler import compile_vertex
        from engine.declaration import load_declaration

        ast = load_declaration(vpath)
        _, payloads = _combined_read(
            ast, vpath, compile_vertex(ast), return_payloads=True, ordering=ByKey("n")
        )

        assert [p["n"] for p in payloads["decision"]] == [1]

    def test_an_envelope_key_still_orders_scalar_payload_rows(self):
        """ts is read off the row, so payload shape cannot exclude the fact.

        Pinned at the ordering layer rather than through the fold: the fold body
        merges `_id`/`_ts` INTO the payload dict, so it cannot consume a
        non-mapping payload at all. That limitation predates the declared
        ordering and is not what this fix is about — what is pinned here is that
        the ordering layer no longer raises on the way past.
        """
        from atoms import totalize

        from engine.vertex_reader import _row_field, _row_id

        rows = [
            ("id-b", "decision", 2.0, "test", "", json.dumps("raw"), 2),
            ("id-a", "decision", 1.0, "test", "", json.dumps(["x"]), 1),
        ]
        ordered = totalize(rows, ByKey("ts"), get_field=_row_field, get_id=_row_id)

        assert [r[0] for r in ordered] == ["id-a", "id-b"]

    def test_the_row_accessor_matches_the_mapping_one(self):
        """One family rule, two spellings that must agree on every payload."""
        from atoms import resolve_key_field

        from engine.vertex_reader import _row_field

        for payload in ("raw", 7, ["a"], None, {"n": 1}):
            row = ("id-x", "decision", 1.0, "test", "", json.dumps(payload), 1)
            record = {"id": "id-x", "ts": 1.0, "payload": payload}
            assert _row_field(row, "n") == resolve_key_field(record, "n")
