"""Genesis primitive + reserved-namespace ingest guard (SPEC §9.2 S1).

``SqliteStore.absorb_genesis`` is the atomic lineage-opening write: identity
check + era pins + sign-final-payload + append in ONE transaction. Signing
uses a fake callable (engine's contract is the callable, not Ed25519 — same
posture as test_fact_signing).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact

from engine import Tick, Vertex
from engine.sqlite_store import (
    GenesisExists,
    SqliteStore,
    UnsignableGenesis,
)
from engine.vertex import ReservedKindError
from lang.document import DECL_GENESIS


def _signer(secret: str | None):
    """Fake per-observer signer: returns a signature unless secret is None."""
    def signer(observer: str, digest: str) -> str | None:
        if secret is None:
            return None
        return hashlib.sha256(f"{secret}:{observer}:{digest}".encode()).hexdigest()
    return signer


def _store(path: Path) -> SqliteStore[Fact]:
    return SqliteStore(
        path=path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )


_DOCS = [
    {"kind": "_decl.vertex-defined", "subject": "x", "payload": {"name": "x"}},
    {"kind": "_decl.kind-defined", "subject": "ping", "payload": {"order": 0}},
]


class TestAbsorbGenesisPrimitive:
    def test_writes_signed_genesis_with_pins(self, tmp_path):
        db = tmp_path / "x.db"
        receipt = _store(db).absorb_genesis(
            _DOCS, observer="x", fact_signer=_signer("k")
        )
        assert receipt["documents"] == 2
        assert receipt["signed"] is True
        assert receipt["chain_head"] is None  # no ticks
        assert receipt["fact_cursor"] is None  # empty store

        conn = sqlite3.connect(str(db))
        row = conn.execute(
            "SELECT id, observer, payload, signature FROM facts WHERE kind=?",
            (DECL_GENESIS,),
        ).fetchone()
        conn.close()
        gid, observer, payload_text, signature = row
        assert gid == receipt["lineage"]  # genesis id IS the lineage id
        assert observer == "x"
        assert signature  # signed
        payload = json.loads(payload_text)
        assert payload["protocol"] == 1
        assert payload["documents"] == _DOCS

    def test_double_absorb_refuses_and_writes_once(self, tmp_path):
        db = tmp_path / "x.db"
        _store(db).absorb_genesis(_DOCS, observer="x", fact_signer=_signer("k"))
        with pytest.raises(GenesisExists):
            _store(db).absorb_genesis(_DOCS, observer="x", fact_signer=_signer("k"))
        conn = sqlite3.connect(str(db))
        n = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE kind=?", (DECL_GENESIS,)
        ).fetchone()[0]
        conn.close()
        assert n == 1

    def test_unsignable_rolls_back(self, tmp_path):
        db = tmp_path / "x.db"
        with pytest.raises(UnsignableGenesis):
            _store(db).absorb_genesis(_DOCS, observer="x", fact_signer=_signer(None))
        # Rolled back — no genesis row written (the store file exists, empty).
        conn = sqlite3.connect(str(db))
        n = conn.execute(
            "SELECT COUNT(*) FROM facts WHERE kind=?", (DECL_GENESIS,)
        ).fetchone()[0]
        conn.close()
        assert n == 0

    def test_no_signer_refuses(self, tmp_path):
        db = tmp_path / "x.db"
        with pytest.raises(UnsignableGenesis):
            _store(db).absorb_genesis(_DOCS, observer="x", fact_signer=None)

    def test_pins_reflect_existing_facts_and_ticks(self, tmp_path):
        db = tmp_path / "x.db"
        s = _store(db)
        s.append(Fact(kind="ping", ts=1.0, payload={"n": 1}, observer="x"))
        newest = s.append(Fact(kind="ping", ts=2.0, payload={"n": 2}, observer="x"))
        s.append_tick(
            Tick(name="ping", ts=datetime.now(UTC), payload={"n": 2}, origin="x")
        )
        expected_head = s.current_chain_head()
        assert expected_head is not None

        receipt = s.absorb_genesis(_DOCS, observer="x", fact_signer=_signer("k"))
        assert receipt["fact_cursor"] == newest  # newest pre-genesis fact
        assert receipt["chain_head"] == expected_head  # actual tick chain head
        s.close()


class TestReservedKindIngestGuard:
    def test_receive_refuses_decl_kind_when_store_attached(self, tmp_path):
        store = _store(tmp_path / "x.db")
        v = Vertex("x", store=store)
        with pytest.raises(ReservedKindError):
            v.receive(
                Fact(kind=DECL_GENESIS, ts=1.0, payload={}, observer="x"), grant=None
            )
        # Nothing persisted — the guard fires before the append.
        assert store.total == 0
        store.close()

    def test_storeless_receive_allows_decl_kind_for_replay(self, tmp_path):
        # Standalone replay feeds stored facts into a STORELESS vertex; a
        # historical _decl.genesis must fold through harmlessly (unregistered
        # kind), never trip the guard.
        v = Vertex("x")  # no store attached
        v.register("ping", 0, lambda s, p: s + 1)
        v.receive(Fact(kind=DECL_GENESIS, ts=1.0, payload={}, observer="x"), grant=None)
        v.receive(Fact(kind="ping", ts=2.0, payload={}, observer="x"), grant=None)
        assert v.state("ping") == 1  # ping folded; genesis passed through
