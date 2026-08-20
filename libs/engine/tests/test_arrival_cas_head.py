"""The CAS token names an ARRIVAL coordinate — cut C §Q3.

``decision:design/arrival-sliceC-ordering``. The declaration head an edit
ceremony compares ``expected_head`` against is ``(record_ordinal, id)``: the
ordinal of the log record whose expansion carries the row, so the rows of one
batch record share it. Three things have to be pinned, and only together do
they say something the old rowid token did not:

1. The axis is arrival, not ``(ts, id)`` — a backdated declaration that
   ARRIVES last is the head even though its timestamp is the oldest.
2. The axis is arrival, not rowid — inside one batch record the ordinal ties
   and the id breaks it, which can name a row the rowid axis would not.
3. The token agrees with a from-scratch walk of the log, which is the
   authority. The walk here expands record bodies by hand rather than through
   ``rows_of_record``, so it is an independent second opinion about what a
   record carries and not a re-run of the implementation.

The legacy families keep their own rowid token and their own pin
(``test_absorb_edit.py``); nothing here touches them.
"""

from __future__ import annotations

import json
import sqlite3
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
from engine.arrival_store import ArrivalStore
from engine.jsonl_codec import object_of_batch, object_of_fact_row
from engine.sqlite_store import StaleDeclarationHead
from tests.conftest import Custodian

# Two loops, so an edit ceremony can carry two change rows and land as one
# multi-row batch record — the shape case 2 needs.
SRC = (
    'name "x"\nstore "./s.arrival"\nloops {\n'
    '  a { fold { n "inc" } }\n'
    '  b { fold { n "inc" } }\n}\n'
)


@pytest.fixture
def keys(tmp_path):
    return Custodian(tmp_path, "kyle")


@pytest.fixture
def signer(keys):
    return keys.signer


def open_store(tmp_path, signer) -> ArrivalStore:
    return ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )


def opened_lineage(tmp_path, keys, signer) -> tuple[ArrivalLog, str]:
    """A minted log and an opened lineage, with one edit ceremony behind it."""
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store = open_store(tmp_path, signer)
    try:
        lineage = store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(SRC))],
            observer="kyle",
            fact_signer=signer,
        )["lineage"]
        store.append(Fact.of("note", "kyle", message="noise"))
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="a",
                    payload={"order": 0},
                    annotation="modified",
                )
            ],
            observer="kyle",
            fact_signer=signer,
        )
    finally:
        store.close()
    return log, lineage


def decl_row(fact_id: str, lineage: str, subject: str, ts: float) -> tuple:
    """A self-lineage declaration fact row, as ``absorb_edit`` assembles one."""
    return (
        fact_id,
        DECL_KIND_DEFINED,
        ts,
        "kyle",
        "",
        json.dumps(
            {
                "lineage": lineage,
                "subject": subject,
                "change": "modified",
                "payload": {"order": 9},
            }
        ),
    )


def newest_by_ts_id(db: Path) -> str:
    """The declaration the ``(ts, id)`` axis would name — the foil."""
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT id FROM facts WHERE kind GLOB '_decl.*' "
            "ORDER BY ts DESC, id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()


def newest_by_rowid(db: Path) -> str:
    """The declaration the old rowid axis would name — the other foil."""
    conn = sqlite3.connect(str(db))
    try:
        return conn.execute(
            "SELECT id FROM facts WHERE kind GLOB '_decl.*' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()


def head_by_walking_the_log(log_path: Path, lineage: str) -> tuple[int, str] | None:
    """The head, from a from-scratch walk — the authority, independently read.

    Bodies are expanded by hand (``t``/``rows``) instead of through
    ``engine.arrival_projection.rows_of_record``, so agreeing with the store
    is agreement between two readings of the log rather than one reading run
    twice.
    """
    best: tuple[int, str] | None = None
    for record in ArrivalLog(log_path).walk():
        body = record["body"]
        if not isinstance(body, dict):
            continue
        if body.get("t") == "batch":
            rows = body["rows"]
        elif body.get("t") == "fact":
            rows = [body]
        else:
            continue  # tick, or a structural record that carries no rows
        for row in rows:
            if not str(row["kind"]).startswith("_decl."):
                continue
            if row["id"] != lineage:
                payload = json.loads(row["payload"])
                if payload.get("lineage") != lineage:
                    continue
            candidate = (record["ord"], row["id"])
            if best is None or candidate > best:
                best = candidate
    return best


# --- 1: arrival, not (ts, id) ----------------------------------------------


def test_cas_token_rides_the_arrival_axis(tmp_path, keys, signer):
    """A backdated declaration ARRIVES last, so it is the head.

    Successor to ``test_cas_token_rides_the_receipt_axis``: the same
    construction, one axis over. The backdating rides the LOG rather than a
    direct index INSERT — on this family an out-of-band row in the index is
    state the log does not account for, and the store refuses it. A second
    writer landing a record is the honest way to move the head.
    """
    log, lineage = opened_lineage(tmp_path, keys, signer)
    store = open_store(tmp_path, signer)
    try:
        head_before = store.declaration_head()
    finally:
        store.close()
    assert head_before is not None

    backdated = "01BACKDATED0000000000000A"
    log.append(
        "fact",
        object_of_fact_row(decl_row(backdated, lineage, "b", 1.0)),
        observer="kyle",
        at=1.0,
        signer=signer,
    )

    store = open_store(tmp_path, signer)  # the open tails the record
    try:
        head_now = store.declaration_head()
        assert head_now is not None
        # The arrival axis: an ordinal that advanced, naming the newest ARRIVAL.
        assert head_now[1] == backdated
        assert head_now[0] == head_before[0] + 1
        # The two axes genuinely disagree, so the assertion above discriminates.
        assert newest_by_ts_id(tmp_path / "s.db") != backdated

        # The pre-backdate token is stale and is refused...
        with pytest.raises(StaleDeclarationHead):
            store.absorb_edit(
                [
                    Change(
                        kind=DECL_KIND_DEFINED,
                        subject="c",
                        payload={"order": 2},
                        annotation="modified",
                    )
                ],
                observer="kyle",
                fact_signer=signer,
                expected_head=head_before,
            )
        # ...while the fresh arrival-axis token is accepted.
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="c",
                    payload={"order": 2},
                    annotation="modified",
                )
            ],
            observer="kyle",
            fact_signer=signer,
            expected_head=head_now,
        )
    finally:
        store.close()


def test_the_ordinal_is_the_records_not_a_row_counter(tmp_path, keys, signer):
    """A two-row ceremony advances the head by ONE ordinal, not two.

    The coordinate counts records, and a multi-change edit ceremony is one
    record. A row counter would advance by two here and the token would name
    a position the log has no record at.
    """
    log, lineage = opened_lineage(tmp_path, keys, signer)
    store = open_store(tmp_path, signer)
    try:
        before = store.declaration_head()
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="a",
                    payload={"order": 5},
                    annotation="modified",
                ),
                Change(
                    kind=DECL_KIND_RETIRED,
                    subject="b",
                    payload=None,
                    annotation="removed",
                ),
            ],
            observer="kyle",
            fact_signer=signer,
        )
        after = store.declaration_head()
    finally:
        store.close()
    assert before is not None and after is not None
    assert after[0] == before[0] + 1
    assert after[0] == ArrivalLog(log.path).head()["ord"]


# --- 2: arrival, not rowid --------------------------------------------------


def test_rows_of_one_batch_share_an_ordinal_and_tie_break_by_id(
    tmp_path, keys, signer
):
    """Inside one record the ordinal ties, so the ID decides — not the rowid.

    This is the one place the arrival axis is OBSERVABLY not the index's
    rowid, and therefore the case that makes cut C's re-point more than a
    rename. The batch's rows are ordered so the lexicographically larger id
    lands at the LOWER rowid: the rowid axis names the last row inserted, the
    arrival axis names the larger id. They name different rows.
    """
    log, lineage = opened_lineage(tmp_path, keys, signer)
    high, low = "01ZZZZZZZZZZZZZZZZZZZZZZZZ", "01AAAAAAAAAAAAAAAAAAAAAAAA"
    log.append(
        "batch",
        # Larger id FIRST — so it is the lower rowid once the index consumes.
        object_of_batch([
            decl_row(high, lineage, "a", 100.0),
            decl_row(low, lineage, "b", 100.0),
        ]),
        observer="kyle",
        at=100.0,
        signer=signer,
    )

    store = open_store(tmp_path, signer)
    try:
        head = store.declaration_head()
    finally:
        store.close()
    assert head is not None
    assert head[1] == high
    # The rowid axis genuinely names the other row — the axes disagree here.
    assert newest_by_rowid(tmp_path / "s.db") == low
    assert head[1] != newest_by_rowid(tmp_path / "s.db")
    # And both rows really are in the one record, sharing its ordinal.
    assert head[0] == ArrivalLog(log.path).head()["ord"]


# --- 3: the log is the authority -------------------------------------------


def test_the_token_agrees_with_a_from_scratch_walk_of_the_log(
    tmp_path, keys, signer
):
    """Every head the store answers matches an independent walk of the log.

    Checked after each step, not only at the end: a token that agrees once
    at the tail could still be wrong everywhere behind it. The store's
    answer is the log's answer or it is nothing.
    """
    log, lineage = opened_lineage(tmp_path, keys, signer)
    db = tmp_path / "s.db"

    def agree(store: ArrivalStore) -> tuple[int, str] | None:
        head = store.declaration_head()
        assert head == head_by_walking_the_log(log.path, lineage), (
            f"store says {head}, the log says "
            f"{head_by_walking_the_log(log.path, lineage)}"
        )
        return head

    store = open_store(tmp_path, signer)
    try:
        agree(store)
        # A plain fact moves the log's head without moving the DECLARATION
        # head — the walk and the store must agree about that too.
        store.append(Fact.of("note", "kyle", message="between"))
        assert agree(store) == store.declaration_head()
        # A one-row ceremony (a fact record).
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="a",
                    payload={"order": 1},
                    annotation="modified",
                )
            ],
            observer="kyle",
            fact_signer=signer,
        )
        agree(store)
        # A two-row ceremony (a batch record).
        store.absorb_edit(
            [
                Change(
                    kind=DECL_KIND_DEFINED,
                    subject="a",
                    payload={"order": 2},
                    annotation="modified",
                ),
                Change(
                    kind=DECL_KIND_RETIRED,
                    subject="b",
                    payload=None,
                    annotation="removed",
                ),
            ],
            observer="kyle",
            fact_signer=signer,
        )
        agree(store)
    finally:
        store.close()

    # And a record from another writer, adopted on the next open.
    log.append(
        "fact",
        object_of_fact_row(
            decl_row("01OTHERWRITER00000000000A", lineage, "c", 5.0)
        ),
        observer="kyle",
        at=5.0,
        signer=signer,
    )
    store = open_store(tmp_path, signer)
    try:
        assert agree(store) == (ArrivalLog(log.path).head()["ord"],
                                "01OTHERWRITER00000000000A")
    finally:
        store.close()
    assert db.exists()


def test_a_foreign_lineage_declaration_is_not_the_head(tmp_path, keys, signer):
    """The predicate is unchanged: a foreign ``_decl.*`` row never wins.

    Only the coordinate axis moved in cut C. A declaration stamped with
    someone else's lineage arrives at the highest ordinal and is still
    excluded, exactly as it was under the rowid token.
    """
    log, lineage = opened_lineage(tmp_path, keys, signer)
    store = open_store(tmp_path, signer)
    try:
        head_before = store.declaration_head()
    finally:
        store.close()

    log.append(
        "fact",
        object_of_fact_row(
            decl_row("01FOREIGN000000000000000A", "some-other-lineage", "x", 500.0)
        ),
        observer="kyle",
        at=500.0,
        signer=signer,
    )

    store = open_store(tmp_path, signer)
    try:
        assert store.declaration_head() == head_before
    finally:
        store.close()


def test_own_genesis_participates_as_the_head(tmp_path, keys, signer):
    """Before any edit, the head is the genesis row's own arrival coordinate.

    The other half of the unchanged predicate: the genesis row is matched by
    its id being the lineage, not by a payload stamp, so it participates.
    """
    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=signer, key=keys.public
    )
    store = open_store(tmp_path, signer)
    try:
        lineage = store.absorb_genesis(
            [d.as_json() for d in vertex_to_documents(parse_vertex(SRC))],
            observer="kyle",
            fact_signer=signer,
        )["lineage"]
        head = store.declaration_head()
    finally:
        store.close()
    assert head == (ArrivalLog(log.path).head()["ord"], lineage)
    assert head == head_by_walking_the_log(log.path, lineage)
