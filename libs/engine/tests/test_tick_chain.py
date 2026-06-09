"""Tick hash chain — tamper-evidence at the store layer.

Covers design/tick-chain-at-store-layer: prev_hash linkage, explicit
id-based fact windows, window_hash commitments, pre-chain era migration.

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

    def test_inserted_fact_breaks_window(self, tmp_db: Path):
        store = make_store(tmp_db)
        emit(store, 2)
        tick(store)

        # "0"*26 sorts before any real ULID — lands inside the first window
        store.append(Fact.of("note", "intruder", body="backdated"), id_override="0" * 26)

        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash" in b["reason"] for b in report["breaks"])

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
