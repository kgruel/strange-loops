"""Fact signatures travel through transport — delta 3 at the store-ops layer.

The asymmetry under test (design/fact-signature-at-store-column): fact
signatures are authorship claims over content only, so slice/merge/rebirth
carry them VERBATIM — while tick chain columns (receipt custody) stay
stripped. Era-aware on both sides: sources predating the column produce
NULL, never an error.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from atoms import Fact

from store import merge_store, rebirth_store, slice_store, verify_rebirth
from store.rebirth import FactRow, Transform, ulid_migration


def fact_signer(observer: str, digest: str) -> str | None:
    if observer != "keyed":
        return None
    return hashlib.sha256(f"secret:{digest}".encode()).hexdigest()


def make_signed_store(path: Path, n: int = 2) -> list[str]:
    """Engine store with a per-observer signer; returns fact ids."""
    from engine import SqliteStore

    store = SqliteStore(
        path=path,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=fact_signer,
    )
    ids = []
    for i in range(n):
        obs = "keyed" if i % 2 == 0 else "unkeyed"
        ids.append(store.append(Fact.of("note", obs, body=f"fact-{i}")))
    store.close()
    return ids


def make_pre_delta3_store(path: Path) -> None:
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
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?,?,?,?,?,?)",
        ("01OLDROWAAAAAAAAAAAAAAAAAA", "note", 100.0, "keyed", "", '{"body": "old"}'),
    )
    conn.commit()
    conn.close()


def sigs(path: Path) -> dict[str, str | None]:
    conn = sqlite3.connect(str(path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(facts)")}
        if "signature" not in cols:
            return {}
        return dict(conn.execute("SELECT id, signature FROM facts"))
    finally:
        conn.close()


class TestMergeCarriesSignature:
    def test_signature_travels(self, tmp_path: Path):
        src, tgt = tmp_path / "src.db", tmp_path / "tgt.db"
        ids = make_signed_store(src)
        make_signed_store(tgt, n=0)
        merge_store(tgt, src)
        src_sigs, tgt_sigs = sigs(src), sigs(tgt)
        for fid in ids:
            assert tgt_sigs[fid] == src_sigs[fid]
        assert any(v is not None for v in tgt_sigs.values())
        assert any(v is None for v in tgt_sigs.values())  # unkeyed stays NULL

    def test_pre_delta3_source_merges_as_null(self, tmp_path: Path):
        src, tgt = tmp_path / "old.db", tmp_path / "tgt.db"
        make_pre_delta3_store(src)
        make_signed_store(tgt, n=1)
        result = merge_store(tgt, src)
        assert result.facts_added == 1
        assert sigs(tgt)["01OLDROWAAAAAAAAAAAAAAAAAA"] is None

    def test_pre_delta3_target_gains_column_when_source_signed(self, tmp_path: Path):
        src, tgt = tmp_path / "src.db", tmp_path / "old.db"
        ids = make_signed_store(src)
        make_pre_delta3_store(tgt)
        merge_store(tgt, src)
        tgt_sigs = sigs(tgt)
        assert tgt_sigs  # column exists now
        assert tgt_sigs[ids[0]] is not None


class TestSliceCarriesSignature:
    def test_signature_travels(self, tmp_path: Path):
        src, out = tmp_path / "src.db", tmp_path / "out.db"
        ids = make_signed_store(src)
        slice_store(source=src, target=out)
        assert sigs(out)[ids[0]] == sigs(src)[ids[0]]

    def test_pre_delta3_source_slices_as_null(self, tmp_path: Path):
        src, out = tmp_path / "old.db", tmp_path / "out.db"
        make_pre_delta3_store(src)
        slice_store(source=src, target=out)
        assert sigs(out)["01OLDROWAAAAAAAAAAAAAAAAAA"] is None


class TestRebirthCarriesSignature:
    def test_id_migration_preserves_signature(self, tmp_path: Path):
        """Content-only commitment pays off: re-minting the id leaves the
        authorship signature valid, so rebirth carries it verbatim."""
        src, tgt = tmp_path / "src.db", tmp_path / "reborn.db"
        # uuid4-style id forces migration
        conn_ids = make_signed_store(src)
        conn = sqlite3.connect(str(src))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
            "VALUES (?,?,?,?,?,?,?)",
            ("deadbeef-0000-4000-8000-000000000000", "note", 50.0, "keyed",
             "", '{"body": "uuid era"}', "carried-sig"),
        )
        conn.commit()
        conn.close()
        result = rebirth_store(src, tgt, transform=ulid_migration())
        assert result.ids_migrated == 1
        tgt_sigs = sigs(tgt)
        src_sigs = sigs(src)
        assert tgt_sigs[conn_ids[0]] == src_sigs[conn_ids[0]]  # untouched id
        migrated = [s for s in tgt_sigs.values() if s == "carried-sig"]
        assert migrated  # signature survived the id migration

    def test_content_change_drops_signature(self, tmp_path: Path):
        src, tgt = tmp_path / "src.db", tmp_path / "reborn.db"
        make_signed_store(src)
        redact = Transform(
            rule="redact",
            map_fact=lambda r: FactRow(
                r.id, r.kind, r.ts, r.observer, r.origin,
                '{"body": "[redacted]"}', r.signature,
            ),
        )
        rebirth_store(src, tgt, transform=redact)
        conn = sqlite3.connect(str(tgt))
        redacted = conn.execute(
            "SELECT signature FROM facts WHERE payload = ?",
            ('{"body": "[redacted]"}',),
        ).fetchall()
        conn.close()
        assert redacted and all(s[0] is None for s in redacted)

    def test_verify_rebirth_checks_signatures_roundtrip(self, tmp_path: Path):
        src, tgt = tmp_path / "src.db", tmp_path / "reborn.db"
        make_signed_store(src)
        rebirth_store(src, tgt)
        v = verify_rebirth(src, tgt)
        assert v.ok is True
        # Tampering with a carried signature is a row mismatch on re-run
        conn = sqlite3.connect(str(tgt))
        conn.execute(
            "UPDATE facts SET signature = 'forged' WHERE signature IS NOT NULL"
        )
        conn.commit()
        conn.close()
        v2 = verify_rebirth(src, tgt)
        assert v2.ok is False
        assert any("signature" in m for m in v2.mismatches)
