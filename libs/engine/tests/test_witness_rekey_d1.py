"""Slice D / WP-2 — the witness re-key (D1) gates.

`docs/scratch/arrival-sliceD/design-proposal.md` §D1 re-keys `WitnessPosition`
off the projection rowid and onto the arrival coordinate, under the ratified
RECORD-GRANULAR cutoff. These are the gates that make each ruled property a
test rather than a review note.

- G-D1-2: the DONE-CRITERIA verbatim strings. The three
  ``WitnessAggregateUnsupported`` raise-site messages and both A10
  (``WitnessLineageMismatch``) refusal messages are pinned BYTE-IDENTICAL —
  not by substring, which is what let the re-key edit them unnoticed.
- G-D1-3: the ruled cost of record granularity — a mid-batch position
  round-trips through ``seq:N`` to the *record*, not to the row.
- G-D1-4: same-path store replacement raises the separately-typed
  ``WitnessAxisMismatch``; the A10 and unadopted refusals are untouched, and
  a same-lineage sibling store still RE-RESOLVES rather than refusing.
- G-D1-5: position equivalence — on an un-permuted store the arrival-resolved
  prefix selects exactly the row-set rowid selection did; on a permuted store
  arrival order governs and rowid order does not. ``durable_handle`` output is
  unchanged by the re-key.
- G-D1-6: a reversed ``--diff`` attributes the baseline identically, via the
  engine's ``baseline`` field rather than an app-side coordinate comparison.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import (
    DECL_KIND_DEFINED,
    DECL_KIND_RETIRED,
    Change,
    vertex_to_documents,
)

from engine.arrival import ArrivalLog
from engine.arrival_store import ARRIVAL_LINEAGE_KEY, ArrivalStore
from engine.sqlite_store import SqliteStore, ensure_coordinate_schema, gen_id
from engine.tick import Tick
from engine.vertex_reader import vertex_fold, vertex_query_facts
from engine.witness import (
    GENESIS_SENTINEL,
    WitnessAggregateUnsupported,
    WitnessAxisMismatch,
    WitnessLineageMismatch,
    WitnessPosition,
    diff_interval_report,
    durable_handle,
    resolve_seq,
    resolve_witness_position,
    verify_position_for_store,
)

_SRC = (
    'name "x"\nstore "./s.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n'
    '  b { fold { n "inc" } }\n}\n'
)


def _tick_signer(digest: str) -> str:
    return hashlib.sha256(digest.encode()).hexdigest()


def _arrival_store_with_a_batch(dirpath: Path, keys, signer) -> tuple[Path, Path]:
    """An arrival-canonical store whose _decl ceremony is a genuine multi-row
    batch record — the mid-batch case G-D1-3 and G-D1-4 both need."""
    dirpath.mkdir(parents=True, exist_ok=True)
    log = ArrivalLog.mint(
        dirpath / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store: ArrivalStore = ArrivalStore(
        path=dirpath / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
        tick_signer=_tick_signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))
        store.append(Fact.of("note", "kyle", message="two"))
        store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(_SRC))],
            observer="kyle",
            fact_signer=signer,
        )
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
        )
        store.append(Fact.of("note", "kyle", message="three"))
        # TWO change rows, ONE batch record — one shared arrival ordinal.
        store.absorb_edit(
            [
                Change(kind=DECL_KIND_DEFINED, subject="a",
                       payload={"order": 0}, annotation="modified"),
                Change(kind=DECL_KIND_RETIRED, subject="b",
                       payload=None, annotation="removed"),
            ],
            observer="kyle",
            fact_signer=signer,
        )
        store.append(Fact.of("note", "kyle", message="four"))
    finally:
        store.close()
    return log.path, dirpath / "s.db"


def _meta(db: Path, key: str) -> str | None:
    """A store_meta read that tolerates a pre-adoption store (no table)."""
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute(
            "SELECT value FROM store_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()


def _set_meta(db: Path, **pairs: str) -> None:
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS store_meta (key TEXT PRIMARY KEY, value TEXT)"
        )
        for key, value in pairs.items():
            conn.execute(
                "INSERT OR REPLACE INTO store_meta (key, value) VALUES (?, ?)",
                (key, value),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# G-D1-2 — the verbatim strings
# ---------------------------------------------------------------------------


class TestG_D1_2_VerbatimRefusalStrings:
    """DONE-CRITERIA: ``WitnessAggregateUnsupported`` + A10 stay VERBATIM.

    Pinned as whole-string equality. The existing suites match these refusals
    by substring, which cannot see an edit to the rest of the sentence — and
    the re-key rewrote the surrounding prose of both modules.
    """

    VERTEX_FOLD_MESSAGE = (
        "vertex_fold: a witness position is per-store and cannot reconstruct "
        "a combine/discover aggregate fold — witness order is per-member "
        "(A1/A9). Fold a member store at its own position instead."
    )
    VERTEX_FACTS_MESSAGE = (
        "vertex_facts: a witness position is per-store and cannot select "
        "over a combine/discover aggregate — address a member store, or "
        "use as_of for a uniform event-time projection"
    )
    VERTEX_QUERY_FACTS_MESSAGE = (
        "vertex_query_facts: a witness cursor is per-store and cannot "
        "page over a combine/discover aggregate — no shared witness "
        "order exists across members (A1/A9). Address a member store "
        "directly."
    )
    A10_UNADOPTED_TEMPLATE = (
        "witness position (fact {fact_id!r}) was resolved against "
        "{source} but is being applied to {target} — an UNADOPTED handle "
        "is session-local to its own store (N1); its rowid means nothing "
        "here. Resolve the position against this store, or adopt the store "
        "to mint a portable lineage-qualified handle."
    )
    A10_LINEAGE_TEMPLATE = (
        "witness position (lineage {lineage}) was resolved against "
        "{source} and does not match this store's lineage "
        "({target_lineage}) at {target} — a lineage-qualified handle "
        "resolves only against its own lineage (A10). Address the correct "
        "store, or re-resolve the position here."
    )

    def _combine_vertex(self, tmp_path: Path) -> Path:
        """A combine vertex over a member vertex — the aggregate shape."""
        member_db = tmp_path / "member.db"
        SqliteStore(
            path=member_db, serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        ).close()
        member_v = tmp_path / "member.vertex"
        member_v.write_text(
            f'name "m"\nstore "{member_db}"\n'
            'loops { decision { fold { items "by" "topic" } } }\n'
        )
        vpath = tmp_path / "combo.vertex"
        vpath.write_text(f'name "agg"\ncombine {{\n  vertex "{member_v}"\n}}\n')
        return vpath

    def _a_position(self, tmp_path: Path) -> WitnessPosition:
        return WitnessPosition(
            fact_id="f1", arrival_lineage=None, ordinal=1, seq=1,
            lineage=None, unadopted=True, anchor=None,
            store=str((tmp_path / "somewhere.db").resolve()),
        )

    def test_vertex_fold_aggregate_message_is_byte_identical(self, tmp_path):
        vpath = self._combine_vertex(tmp_path)
        with pytest.raises(WitnessAggregateUnsupported) as exc:
            vertex_fold(vpath, at=self._a_position(tmp_path))
        assert str(exc.value) == self.VERTEX_FOLD_MESSAGE

    def test_vertex_facts_aggregate_message_is_byte_identical(self, tmp_path):
        from engine.vertex_reader import vertex_facts

        vpath = self._combine_vertex(tmp_path)
        with pytest.raises(WitnessAggregateUnsupported) as exc:
            vertex_facts(vpath, 0.0, 1e12, at=self._a_position(tmp_path))
        assert str(exc.value) == self.VERTEX_FACTS_MESSAGE

    def test_vertex_query_facts_aggregate_message_is_byte_identical(self, tmp_path):
        vpath = self._combine_vertex(tmp_path)
        with pytest.raises(WitnessAggregateUnsupported) as exc:
            vertex_query_facts(vpath, before=self._a_position(tmp_path))
        assert str(exc.value) == self.VERTEX_QUERY_FACTS_MESSAGE

    def test_a10_unadopted_message_is_byte_identical(self, tmp_path):
        source = tmp_path / "a.db"
        target = tmp_path / "b.db"
        for p in (source, target):
            SqliteStore(
                path=p, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
            ).close()
        pos = WitnessPosition(
            fact_id="f1", arrival_lineage=None, ordinal=1, seq=1,
            lineage=None, unadopted=True, anchor=None, store=str(source.resolve()),
        )
        with pytest.raises(WitnessLineageMismatch) as exc:
            verify_position_for_store(pos, target)
        assert str(exc.value) == self.A10_UNADOPTED_TEMPLATE.format(
            fact_id="f1", source=str(source.resolve()), target=str(target.resolve())
        )

    def test_a10_lineage_mismatch_message_is_byte_identical(self, tmp_path):
        target = tmp_path / "b.db"
        SqliteStore(
            path=target, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        ).close()
        source = tmp_path / "a.db"
        pos = WitnessPosition(
            fact_id="f1", arrival_lineage=None, ordinal=1, seq=1,
            lineage="LINEAGE-A", unadopted=False, anchor=None,
            store=str(source.resolve()),
        )
        with pytest.raises(WitnessLineageMismatch) as exc:
            verify_position_for_store(pos, target)
        assert str(exc.value) == self.A10_LINEAGE_TEMPLATE.format(
            lineage="LINEAGE-A",
            source=str(source.resolve()),
            target_lineage=_meta(target, "own_lineage"),
            target=str(target.resolve()),
        )


# ---------------------------------------------------------------------------
# G-D1-3 — seq:N round-trip across a batch boundary
# ---------------------------------------------------------------------------


class TestG_D1_3_SeqRoundTripAcrossABatch:
    """The ruled cost of D1-Q1's RECORD-GRANULAR arm, pinned.

    A ceremony is atomic: its rows share ONE ``arrival_ordinal``. A cutoff
    ``arrival_ordinal <= ord`` therefore selects the WHOLE record, so a
    position addressed at a mid-batch row resolves to the same prefix — and
    the same ``seq`` — as one addressed at the batch's last row. ``seq:N``
    round-trips to the RECORD, not to the row. That is the ruled cost, and
    this gate is what keeps it a decision rather than a surprise.
    """

    def _batch_rows(self, db: Path) -> list[tuple[str, int, int]]:
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute(
                "SELECT id, arrival_ordinal, arrival_seq FROM facts "
                "WHERE kind IN (?, ?) ORDER BY arrival_ordinal, arrival_seq",
                (DECL_KIND_DEFINED, DECL_KIND_RETIRED),
            ).fetchall()
        finally:
            conn.close()

    def test_a_multi_row_record_shares_one_ordinal(self, tmp_path, keys, signer):
        _log, db = _arrival_store_with_a_batch(tmp_path / "s", keys, signer)
        rows = self._batch_rows(db)
        assert len(rows) == 2, "the harness must produce a genuine multi-row batch"
        assert rows[0][1] == rows[1][1]
        assert [r[2] for r in rows] == [0, 1]

    def test_mid_batch_position_round_trips_through_seq_to_the_record(
        self, tmp_path, keys, signer
    ):
        _log, db = _arrival_store_with_a_batch(tmp_path / "s", keys, signer)
        first_id, batch_ordinal, _ = self._batch_rows(db)[0]
        last_id = self._batch_rows(db)[1][0]

        mid = resolve_witness_position(db, first_id, group_boundary="allow")
        end = resolve_witness_position(db, last_id, group_boundary="allow")

        # Record granularity: both rows of the record cut the SAME prefix.
        assert mid.ordinal == end.ordinal == batch_ordinal
        assert mid.seq == end.seq

        # seq:N -> id -> position is a fixed point at the record boundary: the
        # id it resolves back to is the record's LAST row, not the mid row.
        round_tripped_id = resolve_seq(db, mid.seq)
        assert round_tripped_id == last_id
        assert round_tripped_id != first_id
        round_tripped = resolve_witness_position(
            db, round_tripped_id, group_boundary="allow"
        )
        assert round_tripped.ordinal == mid.ordinal
        assert round_tripped.seq == mid.seq

    def test_seq_round_trip_is_exact_outside_a_batch(self, tmp_path, keys, signer):
        """The cost is confined to multi-row records: every single-row record
        round-trips through ``seq:N`` back to its own id."""
        _log, db = _arrival_store_with_a_batch(tmp_path / "s", keys, signer)
        batch_ordinals = {r[1] for r in self._batch_rows(db)}
        conn = sqlite3.connect(str(db))
        singles = [
            r[0]
            for r in conn.execute(
                "SELECT id, arrival_ordinal FROM facts "
                "ORDER BY arrival_ordinal, arrival_seq"
            )
            if r[1] not in batch_ordinals
        ]
        conn.close()
        assert len(singles) >= 4
        for fid in singles:
            pos = resolve_witness_position(db, fid, group_boundary="allow")
            assert resolve_seq(db, pos.seq) == fid


# ---------------------------------------------------------------------------
# G-D1-4 — the same-path axis guard
# ---------------------------------------------------------------------------


class TestG_D1_4_SamePathAxisGuard:
    """A store file replaced in place under the same path is a DIFFERENT
    coordinate axis wearing the old address — A10's same-path branch would
    wave it through, because the path matches. The new typed
    ``WitnessAxisMismatch`` closes exactly that hole, and nothing else: A10's
    two refusals and the same-lineage re-resolution are unchanged.
    """

    def test_same_path_replacement_raises_witness_axis_mismatch(
        self, tmp_path, keys, signer
    ):
        _log_a, db_a = _arrival_store_with_a_batch(tmp_path / "a", keys, signer)
        _log_b, db_b = _arrival_store_with_a_batch(tmp_path / "b", keys, signer)
        axis_a = _meta(db_a, ARRIVAL_LINEAGE_KEY)
        axis_b = _meta(db_b, ARRIVAL_LINEAGE_KEY)
        assert axis_a and axis_b and axis_a != axis_b

        pos = resolve_witness_position(db_a, "head", group_boundary="allow")
        assert pos.arrival_lineage == axis_a
        # Valid before the swap.
        assert verify_position_for_store(pos, db_a) is pos

        # The store file is replaced IN PLACE, under the same path.
        shutil.copyfile(db_b, db_a)

        with pytest.raises(WitnessAxisMismatch) as exc:
            verify_position_for_store(pos, db_a)
        assert axis_a in str(exc.value) and axis_b in str(exc.value)

    def test_axis_guard_needs_a_real_axis_on_BOTH_sides(self, tmp_path, keys, signer):
        """D1: it fires only when both sides carry a real axis. A legacy
        (axis-less) position against an arrival store, or an arrival position
        against a legacy store, is NOT this failure."""
        _log_a, db_a = _arrival_store_with_a_batch(tmp_path / "a", keys, signer)
        axis_a = _meta(db_a, ARRIVAL_LINEAGE_KEY)
        assert axis_a is not None

        legacy_pos = WitnessPosition(
            fact_id=GENESIS_SENTINEL, arrival_lineage=None, ordinal=-1, seq=0,
            lineage=None, unadopted=True, anchor=None, store=str(db_a.resolve()),
        )
        assert verify_position_for_store(legacy_pos, db_a) is legacy_pos

        legacy_db = tmp_path / "legacy.db"
        SqliteStore(
            path=legacy_db, serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        ).close()
        assert _meta(legacy_db, ARRIVAL_LINEAGE_KEY) is None
        arrival_pos = WitnessPosition(
            fact_id=GENESIS_SENTINEL, arrival_lineage=axis_a, ordinal=-1, seq=0,
            lineage=None, unadopted=True, anchor=None,
            store=str(legacy_db.resolve()),
        )
        assert verify_position_for_store(arrival_pos, legacy_db) is arrival_pos

    def test_a10_refusals_are_untouched_by_the_axis_guard(self, tmp_path, keys, signer):
        """A DIFFERENT store is A10's business, not the axis guard's — even
        when both stores are arrival-canonical with different axes. Otherwise
        the axis guard would preempt A10 and B1c re-resolution alike."""
        _log_a, db_a = _arrival_store_with_a_batch(tmp_path / "a", keys, signer)
        _log_b, db_b = _arrival_store_with_a_batch(tmp_path / "b", keys, signer)
        assert _meta(db_a, ARRIVAL_LINEAGE_KEY) != _meta(db_b, ARRIVAL_LINEAGE_KEY)

        unadopted = WitnessPosition(
            fact_id="f1", arrival_lineage=_meta(db_a, ARRIVAL_LINEAGE_KEY),
            ordinal=1, seq=1, lineage=None, unadopted=True, anchor=None,
            store=str(db_a.resolve()),
        )
        with pytest.raises(WitnessLineageMismatch, match="an UNADOPTED handle"):
            verify_position_for_store(unadopted, db_b)

        foreign = WitnessPosition(
            fact_id="f1", arrival_lineage=_meta(db_a, ARRIVAL_LINEAGE_KEY),
            ordinal=1, seq=1, lineage="NOT-THIS-STORES-LINEAGE", unadopted=False,
            anchor=None, store=str(db_a.resolve()),
        )
        with pytest.raises(
            WitnessLineageMismatch, match="does not match this store's lineage"
        ):
            verify_position_for_store(foreign, db_b)

    def test_same_lineage_sibling_still_re_resolves_not_refuses(self, tmp_path):
        """B1c: two stores sharing a declaration lineage have their OWN
        arrival axes. Re-resolution by fact id must survive the axis guard."""
        src = tmp_path / "a.db"
        dst = tmp_path / "b.db"
        for p in (src, dst):
            SqliteStore(
                path=p, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
            ).close()
        _set_meta(src, **{ARRIVAL_LINEAGE_KEY: "AXIS-A", "own_lineage": "L"})
        _set_meta(dst, **{ARRIVAL_LINEAGE_KEY: "AXIS-B", "own_lineage": "L"})
        conn = sqlite3.connect(str(dst))
        for i, coord in enumerate((7, 8)):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, "
                "signature, arrival_ordinal, arrival_seq) "
                "VALUES (?, 'note', ?, 'kyle', '', ?, NULL, ?, 0)",
                (f"shared-{i}", 100.0 + i, json.dumps({"n": i}), coord),
            )
        conn.commit()
        conn.close()

        pos = WitnessPosition(
            fact_id="shared-1", arrival_lineage="AXIS-A", ordinal=2, seq=2,
            lineage="L", unadopted=False, anchor=None, store=str(src.resolve()),
        )
        applied = verify_position_for_store(pos, dst)
        # The TARGET's coordinate, and the TARGET's axis — never the source's.
        assert applied.ordinal == 8
        assert applied.arrival_lineage == "AXIS-B"
        assert applied.store == str(dst.resolve())


# ---------------------------------------------------------------------------
# G-D1-5 — position equivalence, ordered and permuted
# ---------------------------------------------------------------------------


def _corpus(db: Path, order: list[int]) -> list[str]:
    """A legacy-mirrored corpus whose rows are INSERTED in ``order`` but carry
    arrival coordinates 1..N in canonical order. ``order`` = ``range(n)`` gives
    an un-permuted store (rowid order == arrival order); any other permutation
    divorces the two axes."""
    SqliteStore(
        path=db, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    ).close()
    conn = sqlite3.connect(str(db))
    ensure_coordinate_schema(conn, mode="mirrored")
    ids = [f"corpus-{i:03d}" for i in range(len(order))]
    for i in order:
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, "
            "signature, arrival_ordinal, arrival_seq) "
            "VALUES (?, 'note', ?, 'kyle', '', ?, NULL, ?, 0)",
            (ids[i], 1000.0 + i, json.dumps({"n": i}), i + 1),
        )
    conn.commit()
    conn.close()
    return ids


def _prefix_by_ordinal(db: Path, ordinal: int) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {
            r[0]
            for r in conn.execute(
                "SELECT id FROM facts WHERE arrival_ordinal <= ?", (ordinal,)
            )
        }
    finally:
        conn.close()


def _rowid_rank(db: Path):
    """A sort key giving each fact id its physical (rowid) rank."""
    conn = sqlite3.connect(str(db))
    try:
        rank = {
            r[0]: r[1]
            for r in conn.execute("SELECT id, rowid FROM facts")
        }
    finally:
        conn.close()
    return lambda fid: rank[fid]


def _prefix_by_rowid(db: Path, fact_id: str) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        rid = conn.execute(
            "SELECT rowid FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()[0]
        return {
            r[0] for r in conn.execute("SELECT id FROM facts WHERE rowid <= ?", (rid,))
        }
    finally:
        conn.close()


class TestG_D1_5_PositionEquivalence:
    """The re-key must not move any answer on a store where the two axes
    agree, and must follow ARRIVAL — not rowid — where they disagree. Both
    halves are needed: the first alone would pass for a no-op, the second
    alone would not prove the corpus is unaffected.
    """

    ORDERED = list(range(12))
    PERMUTED = [7, 0, 11, 3, 1, 9, 5, 2, 10, 4, 8, 6]

    def test_unpermuted_store_selects_the_same_row_set_as_rowid_did(self, tmp_path):
        db = tmp_path / "ordered.db"
        ids = _corpus(db, self.ORDERED)
        for fid in ids:
            pos = resolve_witness_position(db, fid, group_boundary="allow")
            assert _prefix_by_ordinal(db, pos.ordinal) == _prefix_by_rowid(db, fid)

    def test_permuted_store_is_governed_by_arrival_not_rowid(self, tmp_path):
        db = tmp_path / "permuted.db"
        ids = _corpus(db, self.PERMUTED)
        divergences = 0
        for fid in ids:
            pos = resolve_witness_position(db, fid, group_boundary="allow")
            arrival_prefix = _prefix_by_ordinal(db, pos.ordinal)
            rowid_prefix = _prefix_by_rowid(db, fid)
            # Arrival is the authority: the prefix is exactly the canonical
            # 1..ordinal run, whatever physical order the rows were written in.
            assert arrival_prefix == set(ids[: pos.ordinal])
            assert pos.seq == len(arrival_prefix)
            if arrival_prefix != rowid_prefix:
                divergences += 1
        # Not vacuous: the permutation genuinely divorces the two axes.
        assert divergences > 0

    def test_positions_agree_across_the_two_representations(self, tmp_path):
        """The same fact id resolves to the same (ordinal, seq) in both the
        ordered and the permuted store — the coordinate is a property of the
        record, not of where the row physically landed."""
        ordered = tmp_path / "o.db"
        permuted = tmp_path / "p.db"
        ids = _corpus(ordered, self.ORDERED)
        assert _corpus(permuted, self.PERMUTED) == ids
        for fid in ids:
            a = resolve_witness_position(ordered, fid, group_boundary="allow")
            b = resolve_witness_position(permuted, fid, group_boundary="allow")
            assert (a.ordinal, a.seq, a.fact_id) == (b.ordinal, b.seq, b.fact_id)

    def test_the_reader_selects_on_the_arrival_axis_not_the_rowid_axis(self, tmp_path):
        """The SELECTION path, not just resolution.

        ``StoreReader.facts_by_kind(at_ordinal=...)`` is what every ``at=``
        fold actually reads through, and its cutoff clause is a separate site
        from the resolution query. On the permuted store the two axes disagree
        row-for-row, so a cutoff silently left on ``rowid`` returns a
        different set — which resolution-only assertions cannot see.
        """
        from engine.store_reader import StoreReader

        permuted = tmp_path / "p.db"
        ids = _corpus(permuted, self.PERMUTED)
        disagreements = 0
        for fid in ids:
            pos = resolve_witness_position(permuted, fid, group_boundary="allow")
            with StoreReader(permuted) as reader:
                selected = [
                    f["id"] for f in reader.facts_by_kind("note", at_ordinal=pos.ordinal)
                ]
            # Selected in ARRIVAL order, and exactly the canonical prefix.
            assert selected == ids[: pos.ordinal]
            if selected != sorted(selected, key=_rowid_rank(permuted)):
                disagreements += 1
        # Not vacuous: on this store rowid order is genuinely not arrival order.
        assert disagreements > 0

    def test_durable_handle_output_is_unchanged_by_the_rekey(self, tmp_path, keys, signer):
        """DONE-CRITERIA: ``durable_handle`` is untouched — ``fact:<lineage>/<id>``
        for adopted positions, refused (``None``) for unadopted and genesis.
        It never named a coordinate, so the re-key cannot show through it."""
        _log, db = _arrival_store_with_a_batch(tmp_path / "s", keys, signer)
        lineage = _meta(db, "own_lineage")
        assert lineage

        conn = sqlite3.connect(str(db))
        ids = [
            r[0]
            for r in conn.execute(
                "SELECT id FROM facts ORDER BY arrival_ordinal, arrival_seq"
            )
        ]
        conn.close()
        for fid in ids:
            pos = resolve_witness_position(db, fid, group_boundary="allow")
            assert durable_handle(pos) == f"fact:{lineage}/{fid}"

        assert durable_handle(
            resolve_witness_position(db, GENESIS_SENTINEL)
        ) is None

        unadopted = tmp_path / "u.db"
        SqliteStore(
            path=unadopted, serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
        ).close()
        conn = sqlite3.connect(str(unadopted))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, "
            "signature, arrival_ordinal, arrival_seq) "
            "VALUES (?, 'note', 1.0, 'kyle', '', '{}', NULL, 1, 0)",
            (gen_id(),),
        )
        conn.commit()
        conn.close()
        assert durable_handle(resolve_witness_position(unadopted, "head")) is None


# ---------------------------------------------------------------------------
# G-D1-6 — the engine baseline field
# ---------------------------------------------------------------------------


class TestG_D1_6_ReversedDiffBaseline:
    """``diff_interval_report`` owns the baseline choice; the app only maps it
    to a CLI label. The field must name the LOWER endpoint by input position,
    so a reversed interval attributes the same baseline ROW while flipping the
    name — which is exactly what the app needs and cannot compute once the
    coordinate is no longer a public rowid.
    """

    def _store(self, tmp_path: Path) -> tuple[Path, WitnessPosition, WitnessPosition]:
        db = tmp_path / "d.db"
        SqliteStore(
            path=db, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
        ).close()
        conn = sqlite3.connect(str(db))
        for i, ts in enumerate((100.0, 200.0, 150.0, 300.0)):
            conn.execute(
                "INSERT INTO facts (id, kind, ts, observer, origin, payload, "
                "signature, arrival_ordinal, arrival_seq) "
                "VALUES (?, 'decision', ?, 'kyle', '', ?, NULL, ?, 0)",
                (f"d-{i}", ts, json.dumps({"topic": f"t{i}"}), i + 1),
            )
        conn.commit()
        conn.close()
        return (
            db,
            resolve_witness_position(db, "d-1", group_boundary="allow"),
            resolve_witness_position(db, "d-3", group_boundary="allow"),
        )

    def test_reversed_diff_attributes_the_same_baseline_row(self, tmp_path):
        db, lo, hi = self._store(tmp_path)
        forward = diff_interval_report(db, lo, hi)
        backward = diff_interval_report(db, hi, lo)

        # Same interval, same findings — the report is symmetric in content.
        assert forward["late_arrivals"] == backward["late_arrivals"]
        assert forward["declaration_changed"] == backward["declaration_changed"]
        # ...and the baseline names the LOWER endpoint by input position.
        assert forward["baseline"] == "pos1"
        assert backward["baseline"] == "pos2"
        # Not vacuous: the interval genuinely holds a late arrival.
        assert [a["id"] for a in forward["late_arrivals"]] == ["d-2"]

    def test_baseline_is_present_on_the_empty_interval_too(self, tmp_path):
        db, lo, _hi = self._store(tmp_path)
        report = diff_interval_report(db, lo, lo)
        assert report == {
            "late_arrivals": [],
            "declaration_changed": False,
            "baseline": "pos1",
        }

    def test_the_app_maps_the_engine_field_to_its_own_label(self, tmp_path):
        """The engine names positions; only the app knows they are called
        'from' and 'to'. Pinned together so the mapping cannot silently
        invert — the failure the pre-D1 comment warned about."""
        db, lo, hi = self._store(tmp_path)
        for pos1, pos2, expected in ((lo, hi, "from"), (hi, lo, "to")):
            report = diff_interval_report(db, pos1, pos2)
            assert (
                "from" if report.get("baseline") == "pos1" else "to"
            ) == expected
