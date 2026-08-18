"""The derived ``.jsonl`` projection — cut B §Q2.

An arrival-canonical store's second projection: ``<name>.jsonl`` beside the
``<name>.arrival``, the shape ``probe`` already classifies as
``derived_log``. It carries row-class records only, its line order is a
byte-lexicographic sort that means nothing, it is materialized on demand and
never on the append path, and it carries no staleness marker — its currency
is a set question, answered by re-derive-and-diff.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from atoms import Fact
from lang import parse_vertex
from lang.document import DECL_GENESIS, vertex_to_documents

from engine.arrival import ArrivalLog
from engine.arrival_projection import (
    DerivedLogAgreement,
    audit_derived_log,
    canonical_line,
    derived_lines,
    derived_log_path_for,
    line_of_record,
    rederive_projections,
    write_derived_log,
)
from engine.arrival_store import ArrivalStore
from engine.jsonl_codec import deserialize_records
from engine.probe import probe_target
from engine.tick import Tick
from tests.conftest import ARRIVAL_VERTEX_SRC as BASE
from tests.conftest import Custodian


@pytest.fixture
def keys(tmp_path):
    return Custodian(tmp_path, "kyle")


@pytest.fixture
def signer(keys):
    return keys.signer


def build(tmp_path, keys, signer):
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))
        store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))],
            observer="kyle",
            fact_signer=signer,
        )
        store.append(Fact.of("note", "kyle", message="two"))
        store.append_tick(
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 1}, origin="t")
        )
    finally:
        store.close()
    return log, tmp_path / "s.jsonl"


def read(path):
    return path.read_text(encoding="utf-8").splitlines()


# --- shape and path ----------------------------------------------------------


def test_the_path_is_the_shape_probe_already_calls_a_projection(
    tmp_path, keys, signer
):
    """No new suffix: ``<name>.jsonl`` beside the ``.arrival``."""
    log, jsonl = build(tmp_path, keys, signer)
    assert derived_log_path_for(log.path) == jsonl

    write_derived_log(log.path)

    info = probe_target(jsonl)
    assert info.target_type == "derived_log"
    assert info.canonical_mode == "arrival"
    assert info.canonical_path == log.path
    assert info.writable is False


def test_structural_records_have_no_line(tmp_path, keys, signer):
    """NON-NEGOTIABLE. The genesis at ordinal 0 is not a codec object at
    all; its content lives in the arrival log, which is the store."""
    log, jsonl = build(tmp_path, keys, signer)
    records = list(ArrivalLog(log.path).walk())
    assert records[0]["k"] == "genesis"
    assert line_of_record(records[0]) is None

    write_derived_log(log.path)

    lines = read(jsonl)
    assert len(lines) == sum(1 for r in records if r["k"] != "genesis")
    assert all(json.loads(line)["t"] in ("fact", "tick", "batch") for line in lines)


def test_a_line_is_the_record_body_and_nothing_else(tmp_path, keys, signer):
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    bodies = [
        r["body"] for r in ArrivalLog(log.path).walk() if r["k"] != "genesis"
    ]
    assert bodies  # not vacuous
    # Every line decodes to exactly one record body, and to nothing else.
    assert {json.dumps(json.loads(line), sort_keys=True) for line in read(jsonl)} == {
        json.dumps(b, sort_keys=True) for b in bodies
    }


def test_payload_rides_as_verbatim_stored_text(tmp_path, keys, signer):
    """The identity round trip: the body IS the codec's object for the
    committed row, so re-encoding it changes nothing a signature covers."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        stored = {
            r[0]: (r[1], r[2])
            for r in conn.execute("SELECT id, payload, signature FROM facts")
        }
    finally:
        conn.close()

    seen = {}
    for line in read(jsonl):
        for t, row in deserialize_records(line):
            if t == "fact":
                seen[row[0]] = (row[5], row[6])
    assert seen == stored


def test_a_batch_record_emits_one_batch_line(tmp_path, keys, signer):
    from lang.document import DECL_KIND_DEFINED, DECL_KIND_RETIRED, Change

    src = (
        'name "x"\nstore "./s.arrival"\nloops {\n'
        '  a { fold { n "inc" } }\n  b { fold { n "inc" } }\n}\n'
    )
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )
    try:
        store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(src))],
            observer="kyle",
            fact_signer=signer,
        )
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
    finally:
        store.close()

    write_derived_log(log.path)
    lines = read(tmp_path / "s.jsonl")
    batch = [line for line in lines if json.loads(line)["t"] == "batch"]
    assert len(batch) == 1
    assert len(deserialize_records(batch[0])) == 2


# --- ordering ----------------------------------------------------------------


def test_line_order_is_a_byte_lexicographic_sort(tmp_path, keys, signer):
    """NON-NEGOTIABLE. Byte sort is the only order that is a pure function
    of the set — reproducible by ``sort(1)`` in any language, and what lets
    a merge driver produce the same bytes a fresh derivation produces."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    raw = jsonl.read_bytes().splitlines()
    assert raw == sorted(raw)
    assert len(raw) > 1  # not vacuous


def test_the_order_is_not_arrival_order(tmp_path, keys, signer):
    """The point of the ruling, made visible: the file's order is NOT the
    order records arrived, so no reader may attribute an ordering claim to
    it. The ordinal lives in the arrival log."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    arrival_order = [
        line_of_record(r)
        for r in ArrivalLog(log.path).walk()
        if line_of_record(r) is not None
    ]
    assert read(jsonl) != arrival_order
    assert sorted(read(jsonl)) == sorted(arrival_order)


def test_a_fresh_derivation_is_byte_identical_every_time(tmp_path, keys, signer):
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    first = jsonl.read_bytes()
    write_derived_log(log.path)
    assert jsonl.read_bytes() == first


def test_canonical_line_is_the_one_home_for_the_grammar(tmp_path, keys, signer):
    """A rewriter of this file imports the line rule rather than re-spelling
    it, so driver output and a fresh derivation cannot drift."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    for line in read(jsonl):
        assert canonical_line(line) == line
    # Key order in a hand-built line is normalized away.
    obj = json.loads(read(jsonl)[0])
    shuffled = json.dumps(dict(reversed(list(obj.items()))), separators=(",", ":"))
    assert canonical_line(shuffled) == read(jsonl)[0]


# --- derivation trigger ------------------------------------------------------


def test_the_append_path_never_materializes_it(tmp_path, keys, signer):
    """NON-NEGOTIABLE: on demand only. Regenerating a byte-sorted file per
    emit is O(n) per write — the O(n^2) ingest shape this arc paid for once."""
    log, jsonl = build(tmp_path, keys, signer)
    assert not jsonl.exists()

    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="after"))
    finally:
        store.close()
    assert not jsonl.exists()


def test_re_derivation_materializes_it_only_when_asked(tmp_path, keys, signer):
    log, jsonl = build(tmp_path, keys, signer)

    result = rederive_projections(log.path)
    assert result.projections == ("index",)
    assert not jsonl.exists()

    result = rederive_projections(log.path, derived_log=True)
    assert result.projections == ("index", "derived-log")
    assert jsonl.exists()
    assert read(jsonl) == derived_lines(ArrivalLog(log.path))


def test_it_is_derived_from_the_log_and_never_from_the_index(
    tmp_path, keys, signer
):
    """NON-NEGOTIABLE. A poisoned index must not launder itself into a
    second artifact, so the derivation must not read sqlite at all."""
    log, jsonl = build(tmp_path, keys, signer)
    expected = derived_lines(ArrivalLog(log.path))

    # Poison the index: an out-of-band row the log never carried.
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, origin, payload) "
            "VALUES ('01OUTOFBANDROWZZZZZZZZZZZZ', 'note', 9.0, 'x', '', '{}')"
        )
        conn.commit()
    finally:
        conn.close()

    write_derived_log(log.path)
    assert read(jsonl) == expected
    assert "01OUTOFBANDROWZZZZZZZZZZZZ" not in jsonl.read_text()

    # And the index is deleted entirely — derivation still succeeds.
    (tmp_path / "s.db").unlink()
    write_derived_log(log.path)
    assert read(jsonl) == expected


# --- the agreement audit -----------------------------------------------------


def test_a_fresh_derivation_audits_clean(tmp_path, keys, signer):
    log, _ = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    agreement = audit_derived_log(log.path)
    assert isinstance(agreement, DerivedLogAgreement)
    assert agreement.ok and agreement.missing == 0 and agreement.extra == 0


def test_a_deleted_line_reports_missing(tmp_path, keys, signer):
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    lines = read(jsonl)
    jsonl.write_text("".join(line + "\n" for line in lines[1:]), encoding="utf-8")

    agreement = audit_derived_log(log.path)
    assert not agreement.ok
    assert agreement.missing == 1 and agreement.extra == 0
    assert "absent" in agreement.detail


def test_an_added_line_reports_extra(tmp_path, keys, signer):
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    forged = json.dumps(
        {
            "t": "fact",
            "id": "01FORGEDLINEZZZZZZZZZZZZZZ",
            "kind": "note",
            "ts": 1.0,
            "observer": "x",
            "origin": "",
            "payload": "{}",
        },
        separators=(",", ":"),
    )
    with jsonl.open("a", encoding="utf-8") as fh:
        fh.write(forged + "\n")

    agreement = audit_derived_log(log.path)
    assert not agreement.ok
    assert agreement.missing == 0 and agreement.extra == 1


def test_a_missing_file_is_reported_as_every_record_missing(
    tmp_path, keys, signer
):
    log, jsonl = build(tmp_path, keys, signer)
    assert not jsonl.exists()

    agreement = audit_derived_log(log.path)
    assert not agreement.ok
    assert agreement.missing == len(derived_lines(ArrivalLog(log.path)))
    assert agreement.extra == 0
    assert "no derived log" in agreement.detail


def test_a_healthy_store_is_never_reported_as_missing_its_genesis(
    tmp_path, keys, signer
):
    """Contract note on `missing`: it counts ROW-CLASS records. Structural
    records are outside the projection."""
    log, _ = build(tmp_path, keys, signer)
    write_derived_log(log.path)

    records = list(ArrivalLog(log.path).walk())
    # Both genesis senses are present: the STRUCTURAL arrival genesis at
    # ordinal 0 (no line) and the `_decl.genesis` fact ROW (one line).
    assert records[0]["k"] == "genesis"
    assert any(
        r["k"] == "fact" and r["body"].get("kind") == DECL_GENESIS
        for r in records
    )
    assert audit_derived_log(log.path).ok


def test_a_torn_tail_is_short_rather_than_a_content_disagreement(
    tmp_path, keys, signer
):
    """A crashed derivation left a half-written final line. It was never
    terminated, so it never claimed to be a record: the honest reading is
    that the file is SHORT, not that it holds a line the log never carried."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    whole = jsonl.read_bytes()
    jsonl.write_bytes(whole[: -len(whole.splitlines()[-1]) // 2])

    agreement = audit_derived_log(log.path)
    assert not agreement.ok
    assert agreement.missing == 1
    assert agreement.extra == 0


def test_there_is_no_staleness_marker(tmp_path, keys, signer):
    """The offset/count triple does not get a third sibling — the derived
    log's currency is a set question, and a stamp inside the mutable
    artifact being judged is not an answer to it."""
    import sqlite3

    log, _ = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    conn = sqlite3.connect(str(tmp_path / "s.db"))
    try:
        keys_present = {
            r[0] for r in conn.execute("SELECT key FROM store_meta")
        }
    finally:
        conn.close()
    assert not any("jsonl" in k or "derived" in k for k in keys_present)


def test_a_lagging_derived_log_is_not_an_error(tmp_path, keys, signer):
    """Nothing in libs/ reads it — reads execute through the index in every
    mode — so a store whose derived log is behind opens and reads normally."""
    log, jsonl = build(tmp_path, keys, signer)
    write_derived_log(log.path)
    stale = jsonl.read_bytes()

    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="later"))
        assert store.total > 0
    finally:
        store.close()

    assert jsonl.read_bytes() == stale
    # Reopening is fine too — the lag is invisible to every read path.
    ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    ).close()
    assert audit_derived_log(log.path).missing == 1
