"""ArrivalStore — rows land in the arrival log first; the index consumes.

Cut A store mechanics (decision:design/arrival-sliceA-authority §4.3/§4.4):
the write seam, the three-field resume mark, consume-or-refuse catch-up,
and the two ceremony re-points (absorb projects the arrival lineage; adopt
refuses). The authority and exclusivity gates live in
``test_arrival_authority_gate.py``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import DECL_GENESIS, vertex_to_documents
from sign import ed25519

from engine.arrival import ArrivalLog, GenesisRefused
from engine.arrival_store import (
    ARRIVAL_LINEAGE_KEY,
    ARRIVAL_OFFSET_KEY,
    ARRIVAL_ORDINAL_KEY,
    ArrivalCanonicalUnsupported,
    ArrivalStore,
    ensure_arrival_index,
)
from engine.tick import Tick

_DOMAIN = "test-arrival-v1"

BASE = (
    'name "x"\nstore "./x.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n}\n'
)


@pytest.fixture
def keys(tmp_path):
    return ed25519.load_or_generate(tmp_path / "keys")


@pytest.fixture
def signer(keys):
    def sign(observer: str, digest: str) -> str | None:
        return ed25519.sign(keys, digest.encode(), domain=_DOMAIN)

    return sign


def _verify(key_b64: str, signature: str, digest: str) -> bool:
    try:
        public = ed25519.public_key_from_b64(key_b64)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=_DOMAIN)


def mint(tmp_path, keys, signer, name: str = "s") -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / f"{name}.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public_b64,
    )


def open_store(tmp_path, name: str = "s", **kw) -> ArrivalStore:
    return ArrivalStore(
        path=tmp_path / f"{name}.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        **kw,
    )


def fact(kind: str = "note", observer: str = "kyle", **payload) -> Fact:
    return Fact.of(kind, observer, **(payload or {"message": "hi"}))


def records_of(log_path: Path) -> list[dict]:
    return list(ArrivalLog(log_path).walk())


# --- open + write path ------------------------------------------------------


def test_open_canonical_store_routes_an_arrival_locator(tmp_path, keys, signer):
    from engine.jsonl_store import open_canonical_store

    mint(tmp_path, keys, signer)
    store = open_canonical_store(
        tmp_path / "s.arrival",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    try:
        assert isinstance(store, ArrivalStore)
        assert store.log_path == tmp_path / "s.arrival"
        assert store._path == tmp_path / "s.db"
    finally:
        store.close()


def test_an_unminted_log_opens_empty_and_refuses_appends(tmp_path):
    store = open_store(tmp_path)
    try:
        with pytest.raises(GenesisRefused, match="mint a genesis first"):
            store.append(fact())
    finally:
        store.close()
    assert not (tmp_path / "s.arrival").exists()


def test_appends_land_in_the_log_first_as_records(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path, fact_signer=signer)
    try:
        store.append(fact(message="one"))
        store.append(fact(message="two"))
    finally:
        store.close()

    records = records_of(tmp_path / "s.arrival")
    assert [r["k"] for r in records] == ["genesis", "fact", "fact"]
    body = records[1]["body"]
    assert body["t"] == "fact"
    assert body["kind"] == "note"
    # payload rides as the verbatim stored TEXT, never re-serialized
    assert isinstance(body["payload"], str)
    assert json.loads(body["payload"])["message"] == "one"
    # the record's own signature is the arrival attestation; the row's
    # signature (over the fact commitment) rides inside body as data
    assert "sig" in records[1]
    assert body.get("signature")


def test_the_stamped_mark_is_the_ratified_three_fields_and_exact(
    tmp_path, keys, signer
):
    log = mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact())
        lineage = store._meta_get(ARRIVAL_LINEAGE_KEY)
        offset = int(store._meta_get(ARRIVAL_OFFSET_KEY))
        ordinal = int(store._meta_get(ARRIVAL_ORDINAL_KEY))
    finally:
        store.close()
    assert lineage == log.lineage()
    assert offset == (tmp_path / "s.arrival").stat().st_size
    assert ordinal == 1
    # the retired cursor keys never appear for an arrival store
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        meta_keys = {r[0] for r in conn.execute("SELECT key FROM store_meta")}
    finally:
        conn.close()
    assert not any(k.startswith("jsonl") for k in meta_keys)


def test_ticks_ride_as_records_with_the_ticks_own_authorship(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact())
        store.append_tick(
            Tick(name="pulse", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
        )
    finally:
        store.close()
    records = records_of(tmp_path / "s.arrival")
    assert [r["k"] for r in records] == ["genesis", "fact", "tick"]
    tick_record = records[2]
    assert tick_record["observer"] == "pulse"  # a tick's authorship is its name
    assert tick_record["body"]["t"] == "tick"


def test_a_rejected_insert_never_orphans_a_record(tmp_path, keys, signer):
    import sqlite3

    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        first = store.append(fact(message="one"))
        before = (tmp_path / "s.arrival").read_bytes()
        with pytest.raises(sqlite3.IntegrityError):
            store.append(fact(message="dup"), id_override=first)
        assert (tmp_path / "s.arrival").read_bytes() == before
    finally:
        store.close()


# --- catch-up: consume or refuse, never rebuild ------------------------------


def test_an_absent_index_builds_forward_from_the_log(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact(message="survives"))
    finally:
        store.close()

    before = (tmp_path / "s.arrival").read_bytes()
    (tmp_path / "s.db").unlink()

    index = ensure_arrival_index(tmp_path / "s.arrival")
    assert index == tmp_path / "s.db"
    assert index.exists()
    from engine import StoreReader

    with StoreReader(index) as reader:
        assert reader.summary()["facts"]["total"] == 1
    # building is read-only with respect to the log
    assert (tmp_path / "s.arrival").read_bytes() == before


def test_a_reopened_store_tails_records_appended_out_of_band(tmp_path, keys, signer):
    log = mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact(message="one"))
    finally:
        store.close()

    # A second writer appends straight to the log (another process's store).
    row = json.dumps(
        {
            "t": "fact",
            "id": "01TESTID000000000000000000",
            "kind": "note",
            "ts": 2.0,
            "observer": "kyle",
            "origin": "",
            "payload": json.dumps({"message": "two"}),
        }
    )
    log.append("fact", json.loads(row), observer="kyle")

    store = open_store(tmp_path)
    try:
        assert store.catch_up() == "synced"  # the open already tailed it
        ids = [
            r[0]
            for r in store._db.execute("SELECT id FROM facts ORDER BY rowid")
        ]
    finally:
        store.close()
    assert ids[-1] == "01TESTID000000000000000000"


def test_rows_without_a_mark_refuse_rather_than_rebuild(tmp_path, keys, signer):
    import sqlite3

    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact())
    finally:
        store.close()

    # Strip the mark, keep the rows: only re-derivation could reconcile.
    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        for key in (ARRIVAL_LINEAGE_KEY, ARRIVAL_OFFSET_KEY, ARRIVAL_ORDINAL_KEY):
            conn.execute("DELETE FROM store_meta WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ArrivalCanonicalUnsupported, match="re-deriv"):
        open_store(tmp_path)


def test_a_mark_the_log_rejects_refuses_rather_than_rebuilds(tmp_path, keys, signer):
    import sqlite3

    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact())
    finally:
        store.close()

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        conn.execute(
            "UPDATE store_meta SET value = ? WHERE key = ?",
            ("7", ARRIVAL_OFFSET_KEY),  # not a record boundary
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ArrivalCanonicalUnsupported, match="rejects"):
        open_store(tmp_path)


def test_an_index_without_its_log_refuses(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        store.append(fact())
    finally:
        store.close()
    (tmp_path / "s.arrival").unlink()
    with pytest.raises(ArrivalCanonicalUnsupported, match="no.*arrival log"):
        open_store(tmp_path)


# --- ceremonies --------------------------------------------------------------


def _docs():
    return [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]


def test_absorb_projects_the_arrival_lineage_and_sheds_the_pins(
    tmp_path, keys, signer
):
    log = mint(tmp_path, keys, signer)
    store = open_store(tmp_path, fact_signer=signer)
    try:
        store.append(fact(observer="kyle"))
        receipt = store.absorb_genesis(_docs(), observer="kyle", fact_signer=signer)
        assert receipt["lineage"] == log.lineage()
        assert receipt["chain_head"] is None and receipt["fact_cursor"] is None

        row = store._db.execute(
            "SELECT id, payload FROM facts WHERE kind = ?", (DECL_GENESIS,)
        ).fetchone()
        # the row id IS the lineage id — the legacy invariant, projected
        # from the arrival genesis now
        assert row[0] == log.lineage()
        payload = json.loads(row[1])
        assert set(payload) == {"protocol", "documents"}

        own = store._db.execute(
            "SELECT value FROM store_meta WHERE key = 'own_lineage'"
        ).fetchone()[0]
        assert own == log.lineage()
    finally:
        store.close()

    # the ceremony landed as ONE record in the log
    kinds = [r["k"] for r in records_of(tmp_path / "s.arrival")]
    assert kinds == ["genesis", "fact", "fact"]


def test_absorb_without_an_arrival_genesis_refuses_with_the_movement_order(
    tmp_path, signer
):
    store = open_store(tmp_path)
    try:
        with pytest.raises(GenesisRefused, match="movement 2"):
            store.absorb_genesis(_docs(), observer="kyle", fact_signer=signer)
    finally:
        store.close()


def test_adopt_refuses_structurally(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        with pytest.raises(ArrivalCanonicalUnsupported, match="ordinal 0"):
            store.adopt_lineage()
    finally:
        store.close()


def test_reanchor_stays_refused(tmp_path, keys, signer):
    mint(tmp_path, keys, signer)
    store = open_store(tmp_path)
    try:
        with pytest.raises(ArrivalCanonicalUnsupported, match="reanchor"):
            store.reanchor()
    finally:
        store.close()


def test_legacy_absorb_payload_is_untouched(tmp_path):
    """Seam rule S3: the sqlite-canonical ceremony keeps its pins and its
    freshly minted lineage id, byte for byte."""
    import hashlib

    from engine.sqlite_store import SqliteStore

    store: SqliteStore = SqliteStore(
        path=tmp_path / "legacy.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )
    try:
        receipt = store.absorb_genesis(
            _docs(),
            observer="obs",
            fact_signer=lambda o, d: hashlib.sha256(f"{o}{d}".encode()).hexdigest(),
        )
        row = store._conn.execute(
            "SELECT id, payload FROM facts WHERE kind = ?", (DECL_GENESIS,)
        ).fetchone()
        payload = json.loads(row[1])
        assert set(payload) == {"protocol", "documents", "chain_head", "fact_cursor"}
        assert receipt["lineage"] == row[0] != ""
    finally:
        store.close()
