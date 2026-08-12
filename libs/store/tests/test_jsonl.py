"""Oracle tests for store.jsonl — export → rebuild must be hash-identical.

The migration oracle for design/architecture/jsonl-canonical-store. Fixture
stores cover all three eras (pre-chain, chained, signed) and both the
uuid4 and ULID id eras; the round-trip must preserve counts, row hashes,
the chain head, and chain/fact verification.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from ulid import ULID

from store.jsonl import _receipt_order, export_jsonl, rebuild_jsonl

_BASE_TS = 1700000000.0
_UUID_IDS = (
    "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "9b2e7c1a-3d4f-4b6a-8c9d-1e2f3a4b5c6d",
)


def _fake_signer(digest: str) -> str:
    return "FAKESIG:" + digest


def _fake_verifier(signature: str, digest: str) -> bool:
    return signature == "FAKESIG:" + digest


def _fake_fact_signer(observer: str, digest: str) -> str | None:
    # Per-observer authorship: only 'kyle' holds a key — 'guest' facts stay
    # honestly unsigned, exercising the mixed per-observer era.
    return "FAKESIG:" + digest if observer == "kyle" else None


# ---------------------------------------------------------------------------
# Fixture stores
# ---------------------------------------------------------------------------

def _make_store(path, *, prechain=True, chained=True, signed=True):
    """Build a store spanning the eras asked for.

    prechain: legacy narrow schema rows (NULL chain columns, no signature
    columns at all) written before the chain existed.
    chained: an unsigned chained tick through engine.append_tick.
    signed: signed facts + a signed chained tick.
    """
    if prechain:
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
        rows = [
            (uid, "decision", _BASE_TS + i, "kyle", "",
             json.dumps({"topic": f"old/{i}", "message": "uuid era ünïcode"}))
            for i, uid in enumerate(_UUID_IDS)
        ]
        conn.executemany(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.execute(
            "INSERT INTO ticks (id, name, ts, since, origin, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(ULID()), "session", _BASE_TS + 50, _BASE_TS, "test",
             json.dumps({"facts": 2})))
        conn.commit()
        conn.close()

    from engine import SqliteStore, Tick

    if chained:
        store = SqliteStore(path=path, serialize=lambda d: d,
                            deserialize=lambda d: d)
        _append_facts(store, 3, "kyle", _BASE_TS + 100)
        store.append_tick(Tick(
            name="seal", ts=datetime.fromtimestamp(_BASE_TS + 150, tz=UTC),
            origin="test", payload={"reason": "unsigned chained"},
        ), enforce_floor=False)
        store.close()

    if signed:
        store = SqliteStore(path=path, serialize=lambda d: d,
                            deserialize=lambda d: d,
                            tick_signer=_fake_signer,
                            fact_signer=_fake_fact_signer)
        _append_facts(store, 2, "kyle", _BASE_TS + 200)
        _append_facts(store, 1, "guest", _BASE_TS + 210)
        store.append_tick(Tick(
            name="seal", ts=datetime.fromtimestamp(_BASE_TS + 250, tz=UTC),
            origin="test", payload={"reason": "signed"},
        ))
        # A second tick with NO new facts — same fact_cursor as the one
        # above, exercising the tie-break on tick append order.
        store.append_tick(Tick(
            name="seal", ts=datetime.fromtimestamp(_BASE_TS + 260, tz=UTC),
            origin="test", payload={"reason": "no new facts"},
        ))
        store.close()
    return path


def _append_facts(store, n, observer, base):
    """Append facts through the production write path (engine.append).

    The store's serializer is identity, so the "event" is already the dict
    shape append() consumes — no atoms dependency in libs/store.
    """
    for i in range(n):
        store.append({
            "kind": "thread",
            "ts": base + i,
            "observer": observer,
            "origin": "",
            "payload": {"name": f"arc-{observer}-{i}", "status": "open"},
        })


# ---------------------------------------------------------------------------
# Row readers / hash helpers
# ---------------------------------------------------------------------------

def _rows(path, table, cols):
    """Read rows at full arity — narrow (pre-chain) schemas select NULL for
    the columns they do not have, independently of the code under test."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    sql = ", ".join(c if c in have else "NULL" for c in cols)
    out = [tuple(raw) for raw in
           conn.execute(f"SELECT {sql} FROM {table} ORDER BY rowid")]
    conn.close()
    return out


_FACT_COLS = ("id", "kind", "ts", "observer", "origin", "payload", "signature")
_TICK_COLS = ("id", "name", "ts", "since", "origin", "payload", "prev_hash",
              "window_start", "fact_cursor", "window_hash", "signature")


def _fact_rows(path):
    return _rows(path, "facts", _FACT_COLS)


def _tick_rows(path):
    return _rows(path, "ticks", _TICK_COLS)


def _chain_head(path):
    from engine import SqliteStore

    store = SqliteStore(path=path, serialize=lambda d: d, deserialize=lambda d: d)
    head = store.current_chain_head()
    store.close()
    return head


def _verify(path):
    from engine import SqliteStore

    store = SqliteStore(path=path, serialize=lambda d: d, deserialize=lambda d: d)
    chain = store.verify_chain(verifier=_fake_verifier)
    # verify_facts' verifier is per-observer: (observer, signature, digest).
    facts = store.verify_facts(
        verifier=lambda _obs, sig, digest: _fake_verifier(sig, digest))
    store.close()
    return chain, facts


@pytest.fixture
def full_store(tmp_path):
    return _make_store(tmp_path / "full.db")


# ---------------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "eras",
    [
        {"prechain": True, "chained": True, "signed": True},
        {"prechain": True, "chained": False, "signed": False},
        {"prechain": False, "chained": True, "signed": False},
        {"prechain": False, "chained": False, "signed": True},
        {"prechain": True, "chained": False, "signed": True},
    ],
    ids=["all-eras", "prechain-only", "chained-only", "signed-only",
         "prechain-plus-signed"],
)
def test_round_trip_is_hash_identical(tmp_path, eras):
    from engine import tick_row_hash

    src = _make_store(tmp_path / "src.db", **eras)
    log = tmp_path / "src.jsonl"
    dst = tmp_path / "rebuilt.db"

    exported = export_jsonl(src, log)
    rebuilt = rebuild_jsonl(log, dst)

    src_facts, src_ticks = _fact_rows(src), _tick_rows(src)
    dst_facts, dst_ticks = _fact_rows(dst), _tick_rows(dst)

    # counts
    assert (exported.facts, exported.ticks) == (len(src_facts), len(src_ticks))
    assert (rebuilt.facts, rebuilt.ticks) == (len(src_facts), len(src_ticks))
    assert exported.lines == len(src_facts) + len(src_ticks)

    # byte-identical rows, in the same append order
    assert dst_facts == src_facts
    assert dst_ticks == src_ticks

    # byte-identical row hashes, row for row
    assert ([tick_row_hash(r) for r in dst_ticks]
            == [tick_row_hash(r) for r in src_ticks])

    # chain head via the tick_row_hash walk
    assert _chain_head(dst) == _chain_head(src)

    # verify passes on both
    src_chain, src_factrep = _verify(src)
    dst_chain, dst_factrep = _verify(dst)
    assert src_chain["ok"] and dst_chain["ok"]
    assert src_factrep["ok"] and dst_factrep["ok"]
    assert dst_chain["ticks"] == src_chain["ticks"]


def test_export_places_ticks_after_their_window(full_store, tmp_path):
    """Each tick line follows the fact line named by its fact_cursor."""
    from engine.jsonl_codec import deserialize_row

    log = tmp_path / "out.jsonl"
    export_jsonl(full_store, log)
    records = [deserialize_row(ln) for ln in log.read_text().splitlines()]

    seen: list[str] = []
    for t, row in records:
        if t == "fact":
            seen.append(row[0])
            continue
        cursor = row[8]
        if cursor:
            assert cursor in seen, "tick precedes the fact at its cursor"
            # nothing after the cursor fact has been emitted yet
            assert seen[-1] == cursor


def test_export_is_read_only(full_store, tmp_path):
    before = full_store.read_bytes()
    export_jsonl(full_store, tmp_path / "ro.jsonl")
    assert full_store.read_bytes() == before


def test_export_refuses_existing_target(full_store, tmp_path):
    log = tmp_path / "exists.jsonl"
    log.write_text("")
    with pytest.raises(FileExistsError):
        export_jsonl(full_store, log)


def test_rebuild_refuses_existing_target(full_store, tmp_path):
    log = tmp_path / "a.jsonl"
    export_jsonl(full_store, log)
    dst = tmp_path / "a.db"
    dst.write_bytes(b"")
    with pytest.raises(FileExistsError):
        rebuild_jsonl(log, dst)


def test_export_missing_source(tmp_path):
    with pytest.raises(FileNotFoundError):
        export_jsonl(tmp_path / "nope.db", tmp_path / "nope.jsonl")


def test_rebuild_missing_log(tmp_path):
    with pytest.raises(FileNotFoundError):
        rebuild_jsonl(tmp_path / "nope.jsonl", tmp_path / "nope.db")


def test_rebuild_skips_blank_lines(full_store, tmp_path):
    log = tmp_path / "b.jsonl"
    export_jsonl(full_store, log)
    log.write_text(log.read_text() + "\n\n")
    result = rebuild_jsonl(log, tmp_path / "b.db")
    assert result.facts == len(_fact_rows(full_store))


def test_rebuild_leaves_the_index_stamped(full_store, tmp_path):
    """The rebuilt index records what it consumed, not rebuild-on-next-open.

    A property of delegating to JsonlStore — pinned so the read-only-source
    reshape above cannot quietly cost it.
    """
    import sqlite3

    log = tmp_path / "stamped.jsonl"
    export_jsonl(full_store, log)
    dst = tmp_path / "stamped.db"
    rebuild_jsonl(log, dst)

    conn = sqlite3.connect(str(dst))
    try:
        marks = dict(conn.execute("SELECT key, value FROM store_meta"))
    finally:
        conn.close()
    assert int(marks["jsonl_offset"]) == log.stat().st_size
    assert int(marks["jsonl_fact_count"]) == len(_fact_rows(full_store))
    assert int(marks["jsonl_tick_count"]) == len(_tick_rows(full_store))


def test_rebuild_reports_a_torn_tail_and_never_edits_the_source(full_store, tmp_path):
    """A migration source is evidence: report the tear, don't repair it.

    JsonlStore truncates a torn final line because the next append would
    concatenate onto junk — right for a live log it owns. A rebuild source is
    an input, and silently editing it destroys the very bytes someone would
    need to recover the lost record.
    """
    log = tmp_path / "torn.jsonl"
    export_jsonl(full_store, log)
    log.write_bytes(log.read_bytes() + b'{"t":"fact","id":"01TR')
    before = log.read_bytes()

    dst = tmp_path / "torn.db"
    with pytest.raises(ValueError, match="torn final line"):
        rebuild_jsonl(log, dst)

    assert log.read_bytes() == before
    assert not dst.exists()


def test_rebuild_rejects_an_undecodable_line_leaving_no_target(full_store, tmp_path):
    """A codec error mid-log must not leave a partial db behind.

    A partial target makes the obvious retry hit the never-overwrite guard,
    turning one failure into manual cleanup.
    """
    from engine.jsonl_codec import JsonlCodecError

    log = tmp_path / "bad.jsonl"
    export_jsonl(full_store, log)
    rows = log.read_text(encoding="utf-8").splitlines()
    rows.insert(1, '{"t":"fact"}')  # decodes as JSON, not as a row
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")

    dst = tmp_path / "bad.db"
    with pytest.raises(JsonlCodecError):
        rebuild_jsonl(log, dst)
    assert not dst.exists()

    # And the retry after fixing the log is an ordinary rebuild, not a
    # FileExistsError from the failed attempt's residue.
    del rows[1]
    log.write_text("\n".join(rows) + "\n", encoding="utf-8")
    assert rebuild_jsonl(log, dst).facts == len(_fact_rows(full_store))


def test_rebuild_removes_the_target_when_construction_fails(full_store, tmp_path, monkeypatch):
    """Any failure past validation still leaves no partial target."""
    import engine.jsonl_store as js

    log = tmp_path / "boom.jsonl"
    export_jsonl(full_store, log)
    dst = tmp_path / "boom.db"

    real_init = js.JsonlStore.__init__

    def exploding_init(self, **kwargs):
        real_init(self, **kwargs)
        raise RuntimeError("simulated failure mid-rebuild")

    monkeypatch.setattr(js.JsonlStore, "__init__", exploding_init)
    with pytest.raises(RuntimeError):
        rebuild_jsonl(log, dst)
    assert not dst.exists()


def test_rebuild_removes_the_target_when_the_receipt_read_fails(
    full_store, tmp_path, monkeypatch
):
    """A failure AFTER construction (the count read) also leaves no target.

    A fully-built target with no returned RebuildResult would turn the
    natural retry into a FileExistsError (sol r3 finding 2).
    """
    import store.jsonl as sj

    log = tmp_path / "receipt.jsonl"
    export_jsonl(full_store, log)
    dst = tmp_path / "receipt.db"

    def exploding_open(*args, **kwargs):
        raise OSError("simulated failure reading the rebuilt store")

    monkeypatch.setattr(sj, "_open", exploding_open)
    with pytest.raises(OSError):
        rebuild_jsonl(log, dst)
    assert not dst.exists()

    monkeypatch.undo()
    result = rebuild_jsonl(log, dst)  # the natural retry succeeds
    assert result.facts > 0 and dst.exists()


def test_round_trip_of_empty_store(tmp_path):
    from engine import SqliteStore

    src = tmp_path / "empty.db"
    SqliteStore(path=src, serialize=lambda d: d, deserialize=lambda d: d).close()
    log = tmp_path / "empty.jsonl"
    assert export_jsonl(src, log).lines == 0
    assert rebuild_jsonl(log, tmp_path / "empty2.db").facts == 0


# ---------------------------------------------------------------------------
# Ordering rule, as a pure function
# ---------------------------------------------------------------------------

def _f(rowid, fid):
    return (rowid, (fid, "k", 1.0, "o", "", "{}", None))


def _t(rowid, tid, cursor):
    return (rowid, (tid, "n", 1.0, None, "o", "{}", None, "", cursor, None, None))


def test_order_tick_lands_after_its_cursor_fact():
    order = _receipt_order([_f(1, "A"), _f(2, "B"), _f(3, "C")],
                           [(1, _t(1, "T", "B")[1])])
    assert [r[0] for _, r in order] == ["A", "B", "T", "C"]


def test_order_empty_cursor_sorts_before_all_facts():
    order = _receipt_order([_f(1, "A")], [(1, _t(1, "T", "")[1])])
    assert [r[0] for _, r in order] == ["T", "A"]


def test_order_ties_break_on_tick_append_order():
    ticks = [(1, _t(1, "T1", "A")[1]), (2, _t(2, "T2", "A")[1])]
    order = _receipt_order([_f(1, "A")], ticks)
    assert [r[0] for _, r in order] == ["A", "T1", "T2"]


def test_order_unresolvable_cursor_inherits_previous_anchor():
    """A pre-chain (NULL cursor) tick, and one naming an absent fact, hold
    the position of the nearest preceding resolvable cursor."""
    ticks = [
        (1, _t(1, "T0", None)[1]),          # pre-chain: anchor 0
        (2, _t(2, "T1", "A")[1]),           # resolves to rowid 1
        (3, _t(3, "T2", "GONE")[1]),        # absent fact: inherits anchor 1
    ]
    order = _receipt_order([_f(1, "A"), _f(2, "B")], ticks)
    assert [r[0] for _, r in order] == ["T0", "A", "T1", "T2", "B"]
