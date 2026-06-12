"""Fact authorship signatures — delta 3 at the store layer.

Covers design/fact-signature-at-store-column and
design/fact-signing-per-observer-keys: the facts.signature column,
sign-on-append via the injected per-observer signer, content-only
commitments (transport-stable: no id/rowid), signature passthrough for
replay/transport, verify_facts, and the era-aware fact row hash that
makes signature-stripping break already-sealed windows.

Signing here uses fake callables; engine's contract is the callable,
not the algorithm (real Ed25519 composition is exercised at the
apps/loops layer) — same posture as test_tick_chain.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine import Tick
from engine.sqlite_store import SqliteStore


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "facts.db"


def fake_fact_signer(keys: dict[str, str]):
    """Per-observer stand-in: observers in ``keys`` sign, others get None."""
    def signer(observer: str, digest: str) -> str | None:
        secret = keys.get(observer)
        if secret is None:
            return None
        return hashlib.sha256(f"{secret}:{digest}".encode()).hexdigest()
    return signer


def fake_fact_verifier(keys: dict[str, str]):
    """Verifier counterpart — checks against THAT observer's key exactly."""
    signer = fake_fact_signer(keys)
    def verifier(observer: str, signature: str, digest: str) -> bool:
        return signature == signer(observer, digest)
    return verifier


KEYS = {"kyle": "k-kyle", "claude": "k-claude"}


def make_store(path: Path, *, keys: dict[str, str] | None = None,
               tick_signer=None) -> SqliteStore[Fact]:
    return SqliteStore(
        path=path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        tick_signer=tick_signer,
        fact_signer=fake_fact_signer(keys) if keys is not None else None,
    )


def tick(store: SqliteStore[Fact], name: str = "boundary") -> None:
    store.append_tick(
        Tick(name=name, ts=datetime.now(UTC), payload={"n": store.total}, origin="test")
    )


def sig_of(path: Path, fact_id: str) -> str | None:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute(
            "SELECT signature FROM facts WHERE id = ?", (fact_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def make_pre_delta3_db(path: Path) -> None:
    """A facts table from before the signature column existed."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE facts (
            id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL, ts REAL NOT NULL,
            observer TEXT NOT NULL, origin TEXT NOT NULL DEFAULT '',
            payload TEXT NOT NULL)"""
    )
    conn.execute(
        """CREATE TABLE ticks (
            id TEXT NOT NULL PRIMARY KEY, name TEXT NOT NULL, ts REAL NOT NULL,
            since REAL, origin TEXT NOT NULL, payload TEXT NOT NULL)"""
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?,?,?,?,?,?)",
            (f"old-{i}", "note", 100.0 + i, "kyle", "", '{"body": "legacy"}'),
        )
    conn.commit()
    conn.close()


class TestSignOnAppend:
    def test_keyed_observer_signs(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "kyle", body="hello"))
        assert sig_of(tmp_db, fid) is not None

    def test_unkeyed_observer_appends_unsigned(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "drive-by", body="hello"))
        assert sig_of(tmp_db, fid) is None

    def test_no_signer_appends_unsigned(self, tmp_db: Path):
        store = make_store(tmp_db)
        fid = store.append(Fact.of("note", "kyle", body="hello"))
        assert sig_of(tmp_db, fid) is None

    def test_signature_is_per_observer(self, tmp_db: Path):
        """Same content, different observer key → different signature."""
        store = make_store(tmp_db, keys=KEYS)
        a = store.append(Fact(kind="note", ts=1.0, payload={"b": 1}, observer="kyle"))
        b = store.append(Fact(kind="note", ts=1.0, payload={"b": 1}, observer="claude"))
        assert sig_of(tmp_db, a) != sig_of(tmp_db, b)

    def test_commitment_excludes_store_identity(self, tmp_path: Path):
        """Same content in two stores → identical signature (no id/rowid)."""
        f = Fact(kind="note", ts=42.0, payload={"b": 1}, observer="kyle")
        ids = []
        sigs = []
        for name in ("a.db", "b.db"):
            path = tmp_path / name
            store = make_store(path, keys=KEYS)
            store.append(Fact.of("filler", "kyle", body="shift rowids"))
            if name == "b.db":
                store.append(Fact.of("filler", "kyle", body="shift more"))
            fid = store.append(f)
            ids.append(fid)
            sigs.append(sig_of(path, fid))
        assert ids[0] != ids[1]  # store-assigned identity differs
        assert sigs[0] == sigs[1]  # authorship commitment does not

    def test_signature_override_carries_verbatim(self, tmp_db: Path):
        """Replay/transport passthrough: never re-sign, even with a signer."""
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(
            Fact.of("note", "kyle", body="imported"),
            signature_override="foreign-sig",
        )
        assert sig_of(tmp_db, fid) == "foreign-sig"


class TestVerifyFacts:
    def test_clean_store_verifies(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        store.append(Fact.of("note", "kyle", body="a"))
        store.append(Fact.of("note", "drive-by", body="b"))
        report = store.verify_facts(verifier=fake_fact_verifier(KEYS))
        assert report["ok"] is True
        assert report["sig_checked"] is True
        assert report["signed"] == 1
        assert report["unsigned"] == 1
        assert report["observers"]["kyle"]["signed"] == 1
        assert report["observers"]["drive-by"]["unsigned"] == 1

    def test_tampered_payload_detected(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "kyle", body="original"))
        conn = sqlite3.connect(str(tmp_db))
        conn.execute(
            "UPDATE facts SET payload = ? WHERE id = ?",
            ('{"body": "altered"}', fid),
        )
        conn.commit()
        conn.close()
        report = store.verify_facts(verifier=fake_fact_verifier(KEYS))
        assert report["ok"] is False
        assert report["breaks"][0]["fact"] == fid
        assert "signature invalid" in report["breaks"][0]["reason"]

    def test_wrong_observer_key_detected(self, tmp_db: Path):
        """Authorship is THAT observer's key — a valid signature under a
        different registered key is still a break (no any-key relaxation)."""
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "kyle", body="x"))
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("UPDATE facts SET observer = 'claude' WHERE id = ?", (fid,))
        conn.commit()
        conn.close()
        report = store.verify_facts(verifier=fake_fact_verifier(KEYS))
        assert report["ok"] is False

    def test_without_verifier_counts_but_does_not_check(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "kyle", body="x"))
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("UPDATE facts SET payload = '{}' WHERE id = ?", (fid,))
        conn.commit()
        conn.close()
        report = store.verify_facts()
        assert report["ok"] is True  # nothing checked, nothing broken
        assert report["sig_checked"] is False
        assert report["signed"] == 1

    def test_pre_delta3_table_reports_all_unsigned_read_only(self, tmp_db: Path):
        make_pre_delta3_db(tmp_db)
        store = make_store(tmp_db, keys=KEYS)
        report = store.verify_facts(verifier=fake_fact_verifier(KEYS))
        assert report["ok"] is True
        assert report["facts"] == 3
        assert report["unsigned"] == 3
        assert report["observers"]["kyle"]["unsigned"] == 3
        # read-only: no column added by verify
        conn = sqlite3.connect(str(tmp_db))
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        conn.close()
        assert "signature" not in cols


class TestEraAwareWindowHash:
    def test_stripping_signed_fact_breaks_sealed_window(self, tmp_db: Path):
        store = make_store(tmp_db, keys=KEYS)
        fid = store.append(Fact.of("note", "kyle", body="sealed"))
        tick(store)
        conn = sqlite3.connect(str(tmp_db))
        conn.execute("UPDATE facts SET signature = NULL WHERE id = ?", (fid,))
        conn.commit()
        conn.close()
        report = store.verify_chain()
        assert report["ok"] is False
        assert any("window_hash mismatch" in b["reason"] for b in report["breaks"])

    def test_unsigned_facts_hash_identically_to_pre_delta3(self, tmp_db: Path):
        """Sealed windows over unsigned facts never re-anchor: a store with
        the signature column but no signer verifies the same as before."""
        store = make_store(tmp_db)
        store.append(Fact.of("note", "kyle", body="a"))
        tick(store)
        store.append(Fact.of("note", "kyle", body="b"))
        tick(store)
        assert store.verify_chain()["ok"] is True

    def test_migration_preserves_previously_sealed_windows(self, tmp_db: Path):
        """A pre-delta-3 store whose windows were sealed content-only still
        verifies after the signature column lands (NULL rows hash the same)."""
        store = make_store(tmp_db)  # column exists but rows unsigned
        store.append(Fact.of("note", "kyle", body="old era"))
        tick(store)
        signed = make_store(tmp_db, keys=KEYS)  # signer arrives later
        signed.append(Fact.of("note", "kyle", body="new era"))
        tick(signed)
        report = signed.verify_chain()
        assert report["ok"] is True
        assert signed.verify_facts(verifier=fake_fact_verifier(KEYS))["ok"] is True
