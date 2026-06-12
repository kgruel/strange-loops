"""Tick hash chain — tamper-evidence at the store layer.

Covers design/tick-chain-at-store-layer: prev_hash linkage, fact windows
(id cursors, witness-order/rowid membership — see ORDERING AUTHORITY in
sqlite_store and observation design/event-order-vs-witness-order),
window_hash commitments, pre-chain era migration.

Delta 2 (design/tick-signature-on-every-tick,
design/tick-signature-in-chain-envelope): injected tick signing flips the
old chain-head boundary — a signed head is self-verifying. Signing here
uses fake callables; engine's contract is the callable, not the algorithm
(real Ed25519 composition is exercised at the apps/loops layer).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine import Tick
from engine.sqlite_store import SqliteStore, _tick_row_hash


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "chain.db"


def make_store(path: Path) -> SqliteStore[Fact]:
    return SqliteStore(path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)


def fake_signer(secret: str = "k1"):
    """Deterministic stand-in for the injected signer callable."""
    def signer(digest: str) -> str:
        return hashlib.sha256(f"{secret}:{digest}".encode()).hexdigest()
    return signer


def fake_verifier(secret: str = "k1"):
    """Verifier counterpart of fake_signer — same (sig, digest) contract."""
    expected = fake_signer(secret)
    def verifier(signature: str, digest: str) -> bool:
        return signature == expected(digest)
    return verifier


def make_signed_store(path: Path, secret: str = "k1") -> SqliteStore[Fact]:
    return SqliteStore(
        path=path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        tick_signer=fake_signer(secret),
    )


def emit(store: SqliteStore[Fact], n: int, *, kind: str = "note") -> list[str]:
    """Append n facts, return their assigned ids."""
    return [
        store.append(Fact.of(kind, "tester", body=f"fact-{i}"))
        for i in range(n)
    ]


def tick(store: SqliteStore[Fact], name: str = "boundary") -> None:
    store.append_tick(
        Tick(name=name, ts=datetime.now(UTC), payload={"n": store.total}, origin="test")
    )


class TestChainedAppend:
    def test_clean_store_verifies(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)
        emit(store, 2)
        tick(store)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["ticks"] == 2
        assert report["chained"] == 2
        assert report["legacy"] == 0
        assert report["covered_facts"] == 4
        assert report["uncovered_facts"] == 0
        assert report["breaks"] == []

    def test_first_tick_in_new_store_covers_all_prior_facts(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 3)
        tick(store)

        row = store._conn.execute(
            "SELECT window_start, fact_cursor FROM ticks"
        ).fetchone()
        assert row[0] == ""  # window opens at the beginning of the store
        assert store.verify_chain()["covered_facts"] == 3

    def test_live_edge_is_uncovered_not_broken(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)
        emit(store, 1)  # after the last tick — uncovered live edge

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 2
        assert report["uncovered_facts"] == 1

    def test_chain_continues_across_reopen(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        store.close()

        store2 = make_store(tmp_db)
        emit(store2, 1)
        tick(store2)

        report = store2.verify_chain()
        assert report["ok"] is True
        assert report["chained"] == 2

    def test_empty_store_tick_verifies(self, tmp_db: Path):
        store = make_store(tmp_db)
        tick(store)
        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 0


class TestTamperDetection:
    def test_modified_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        ids = emit(store, 2)
        tick(store)

        store._conn.execute(
            "UPDATE facts SET payload = ? WHERE id = ?",
            (json.dumps({"body": "rewritten history"}), ids[0]),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_deleted_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        ids = emit(store, 3)
        tick(store)

        store._conn.execute("DELETE FROM facts WHERE id = ?", (ids[1],))
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_displaced_fact_breaks_window(self, tmp_db: Path):
        """Windows are witness-order (rowid) ranges — moving a covered row
        out of its sealed range changes window content: break. Append-only
        leaves no rowid gaps, so wedging a row INTO a sealed window requires
        displacing one — equally detected."""
        store = make_store(tmp_db)
        ids = emit(store, 3)
        tick(store)

        store._conn.execute(
            "UPDATE facts SET rowid = 1000 WHERE id = ?", (ids[1],)
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

    def test_backdated_arrival_is_live_edge_not_break(self, tmp_db: Path):
        """DELIBERATE semantics flip from the id-window era (which pinned
        this exact insert as a break): a fact arriving with an old
        event-time id (backfill, peer sync) is honest history received
        now — it lands on the live edge in witness order and the next tick
        seals it. A false tamper alarm caused by truthfulness is the bug,
        not the arrival (design/event-order-vs-witness-order)."""
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)

        # "0"*26 sorts before any real ULID — old event time, received now
        store.append(Fact.of("note", "syncer", body="backfilled"), id_override="0" * 26)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 2
        assert report["uncovered_facts"] == 1  # live edge, awaiting next seal

        tick(store)
        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 3  # sealed as received-now

    def test_modified_tick_breaks_successor_link(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute(
            "UPDATE ticks SET payload = ? WHERE name = ?",
            (json.dumps({"n": 999}), "first"),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("prev_hash" in b["reason"] for b in report["breaks"])

    def test_deleted_tick_breaks_chain(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute("DELETE FROM ticks WHERE name = ?", ("first",))
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is False

    def test_unsigned_chain_head_unanchored_documented_boundary(self, tmp_db: Path):
        """An UNSIGNED head is not self-verifying — pre-signature era posture.

        Delta 1 pinned this for all stores; delta 2 flips it for signed
        stores (see TestTickSignatures.test_tampered_head_detected_when_signed).
        It remains the honest boundary of the unsigned era.
        """
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "only")

        store._conn.execute(
            "UPDATE ticks SET payload = ? WHERE name = ?",
            (json.dumps({"n": 999}), "only"),
        )
        store._conn.commit()

        report = store.verify_chain()
        assert report["ok"] is True  # documented gap of the unsigned era


class TestTickSignatures:
    def test_signed_store_verifies(self, tmp_db: Path):
        store = make_signed_store(tmp_db)
        emit(store, 2)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is True
        assert report["chained"] == 2
        assert report["signed"] == 2
        assert report["sig_checked"] is True

    def test_tampered_head_detected_when_signed(self, tmp_db: Path):
        """Delta 2 flips the delta-1 head boundary: a signed head IS
        self-verifying — rewriting its payload invalidates the signature."""
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store, "only")

        store._conn.execute(
            "UPDATE ticks SET payload = ? WHERE name = ?",
            (json.dumps({"n": 999}), "only"),
        )
        store._conn.commit()

        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is False
        assert any("signature invalid" in b["reason"] for b in report["breaks"])

    def test_wrong_key_detected(self, tmp_db: Path):
        store = make_signed_store(tmp_db, secret="k1")
        emit(store, 1)
        tick(store)

        report = store.verify_chain(verifier=fake_verifier("k2"))
        assert report["ok"] is False
        assert any("signature invalid" in b["reason"] for b in report["breaks"])

    def test_stripped_signature_breaks_successor_link(self, tmp_db: Path):
        """The successor's prev_hash commits to the signature
        (design/tick-signature-in-chain-envelope): stripping a signed row's
        signature is detected WITHOUT any verifier."""
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute(
            "UPDATE ticks SET signature = NULL WHERE name = ?", ("first",)
        )
        store._conn.commit()

        report = store.verify_chain()  # no verifier — structural check
        assert report["ok"] is False
        assert any("prev_hash" in b["reason"] for b in report["breaks"])

    def test_stripped_head_signature_is_era_regression(self, tmp_db: Path):
        """The head has no successor to protect it, but signature
        era-monotonicity catches the strip: unsigned-after-signed = break,
        verifier or not."""
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        store._conn.execute(
            "UPDATE ticks SET signature = NULL WHERE name = ?", ("second",)
        )
        store._conn.commit()

        report = store.verify_chain()  # no verifier — structural check
        assert report["ok"] is False
        assert any("unsigned tick after signed era" in b["reason"]
                   for b in report["breaks"])

    def test_signing_era_can_begin_mid_chain(self, tmp_db: Path):
        """Unsigned ticks BEFORE the signing era are honest history, not
        breaks — same posture as the pre-chain era."""
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store, "pre-signing")
        store.close()

        signed = make_signed_store(tmp_db)
        emit(signed, 1)
        tick(signed, "signed")

        report = signed.verify_chain(verifier=fake_verifier())
        assert report["ok"] is True
        assert report["chained"] == 2
        assert report["signed"] == 1

    def test_verify_without_verifier_counts_but_does_not_check(self, tmp_db: Path):
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["signed"] == 1
        assert report["sig_checked"] is False

    def test_total_strip_renders_as_unsigned_documented_boundary(self, tmp_db: Path):
        """KNOWN SCOPE BOUNDARY (delta 2): a forger who strips EVERY
        signature and recomputes every prev_hash forward produces a store
        indistinguishable from honest unsigned history. A self-contained
        chain cannot detect a total rewrite — the anchor is the key
        registry in the .vertex (declared key + zero signed ticks = CLI
        tripwire) and, in a later delta, external witnessing. This test
        pins the boundary so that delta flips it deliberately.
        """
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store, "first")
        emit(store, 1)
        tick(store, "second")

        rows = store._conn.execute(
            "SELECT id, name, ts, since, origin, payload, prev_hash, "
            "window_start, fact_cursor, window_hash, signature "
            "FROM ticks ORDER BY rowid"
        ).fetchall()
        prev: tuple | None = None
        for row in rows:
            new_prev = _tick_row_hash(prev) if prev is not None else None
            store._conn.execute(
                "UPDATE ticks SET signature = NULL, prev_hash = ? WHERE id = ?",
                (new_prev, row[0]),
            )
            prev = (*row[:6], new_prev, *row[7:10], None)
        store._conn.commit()

        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is True  # documented gap, not a regression
        assert report["signed"] == 0


class TestMixedIdEras:
    """Regression: friction chain-cursor-assumes-ulid-order.

    Stores carrying uuid4-era facts (2026-03-15..05-16) violate
    id-order == append-order: lowercase-hex uuid4 ids sort above every
    ULID, so MAX(id) pins to a mid-history uuid4 forever and every window
    minted after it is empty — chain intact but vacuous. Witness order
    (rowid) is immune to id-era mixing by construction.
    """

    UUID4_IDS = (
        "ffecb74d-8474-4de3-97ed-287849461877",  # the actual production pin
        "a1b2c3d4-0000-4000-8000-000000000001",
    )

    def mixed_store(self, path: Path) -> SqliteStore[Fact]:
        """uuid4-era facts first, then ULID-era facts — production shape."""
        store = make_store(path)
        for uid in self.UUID4_IDS:
            store.append(Fact.of("note", "tester", body="uuid4-era"), id_override=uid)
        emit(store, 2)  # ULID era
        return store

    def test_cursor_is_append_edge_not_lexicographic_max(self, tmp_db: Path):
        store = self.mixed_store(tmp_db)
        tick(store)

        cursor = store._conn.execute(
            "SELECT fact_cursor FROM ticks"
        ).fetchone()[0]
        edge = store._conn.execute(
            "SELECT id FROM facts ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
        assert cursor == edge          # newest by rowid (a ULID)
        assert cursor not in self.UUID4_IDS  # NOT MAX(id)

    def test_coverage_accrues_in_mixed_store(self, tmp_db: Path):
        """Under MAX(id) cursors this store sealed empty windows forever
        (covered 0 in perpetuity); under witness order coverage accrues."""
        store = self.mixed_store(tmp_db)
        tick(store)   # new store: window_start "" covers all 4
        emit(store, 2)
        tick(store)   # covers the 2 new ULID facts

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 6
        assert report["uncovered_facts"] == 0

    def test_epoch_after_legacy_in_mixed_store(self, tmp_db: Path):
        """The exact production shape: legacy ticks + uuid4-era facts, then
        the chain epoch. The epoch tick must anchor at the true append edge
        so coverage begins at the NEXT tick instead of never."""
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        for uid in self.UUID4_IDS:
            store.append(Fact.of("note", "tester", body="uuid4-era"), id_override=uid)
        emit(store, 2)
        tick(store)   # epoch marker: empty window at the append edge
        emit(store, 3)
        tick(store)   # first covering tick

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["legacy"] == 1
        assert report["chained"] == 2
        assert report["covered_facts"] == 3   # exactly the post-epoch facts
        # pre-epoch history (legacy fact + uuid4 era + pre-epoch ULIDs)
        # stays honestly uncovered: 1 + 2 + 2
        assert report["uncovered_facts"] == 5


LEGACY_SCHEMA = (
    """CREATE TABLE facts (
        id       TEXT NOT NULL PRIMARY KEY,
        kind     TEXT NOT NULL,
        ts       REAL NOT NULL,
        observer TEXT NOT NULL,
        origin   TEXT NOT NULL DEFAULT '',
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
    """CREATE TABLE ticks (
        id       TEXT NOT NULL PRIMARY KEY,
        name     TEXT NOT NULL,
        ts       REAL NOT NULL,
        since    REAL,
        origin   TEXT NOT NULL,
        payload  TEXT NOT NULL CHECK (json_valid(payload))
    )""",
)


def make_legacy_db(path: Path) -> None:
    """A pre-chain database: old schema, one fact, one tick."""
    conn = sqlite3.connect(str(path))
    for stmt in LEGACY_SCHEMA:
        conn.execute(stmt)
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("01HZZZZZZZZZZZZZZZZZZZZZZZ", "note", 1700000000.0, "tester", "", '{"body": "old"}'),
    )
    conn.execute(
        "INSERT INTO ticks (id, name, ts, since, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
        ("01HZZZZZZZZZZZZZZZZZZZZZZX", "old-boundary", 1700000001.0, None, "test", '{"n": 1}'),
    )
    conn.commit()
    conn.close()


class TestPreChainMigration:
    def test_legacy_rows_tolerated_and_columns_added(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["legacy"] == 1
        assert report["chained"] == 1

    def test_first_chained_tick_after_legacy_claims_no_coverage(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)

        row = store._conn.execute(
            "SELECT window_start, fact_cursor FROM ticks WHERE window_hash IS NOT NULL"
        ).fetchone()
        assert row[0] == row[1]  # epoch marker: empty window, no false claims
        assert store.verify_chain()["covered_facts"] == 0

    def test_coverage_resumes_after_epoch(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)  # epoch tick, covers nothing
        emit(store, 2)
        tick(store)  # covers the 2 facts after the epoch

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["covered_facts"] == 2

    def test_verify_on_pure_legacy_store_is_read_only(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)

        report = store.verify_chain()
        assert report["ok"] is True
        assert report["legacy"] == 1
        assert report["chained"] == 0

        # verify must NOT migrate schema — that's the write path's job
        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(ticks)")}
        assert "window_hash" not in cols

    def test_delta1_db_without_signature_column_verifies_read_only(self, tmp_db: Path):
        """A delta-1 store (chain columns, no signature column) verifies
        as-is: rows normalize to unsigned, and verify never ALTERs."""
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        store._conn.execute("ALTER TABLE ticks DROP COLUMN signature")
        store._conn.commit()

        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is True
        assert report["chained"] == 1
        assert report["signed"] == 0

        cols = {r[1] for r in store._conn.execute("PRAGMA table_info(ticks)")}
        assert "signature" not in cols


class TestVerifyTickDetail:
    """verify_chain(include_ticks=True) — per-tick attestation rows.

    Covers decision/design/attestation-envelope-read-path: the walk
    already computes era, signature validity, and window bounds per tick;
    include_ticks keeps them instead of discarding. window_facts is the
    per-window count whose wrongness surfaced the witness-order bug.
    """

    def test_default_report_omits_detail(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        assert "tick_detail" not in store.verify_chain()

    def test_detail_rows_in_append_order_with_window_counts(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)
        emit(store, 3)
        tick(store)

        detail = store.verify_chain(include_ticks=True)["tick_detail"]
        assert [d["window_facts"] for d in detail] == [2, 3]
        assert all(d["ok"] for d in detail)
        assert all(d["signed"] is False and d["sig_ok"] is None for d in detail)

    def test_cursor_dereference(self, tmp_db: Path):
        store = make_store(tmp_db)
        store.append(Fact.of("seal", "tester", message="deliberate boundary"))
        tick(store)

        d = store.verify_chain(include_ticks=True)["tick_detail"][0]
        assert d["cursor_kind"] == "seal"
        assert d["cursor_preview"] == "deliberate boundary"
        assert d["fact_cursor"]  # the id the chain committed to

    def test_signed_detail_records_sig_ok(self, tmp_db: Path):
        store = make_signed_store(tmp_db)
        emit(store, 1)
        tick(store)

        d = store.verify_chain(
            include_ticks=True, verifier=fake_verifier()
        )["tick_detail"][0]
        assert d["signed"] is True
        assert d["sig_ok"] is True

        # No verifier injected → signature present but unchecked, not failed
        d2 = store.verify_chain(include_ticks=True)["tick_detail"][0]
        assert d2["signed"] is True
        assert d2["sig_ok"] is None

    def test_bad_signature_marks_row_not_ok(self, tmp_db: Path):
        store = make_signed_store(tmp_db, secret="k1")
        emit(store, 1)
        tick(store)

        d = store.verify_chain(
            include_ticks=True, verifier=fake_verifier("k2")
        )["tick_detail"][0]
        assert d["sig_ok"] is False
        assert d["ok"] is False

    def test_legacy_ticks_stay_aggregate_only(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)

        report = store.verify_chain(include_ticks=True)
        assert report["legacy"] == 1
        assert len(report["tick_detail"]) == 1  # only the chained tick

    def test_pure_legacy_store_detail_empty(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        assert store.verify_chain(include_ticks=True)["tick_detail"] == []


class TestEnvelopeReadPath:
    """StoreReader.ticks_between(with_envelope=True) — the witness-era
    envelope crossing into the read path (single query, no join)."""

    def test_plain_call_shape_unchanged(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        store.close()

        from engine.store_reader import StoreReader

        with StoreReader(tmp_db) as r:
            ticks = r.ticks_between(0, 4e9)
            assert isinstance(ticks[0], Tick)

    def test_envelope_chained_signed_and_cursor_deref(self, tmp_db: Path):
        store = make_signed_store(tmp_db)
        store.append(Fact.of("seal", "tester", message="boundary reason"))
        tick(store)
        store.close()

        from engine.store_reader import StoreReader

        with StoreReader(tmp_db) as r:
            [(t, env)] = r.ticks_between(0, 4e9, with_envelope=True)
            assert isinstance(t, Tick)
            assert env["chained"] is True
            assert env["signed"] is True
            assert env["cursor_kind"] == "seal"
            assert env["cursor_preview"] == "boundary reason"

    def test_pre_chain_schema_reports_unchained(self, tmp_db: Path):
        make_legacy_db(tmp_db)

        from engine.store_reader import StoreReader

        with StoreReader(tmp_db) as r:
            [(_, env)] = r.ticks_between(0, 4e9, with_envelope=True)
            assert env == {
                "chained": False, "signed": False, "fact_cursor": "",
                "cursor_kind": "", "cursor_preview": "",
            }

    def test_mixed_eras_in_one_read(self, tmp_db: Path):
        make_legacy_db(tmp_db)
        store = make_store(tmp_db)
        emit(store, 1)
        tick(store)
        store.close()

        from engine.store_reader import StoreReader

        with StoreReader(tmp_db) as r:
            pairs = r.ticks_between(0, 4e9, with_envelope=True)
            assert [e["chained"] for _, e in pairs] == [False, True]


# ---------------------------------------------------------------------------
# Re-anchor — the canon-migration ceremony (SPEC §8.1)
# ---------------------------------------------------------------------------

def _old_canon(obj: object) -> bytes:
    """The pre-JCS canonical encoding (json.dumps, ensure_ascii=True)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def fake_fact_signer(secret: str = "fk"):
    """Per-observer fact signer stand-in — engine contract (observer, digest)."""
    def signer(observer: str, digest: str) -> str:
        return hashlib.sha256(f"{secret}:{observer}:{digest}".encode()).hexdigest()
    return signer


def fake_fact_verifier(secret: str = "fk"):
    expected = fake_fact_signer(secret)
    def verifier(observer: str, signature: str, digest: str) -> bool:
        return signature == expected(observer, digest)
    return verifier


class TestReanchor:
    def _signed_store(self, path: Path) -> SqliteStore[Fact]:
        return SqliteStore(
            path=path,
            serialize=lambda f: f.to_dict(),
            deserialize=Fact.from_dict,
            tick_signer=fake_signer(),
            fact_signer=fake_fact_signer(),
        )

    def _build_old_canon_store(self, path: Path, monkeypatch) -> SqliteStore[Fact]:
        """Build a signed, chained store whose commitments used the OLD canon.

        Divergence comes from non-ASCII ENVELOPE FIELDS (observer, tick
        name): ensure_ascii escapes where JCS mandates raw UTF-8. Payload
        TEXT cannot diverge — it is serialized with ensure_ascii at append
        time and embedded verbatim, so it reaches the canon layer already
        ASCII. (Pure-ASCII envelopes hash identically under both canons —
        re-anchoring those is an idempotent no-op.)
        """
        from engine import sqlite_store as mod
        with monkeypatch.context() as m:
            m.setattr(mod, "_canonical_bytes", _old_canon)
            store = self._signed_store(path)
            store.append(Fact.of("note", "josé", body="café crème"))
            store.append(Fact.of("note", "josé", body="naïve"))
            tick(store, "première")
            store.append(Fact.of("note", "josé", body="emoji"))
            tick(store, "deuxième")
        return store

    def test_old_canon_store_reads_broken_under_jcs(self, tmp_db, monkeypatch):
        store = self._build_old_canon_store(tmp_db, monkeypatch)
        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is False  # the false-tamper-alarm SPEC §8 warns of

    def test_reanchor_restores_verification(self, tmp_db, monkeypatch):
        store = self._build_old_canon_store(tmp_db, monkeypatch)

        receipt = store.reanchor()
        assert receipt["facts_resigned"] == 3
        assert receipt["ticks_rechained"] == 2
        assert receipt["ticks_resigned"] == 2
        assert receipt["head"] is not None

        report = store.verify_chain(verifier=fake_verifier())
        assert report["ok"] is True
        assert report["signed"] == 2
        fact_report = store.verify_facts(verifier=fake_fact_verifier())
        assert fact_report["ok"] is True

    def test_reanchor_is_idempotent(self, tmp_db, monkeypatch):
        store = self._build_old_canon_store(tmp_db, monkeypatch)
        first = store.reanchor()
        second = store.reanchor()
        assert first["head"] == second["head"]
        assert store.verify_chain(verifier=fake_verifier())["ok"] is True

    def test_reanchor_preserves_event_columns(self, tmp_db, monkeypatch):
        store = self._build_old_canon_store(tmp_db, monkeypatch)
        before = store._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts ORDER BY rowid"
        ).fetchall()
        store.reanchor()
        after = store._conn.execute(
            "SELECT id, kind, ts, observer, origin, payload FROM facts ORDER BY rowid"
        ).fetchall()
        assert before == after  # append-only boundary: events untouched

    def test_reanchor_refuses_partial_without_fact_key(self, tmp_db, monkeypatch):
        self._build_old_canon_store(tmp_db, monkeypatch).close()
        # Reopen WITHOUT signers: signed rows exist, keys unavailable.
        store = make_store(tmp_db)
        with pytest.raises(ValueError, match="refusing partial"):
            store.reanchor()

    def test_reanchor_leaves_prechain_era_untouched(self, tmp_db, monkeypatch):
        # Legacy ticks (chain columns NULL) predate the chain; re-anchor
        # must not retro-claim them.
        store = make_store(tmp_db)
        emit(store, 1)
        store._conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) "
            "VALUES ('t-legacy', 'legacy', 1.0, NULL, '', '{}')"
        )
        store._conn.commit()
        store.close()

        from engine import sqlite_store as mod
        with monkeypatch.context() as m:
            m.setattr(mod, "_canonical_bytes", _old_canon)
            store = self._signed_store(tmp_db)
            store.append(Fact.of("note", "tester", body="époque"))
            tick(store, "chained")

        receipt = store.reanchor()
        assert receipt["ticks_rechained"] == 1  # legacy row not counted
        legacy = store._conn.execute(
            "SELECT prev_hash, window_start, fact_cursor, window_hash, signature "
            "FROM ticks WHERE id = 't-legacy'"
        ).fetchone()
        assert legacy == (None, None, None, None, None)
        assert store.verify_chain(verifier=fake_verifier())["ok"] is True
