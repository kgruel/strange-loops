"""Tests for store.rebirth — transform-replay with receipt and genesis seal."""

from __future__ import annotations

import json
import sqlite3

import pytest
from ulid import ULID

from store.rebirth import (
    FactRow,
    deterministic_ulid,
    filtered,
    identity,
    is_ulid,
    rebirth_store,
    ulid_migration,
    verify_rebirth,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID_IDS = (
    "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "9b2e7c1a-3d4f-4b6a-8c9d-1e2f3a4b5c6d",
)

_BASE_TS = 1700000000.0


def _fake_signer(digest: str) -> str:
    return "FAKESIG:" + digest


def _fake_verifier(signature: str, digest: str) -> bool:
    return signature == "FAKESIG:" + digest


def _make_source(path, *, mixed_era=True, legacy_tick=True, signed_tick=False):
    """Build a source store: optionally mixed-id-era facts, a legacy
    (pre-chain) tick, and a chained+signed tick appended through the
    engine (the production write path)."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""\
        CREATE TABLE facts (
            id       TEXT NOT NULL PRIMARY KEY,
            kind     TEXT NOT NULL,
            ts       REAL NOT NULL,
            observer TEXT NOT NULL,
            origin   TEXT NOT NULL DEFAULT '',
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
        CREATE TABLE ticks (
            id       TEXT NOT NULL PRIMARY KEY,
            name     TEXT NOT NULL,
            ts       REAL NOT NULL,
            since    REAL,
            origin   TEXT NOT NULL,
            payload  TEXT NOT NULL CHECK (json_valid(payload))
        );
    """)
    rows = []
    if mixed_era:
        # uuid4 era first (witness order), then ULID era — note the uuid
        # ids SORT ABOVE every ULID, the exact wedge rebirth migrates.
        for i, uid in enumerate(_UUID_IDS):
            rows.append((uid, "decision", _BASE_TS + i, "kyle", "",
                         json.dumps({"topic": f"old/{i}", "message": "uuid era"})))
    for i in range(3):
        rows.append((str(ULID()), "thread", _BASE_TS + 100 + i, "kyle", "",
                     json.dumps({"name": f"arc-{i}", "status": "open"})))
    conn.executemany(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)", rows)
    if legacy_tick:
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(ULID()), "session", _BASE_TS + 50, _BASE_TS, "test",
             json.dumps({"facts": 2})))
    conn.commit()
    conn.close()

    if signed_tick:
        from datetime import UTC, datetime

        from engine import SqliteStore, Tick

        estore = SqliteStore(
            path=path,
            serialize=lambda d: d,
            deserialize=lambda d: d,
            tick_signer=_fake_signer,
        )
        estore.append_tick(Tick(
            name="seal",
            ts=datetime.fromtimestamp(_BASE_TS + 200, tz=UTC),
            origin="test",
            payload={"reason": "pre-rebirth seal"},
        ))
        estore.close()


def _facts(path, *, exclude_receipt=False):
    conn = sqlite3.connect(str(path))
    rows = conn.execute(
        "SELECT id, kind, ts, observer, origin, payload "
        "FROM facts ORDER BY rowid").fetchall()
    conn.close()
    if exclude_receipt:
        rows = [r for r in rows if r[1] != "rebirth"]
    return rows


def _ticks(path):
    conn = sqlite3.connect(str(path))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ticks)")]
    rows = [dict(zip(cols, r, strict=True)) for r in conn.execute(
        "SELECT * FROM ticks ORDER BY rowid")]
    conn.close()
    return rows


def _verify_chain(path, verifier=None):
    from engine import SqliteStore

    estore = SqliteStore(path=path, serialize=lambda d: d,
                         deserialize=lambda d: d)
    report = estore.verify_chain(verifier=verifier)
    estore.close()
    return report


# ---------------------------------------------------------------------------
# Rebirth
# ---------------------------------------------------------------------------

def test_identity_rebirth_counts_and_receipt(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    result = rebirth_store(src, dst, transform=identity())

    assert result.facts_in == 5
    assert result.facts_out == 5
    assert result.filtered == 0
    assert result.ids_migrated == 0
    assert result.ticks_in == 1
    assert result.tick_facts == 1
    assert not result.tick_signed

    facts = _facts(dst)
    # 5 replayed + 1 tick re-entry + 1 receipt
    assert len(facts) == 7
    receipt = facts[-1]
    assert receipt[1] == "rebirth"
    assert receipt[0] == result.receipt_id
    payload = json.loads(receipt[5])
    assert payload["rule"] == "identity"
    assert payload["source_facts"] == 5
    assert payload["source_ticks"] == 1
    assert len(payload["source_content_sha256"]) == 64
    assert len(payload["source_file_sha256"]) == 64


def test_genesis_tick_seals_everything_including_receipt(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    result = rebirth_store(src, dst)

    ticks = _ticks(dst)
    assert len(ticks) == 1
    genesis = ticks[0]
    assert genesis["name"] == "rebirth"
    assert genesis["window_start"] == ""          # covers all
    assert genesis["fact_cursor"] == result.receipt_id  # seal semantics

    report = _verify_chain(dst)
    assert report["ok"]
    assert report["chained"] == 1
    assert report["legacy"] == 0
    assert report["covered_facts"] == 7
    assert report["uncovered_facts"] == 0


def test_genesis_tick_signed_when_signer_injected(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    result = rebirth_store(src, dst, tick_signer=_fake_signer)

    assert result.tick_signed
    assert _ticks(dst)[0]["signature"].startswith("FAKESIG:")
    report = _verify_chain(dst, verifier=_fake_verifier)
    assert report["ok"]
    assert report["signed"] == 1


def test_ulid_migration_migrates_only_uuid_era(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    result = rebirth_store(src, dst, transform=ulid_migration())

    assert result.ids_migrated == 2
    src_ids = [r[0] for r in _facts(src)]
    dst_ids = [r[0] for r in _facts(dst, exclude_receipt=True)[:5]]
    # uuid ids replaced with ULIDs; ULID ids untouched
    for old, new in zip(src_ids, dst_ids, strict=True):
        if is_ulid(old):
            assert new == old
        else:
            assert is_ulid(new)
            assert new == deterministic_ulid(
                _facts(src)[src_ids.index(old)][2], old)
    # event-time sortable: migrated ids now sort BELOW the later ULIDs
    assert sorted(dst_ids) == dst_ids


def test_ulid_migration_is_deterministic(tmp_path):
    src = tmp_path / "src.db"
    _make_source(src)
    rebirth_store(src, tmp_path / "a.db", transform=ulid_migration())
    rebirth_store(src, tmp_path / "b.db", transform=ulid_migration())
    # Identical replayed rows — only the receipt (fresh id/ts) differs.
    assert (_facts(tmp_path / "a.db", exclude_receipt=True)
            == _facts(tmp_path / "b.db", exclude_receipt=True))


def test_filtered_transform_drops_and_counts(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    result = rebirth_store(
        src, dst,
        transform=filtered(lambda r: r.kind != "decision",
                           rule="filter:kind!=decision"),
    )
    assert result.filtered == 2
    assert result.facts_out == 3
    kinds = {r[1] for r in _facts(dst)}
    assert "decision" not in kinds


def test_tick_reentry_preserves_envelope_verbatim(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src, signed_tick=True)
    rebirth_store(src, dst, transform=ulid_migration())

    source_ticks = _ticks(src)
    tick_facts = [r for r in _facts(dst) if r[1].startswith("tick.")]
    assert len(tick_facts) == len(source_ticks) == 2

    by_old_id = {json.loads(r[5])["tick_id"]: r for r in tick_facts}
    for st in source_ticks:
        fact = by_old_id[st["id"]]
        payload = json.loads(fact[5])
        # Envelope verbatim — every column byte-equal, signature intact,
        # cursors still OLD ids (the signature only verifies original bytes).
        assert payload["name"] == st["name"]
        assert payload["payload"] == st["payload"]
        assert payload["since"] == st["since"]
        assert payload["prev_hash"] == st.get("prev_hash")
        assert payload["window_start"] == st.get("window_start")
        assert payload["fact_cursor"] == st.get("fact_cursor")
        assert payload["window_hash"] == st.get("window_hash")
        assert payload["signature"] == st.get("signature")
        assert fact[1] == f"tick.{st['name']}"
        assert fact[2] == st["ts"]
        assert fact[3] == "src"  # observer = source name (file stem)

    signed = json.loads(by_old_id[source_ticks[-1]["id"]][5])
    assert signed["signature"].startswith("FAKESIG:")


def test_source_chain_head_recorded(tmp_path):
    from engine import tick_row_hash

    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src, signed_tick=True)
    rebirth_store(src, dst)

    receipt = json.loads(_facts(dst)[-1][5])
    last = _ticks(src)[-1]
    cols = ("id", "name", "ts", "since", "origin", "payload", "prev_hash",
            "window_start", "fact_cursor", "window_hash", "signature")
    assert receipt["source_chain_head"] == tick_row_hash(
        tuple(last.get(c) for c in cols))


def test_target_exists_refused(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    dst.touch()
    with pytest.raises(FileExistsError):
        rebirth_store(src, dst)


def test_source_missing_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        rebirth_store(tmp_path / "absent.db", tmp_path / "dst.db")


def test_source_never_modified(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    before = _facts(src), _ticks(src)
    rebirth_store(src, dst, transform=ulid_migration())
    assert (_facts(src), _ticks(src)) == before


# ---------------------------------------------------------------------------
# Verification — re-run the transform, diff
# ---------------------------------------------------------------------------

def test_verify_clean_identity(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    rebirth_store(src, dst)
    v = verify_rebirth(src, dst)  # transform reconstructed from receipt
    assert v.ok
    assert v.receipt_found and v.counts_match
    assert v.source_content_match and v.chain_ok
    assert v.mismatches == ()


def test_verify_clean_ulid_migration_with_signatures(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src, signed_tick=True)
    rebirth_store(src, dst, transform=ulid_migration(),
                  tick_signer=_fake_signer)
    v = verify_rebirth(src, dst, verifier=_fake_verifier)
    assert v.ok


def test_verify_detects_target_tamper(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    rebirth_store(src, dst)
    conn = sqlite3.connect(str(dst))
    conn.execute("UPDATE facts SET payload = json('{\"forged\": true}') "
                 "WHERE kind = 'thread' AND rowid = "
                 "(SELECT MIN(rowid) FROM facts WHERE kind = 'thread')")
    conn.commit()
    conn.close()
    v = verify_rebirth(src, dst)
    assert not v.ok
    assert v.mismatches  # the diff names the row
    assert not v.chain_ok  # window_hash breaks too — two independent claims


def test_verify_detects_source_change_after_rebirth(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    rebirth_store(src, dst)
    conn = sqlite3.connect(str(src))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (str(ULID()), "thread", _BASE_TS + 999, "kyle", "", "{}"))
    conn.commit()
    conn.close()
    v = verify_rebirth(src, dst)
    assert not v.ok
    assert not v.source_content_match
    assert v.mismatches  # row-count diff as well


def test_verify_filter_rule_requires_explicit_transform(tmp_path):
    src, dst = tmp_path / "src.db", tmp_path / "dst.db"
    _make_source(src)
    transform = filtered(lambda r: r.kind != "decision",
                         rule="filter:kind!=decision")
    rebirth_store(src, dst, transform=transform)
    with pytest.raises(ValueError, match="pass the original Transform"):
        verify_rebirth(src, dst)
    assert verify_rebirth(src, dst, transform=transform).ok


def test_deterministic_ulid_properties():
    a = deterministic_ulid(_BASE_TS, "seed-1")
    assert a == deterministic_ulid(_BASE_TS, "seed-1")  # deterministic
    assert a != deterministic_ulid(_BASE_TS, "seed-2")  # seed-sensitive
    assert is_ulid(a)
    # timestamp prefix matches a fresh ULID from the same ms
    assert a[:10] == str(ULID.from_timestamp(_BASE_TS))[:10]


def test_is_ulid_shape():
    assert is_ulid(str(ULID()))
    assert not is_ulid(_UUID_IDS[0])
    assert not is_ulid("")
    assert not is_ulid("0" * 25)
    # Lowercase ULIDs (sqlite-ulid era) are NOT canonical — lowercase
    # sorts above uppercase in ASCII, so that era is order-broken too.
    assert not is_ulid(str(ULID()).lower())


def test_lowercase_ulid_era_is_migrated():
    row = FactRow(id=str(ULID()).lower(), kind="decision", ts=_BASE_TS,
                  observer="kyle", origin="", payload="{}")
    mapped = ulid_migration().map_fact(row)
    assert mapped is not None
    assert mapped.id != row.id
    assert is_ulid(mapped.id)
    assert mapped.id == deterministic_ulid(_BASE_TS, row.id)


def test_factrow_transform_contract():
    row = FactRow(id=_UUID_IDS[0], kind="decision", ts=_BASE_TS,
                  observer="kyle", origin="", payload="{}")
    mapped = ulid_migration().map_fact(row)
    assert mapped is not None
    assert mapped.id != row.id and is_ulid(mapped.id)
    assert (mapped.kind, mapped.ts, mapped.observer, mapped.payload) == \
           (row.kind, row.ts, row.observer, row.payload)
