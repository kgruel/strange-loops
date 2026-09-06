"""The neutral, bounded Arrival query surface used by SDK consumers."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from atoms import Fact as AtomFact
from lang.document import DECL_GENESIS, DECL_VERTEX_DEFINED

from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_batch, body_of_fact_row
from engine.arrival_consumer import open_read
from engine.arrival_contract import (
    Continuation,
    DeclarationAnchor,
    Fact,
    FactCursor,
    FactRequest,
    Head,
    HeadMismatch,
    InvalidContinuation,
    NotAuthority,
    Profile,
    ProjectionAbsent,
    ProjectionBehind,
    ProjectionRequirement,
    StoreDescriptor,
    SummaryRequest,
    TickRequest,
    Watermark,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_attestation import Outcome
from engine.arrival_head_seam import Compared
from engine.arrival_registry import BackendRegistry
from engine.arrival_store import ArrivalStore
from engine.declaration import UnadoptedLineage, resolve_declaration_documents_from_snapshot
from engine.residence import index_path_for
from engine.tick import Tick as StoredTick


def _build(tmp_path: Path, keys, signer, *, facts: int = 3) -> tuple[ArrivalLog, Path]:
    log = ArrivalLog.mint(
        tmp_path / "sample.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )
    database = index_path_for(log.path)
    store = ArrivalStore(
        path=database,
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        for number in range(facts):
            store.append(AtomFact.of("note", "kyle", number=number))
        store.append_tick(
            StoredTick(
                name="checkpoint",
                ts=datetime.now(UTC),
                payload={"kind": "test"},
                origin="test",
            )
        )
    finally:
        store.close()
    return log, database


def _head(log: ArrivalLog):
    return FileLedger(log).head()


def test_file_snapshot_bounds_facts_ticks_and_summary_to_its_captured_head(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer)
    query = FileQuery(database)
    snapshot = query.open_snapshot(
        captured_head=_head(log), requirement=ProjectionRequirement.CURRENT
    )
    try:
        facts = snapshot.facts(FactRequest(limit=None, order="oldest"))
        ticks = snapshot.ticks(TickRequest())
        summary = snapshot.summary(SummaryRequest())
        assert [fact.payload["number"] for fact in facts.items] == [0, 1, 2]
        assert facts.cursor is None
        assert len(ticks) == 1
        assert summary.fact_total == 3
        assert summary.tick_total == 1
        assert summary.signed_count + summary.unsigned_count == 3
        assert summary.fact_kinds["note"]["count"] == 3
        assert summary.tick_names["checkpoint"]["count"] == 1
        assert snapshot.view_generation is not None
        fact = facts.items[0]
        tick = ticks[0]
        assert fact.payload_text is not None
        assert json.loads(fact.payload_text) == fact.payload
        assert fact.signature is not None
        assert tick.payload_text is not None
        assert json.loads(tick.payload_text) == tick.payload
        assert tick.prev_hash is None
        assert tick.window_start == ""
        assert tick.fact_cursor == facts.items[-1].id
        assert tick.window_hash is not None
    finally:
        snapshot.close()
        query.close()


def test_file_snapshot_current_refuses_a_lagging_projection_but_allow_behind_binds_it(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer, facts=1)
    # Advance custody directly.  The existing SQLite projection remains a
    # valid but lagging prefix and read opening must not repair it.
    log.append("note", {"message": "not projected"}, observer="kyle")
    query = FileQuery(database)
    try:
        with pytest.raises(ProjectionBehind):
            query.open_snapshot(
                captured_head=_head(log), requirement=ProjectionRequirement.CURRENT
            )
        snapshot = query.open_snapshot(
            captured_head=_head(log), requirement=ProjectionRequirement.ALLOW_BEHIND
        )
        try:
            assert snapshot.represented is not None
            assert snapshot.represented.ordinal < _head(log).ordinal
            assert [fact.payload["number"] for fact in snapshot.facts(
                FactRequest(limit=None, order="oldest")
            ).items] == [0]
        finally:
            snapshot.close()
    finally:
        query.close()


def test_file_snapshot_missing_projection_is_explicit_and_never_materialized(
    tmp_path, keys, signer
):
    log = ArrivalLog.mint(
        tmp_path / "missing.arrival",
        observer="kyle",
        signer=signer,
        key=keys.public,
    )
    query = FileQuery(index_path_for(log.path))
    try:
        with pytest.raises(ProjectionAbsent):
            query.open_snapshot(
                captured_head=_head(log), requirement=ProjectionRequirement.CURRENT
            )
        snapshot = query.open_snapshot(
            captured_head=_head(log), requirement=ProjectionRequirement.ALLOW_BEHIND
        )
        try:
            assert snapshot.represented is None
            assert snapshot.summary(SummaryRequest()).fact_total == 0
        finally:
            snapshot.close()
        assert not index_path_for(log.path).exists()
    finally:
        query.close()



def _project(log: ArrivalLog, database: Path, signer) -> None:
    """Consume newly appended custody rows into the existing test projection."""
    store = ArrivalStore(
        path=database,
        log_path=log.path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    store.close()


def _page(query: FileQuery, head, request: FactRequest, continuation: Continuation | None = None):
    snapshot = query.open_snapshot(
        captured_head=head,
        requirement=ProjectionRequirement.CURRENT,
        continuation=continuation,
    )
    try:
        page = snapshot.facts(request)
        return page, snapshot.view_generation
    finally:
        snapshot.close()


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        ("oldest", ["b0", "b1", "b2", "bob"]),
        ("newest", ["bob", "b2", "b1", "b0"]),
    ],
)
@pytest.mark.parametrize("limit", [1, 2, 50])
def test_file_snapshot_fact_pages_are_hard_row_bounds_inside_a_batch(
    tmp_path, keys, signer, order, expected, limit
):
    """Receipt coordinates, rather than Arrival record boundaries, page facts."""
    log, database = _build(tmp_path, keys, signer, facts=0)
    log.append(
        "batch",
        body_of_batch(
            [
                ("b0", "note", 10.0, "kyle", "", json.dumps({"n": 0})),
                ("b1", "note.child", 11.0, "kyle", "", json.dumps({"n": 1})),
                ("b2", "other", 12.0, "kyle", "", json.dumps({"n": 2})),
            ]
        ),
        observer="kyle",
    )
    log.append(
        "fact",
        body_of_fact_row(("bob", "note", 13.0, "bob", "", json.dumps({"n": 3}))),
        observer="bob",
    )
    _project(log, database, signer)
    head = _head(log)
    request = FactRequest(limit=limit, order=order)
    query = FileQuery(database)
    try:
        page, generation = _page(query, head, request)
        seen = []
        while True:
            assert len(page.items) <= limit
            seen.extend(fact.id for fact in page.items)
            if page.cursor is None:
                assert page.truncated is False
                break
            assert page.truncated is True
            token = Continuation(head, head, request, page.cursor, generation)
            page, resumed_generation = _page(query, head, request, token)
            assert resumed_generation == generation
        assert seen == expected
        assert len(seen) == len(set(seen))
    finally:
        query.close()


def test_file_snapshot_fact_page_filters_and_empty_end_keep_receipt_cursor(tmp_path, keys, signer):
    log, database = _build(tmp_path, keys, signer, facts=0)
    log.append(
        "batch",
        body_of_batch(
            [
                ("b0", "note", 10.0, "kyle", "", json.dumps({"n": 0})),
                ("b1", "note.child", 11.0, "kyle", "", json.dumps({"n": 1})),
                ("b2", "other", 12.0, "kyle", "", json.dumps({"n": 2})),
            ]
        ),
        observer="kyle",
    )
    log.append(
        "fact",
        body_of_fact_row(("bob", "note", 13.0, "bob", "", json.dumps({"n": 3}))),
        observer="bob",
    )
    _project(log, database, signer)
    head = _head(log)
    query = FileQuery(database)
    try:
        kind_request = FactRequest(limit=1, kind="note", order="oldest")
        kind_page, generation = _page(query, head, kind_request)
        assert [fact.id for fact in kind_page.items] == ["b0"]
        assert kind_page.cursor is not None
        kind_token = Continuation(head, head, kind_request, kind_page.cursor, generation)
        kind_next, next_generation = _page(query, head, kind_request, kind_token)
        assert [fact.id for fact in kind_next.items] == ["b1"]
        assert kind_next.truncated is True and kind_next.cursor is not None
        kind_last, _ = _page(
            query,
            head,
            kind_request,
            Continuation(head, head, kind_request, kind_next.cursor, next_generation),
        )
        assert [fact.id for fact in kind_last.items] == ["bob"]
        assert kind_last.truncated is False and kind_last.cursor is None

        observer_page, _ = _page(
            query, head, FactRequest(limit=50, observer="kyle", order="oldest")
        )
        assert [fact.id for fact in observer_page.items] == ["b0", "b1", "b2"]
        empty, _ = _page(
            query, head, FactRequest(limit=1, kind="absent", order="oldest")
        )
        assert empty.items == () and empty.cursor is None and empty.truncated is False
    finally:
        query.close()


def test_file_snapshot_fact_id_prefix_is_literal_and_exact_match_wins(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer, facts=0)
    rows = [
        ("exact", "note", 10.0, "kyle", "", json.dumps({"n": 0})),
        ("exact-long", "note", 11.0, "kyle", "", json.dumps({"n": 1})),
        ("unicode-é", "note", 12.0, "kyle", "", json.dumps({"n": 2})),
        ("tilde-~", "note", 13.0, "kyle", "", json.dumps({"n": 3})),
        ("percent-%", "note", 14.0, "kyle", "", json.dumps({"n": 4})),
        ("underscore-_", "note", 15.0, "kyle", "", json.dumps({"n": 5})),
        ("bracket-[", "note", 16.0, "kyle", "", json.dumps({"n": 6})),
        ("nul-\0tail", "note", 17.0, "kyle", "", json.dumps({"n": 7})),
        ("amb-é", "note", 18.0, "kyle", "", json.dumps({"n": 8})),
        ("amb-~", "note", 19.0, "kyle", "", json.dumps({"n": 9})),
    ]
    log.append("batch", body_of_batch(rows), observer="kyle")
    _project(log, database, signer)
    head = _head(log)
    query = FileQuery(database)
    try:
        exact, _ = _page(query, head, FactRequest(limit=None, fact_id="exact"))
        assert [fact.id for fact in exact.items] == ["exact"]

        for prefix, expected in (
            ("unicode-", "unicode-é"),
            ("tilde-", "tilde-~"),
            ("percent-", "percent-%"),
            ("underscore-", "underscore-_"),
            ("bracket-", "bracket-["),
            ("nul-", "nul-\0tail"),
        ):
            page, _ = _page(
                query, head, FactRequest(limit=None, fact_id=prefix)
            )
            assert [fact.id for fact in page.items] == [expected]

        request = FactRequest(limit=1, fact_id="amb-", order="oldest")
        first, generation = _page(query, head, request)
        assert [fact.id for fact in first.items] == ["amb-é"]
        assert first.cursor is not None and first.truncated is True
        second, _ = _page(
            query,
            head,
            request,
            Continuation(head, head, request, first.cursor, generation),
        )
        assert [fact.id for fact in second.items] == ["amb-~"]
        assert second.cursor is None and second.truncated is False
    finally:
        query.close()


def test_file_snapshot_continuation_stays_at_captured_prefix_inside_a_batch(tmp_path, keys, signer):
    log, database = _build(tmp_path, keys, signer, facts=0)
    log.append(
        "batch",
        body_of_batch(
            [
                ("b0", "note", 10.0, "kyle", "", json.dumps({"n": 0})),
                ("b1", "note", 11.0, "kyle", "", json.dumps({"n": 1})),
                ("b2", "note", 12.0, "kyle", "", json.dumps({"n": 2})),
            ]
        ),
        observer="kyle",
    )
    _project(log, database, signer)
    captured = _head(log)
    request = FactRequest(limit=1, order="oldest")
    query = FileQuery(database)
    try:
        first, generation = _page(query, captured, request)
        assert [fact.id for fact in first.items] == ["b0"]
        assert first.cursor is not None

        log.append(
            "batch",
            body_of_batch(
                [
                    ("later-0", "note", 20.0, "kyle", "", json.dumps({"n": 20})),
                    ("later-1", "note", 21.0, "kyle", "", json.dumps({"n": 21})),
                ]
            ),
            observer="kyle",
        )
        _project(log, database, signer)
        assert _head(log).ordinal > captured.ordinal

        token = Continuation(captured, captured, request, first.cursor, generation)
        second, second_generation = _page(query, captured, request, token)
        assert second_generation == generation
        assert [fact.id for fact in second.items] == ["b1"]
        assert second.cursor is not None
        token = Continuation(captured, captured, request, second.cursor, second_generation)
        third, _ = _page(query, captured, request, token)
        assert [fact.id for fact in third.items] == ["b2"]
        assert third.truncated is False and third.cursor is None
    finally:
        query.close()

def test_consumer_open_returns_only_snapshot_and_resumes_same_generation(
    tmp_path, keys, signer
):
    log, _database = _build(tmp_path, keys, signer, facts=3)
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    with open_read(registry, descriptor) as opened:
        request = FactRequest(limit=1, order="oldest")
        first = opened.snapshot.facts(request)
        assert first.truncated
        assert not hasattr(opened, "ledger")
        token = opened.continuation(request, first)
        assert token is not None
        assert token.view_generation == opened.basis.view_generation

    with open_read(registry, descriptor, continuation=token) as resumed:
        second = resumed.snapshot.facts(request)
        next_token = resumed.continuation(request, second)
        assert next_token is not None
    with open_read(registry, descriptor, continuation=next_token) as resumed:
        third = resumed.snapshot.facts(request)
        assert [
            fact.payload["number"] for fact in first.items + second.items + third.items
        ] == [0, 1, 2]


def test_consumer_refuses_resume_without_a_derived_view_generation():
    from engine.arrival_consumer import OpenedRead
    from engine.arrival_contract import FactCursor, FactPage, Head, ReadBasis

    head = Head("lineage", 1, "hash")
    opened = OpenedRead(
        snapshot=object(),
        basis=ReadBasis("lineage", head, head, None),
        report=object(),
        _query=object(),
        _ledger=object(),
    )
    with pytest.raises(InvalidContinuation, match="derived view"):
        opened.continuation(
            FactRequest(),
            FactPage(( ), FactCursor(1, 0, "fact"), True, "newest"),
        )


def test_consumer_resumes_continuation_after_ledger_advance(tmp_path, keys, signer):
    log, _database = _build(tmp_path, keys, signer, facts=2)
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    request = FactRequest(limit=1, order="oldest")
    with open_read(registry, descriptor) as opened:
        token = opened.continuation(request, opened.snapshot.facts(request))
        assert token is not None
    log.append("note", {"message": "after-page-one"}, observer="kyle")
    with open_read(registry, descriptor, continuation=token) as resumed:
        assert [fact.payload["number"] for fact in resumed.snapshot.facts(request).items] == [1]


@pytest.mark.parametrize(
    "case",
    (
        "foreign",
        "missing",
        "substitution",
        "wrong-coordinate",
        "wrong-lineage-coordinate",
    ),
)
def test_resumed_consumer_completes_new_snapshot_watermark_custody(
    monkeypatch, case
):
    captured = Head("lineage", 3, "captured")
    projected = Head("lineage", 2, "projected")
    represented = Watermark(
        "foreign" if case == "foreign" else captured.lineage,
        (
            captured.ordinal + 1
            if case in {"missing", "wrong-coordinate", "wrong-lineage-coordinate"}
            else captured.ordinal
        ),
    )
    closed: list[str] = []
    snapshot = SimpleNamespace(
        represented=represented,
        declaration_anchor=DeclarationAnchor(None, None),
        view_generation="view",
        close=lambda: closed.append("snapshot"),
    )

    class MissingPrefix(Exception):
        pass

    missing = MissingPrefix("reported prefix is absent")

    class Ledger:
        def __init__(self):
            self.opened = SimpleNamespace(
                comparison=Compared(Outcome.UNCHANGED, captured, None)
            )
            self.lookups = 0

        def head_at(self, watermark):
            self.lookups += 1
            if self.lookups == 1:
                assert watermark == Watermark(captured.lineage, captured.ordinal)
                return captured
            if self.lookups == 2:
                assert watermark == Watermark(projected.lineage, projected.ordinal)
                return projected
            if case == "missing":
                raise missing
            if case == "substitution":
                return Head(captured.lineage, captured.ordinal, "replacement")
            if case == "wrong-coordinate":
                return Head(captured.lineage, captured.ordinal, "wrong-coordinate")
            if case == "wrong-lineage-coordinate":
                return Head("other-lineage", represented.ordinal, "wrong-lineage")
            raise AssertionError("foreign watermark reached custody lookup")

        def close(self):
            closed.append("ledger")

    class Query:
        def open_snapshot(self, **kwargs):
            return snapshot

        def close(self):
            closed.append("query")

    class Registry:
        def open(self, descriptor):
            return Ledger(), Query()

    monkeypatch.setattr("engine.arrival_consumer.AttestedLedger", Ledger)
    request = FactRequest(limit=1, order="oldest")
    continuation = Continuation(
        captured,
        projected,
        request,
        FactCursor(1, 0, "first"),
        "view",
    )
    expected = {
        "foreign": NotAuthority,
        "missing": MissingPrefix,
        "substitution": HeadMismatch,
        "wrong-coordinate": HeadMismatch,
        "wrong-lineage-coordinate": HeadMismatch,
    }[case]

    with pytest.raises(expected) as raised:
        open_read(
            Registry(),
            StoreDescriptor("file", "unused", role=Profile.AUTHORITY),
            requirement=ProjectionRequirement.ALLOW_BEHIND,
            continuation=continuation,
        )

    if case == "missing":
        assert raised.value is missing
    assert closed == ["snapshot", "query", "ledger"]


def test_resumed_consumer_accepts_vouched_projection_advance_but_keeps_token_bounds(
    monkeypatch,
):
    captured = Head("lineage", 3, "captured")
    projected = Head("lineage", 2, "projected")
    advanced = Head("lineage", 4, "advanced")
    closed: list[str] = []
    snapshot = SimpleNamespace(
        represented=Watermark(advanced.lineage, advanced.ordinal),
        declaration_anchor=DeclarationAnchor(None, None),
        view_generation="view",
        close=lambda: closed.append("snapshot"),
    )

    class Ledger:
        def __init__(self):
            self.opened = SimpleNamespace(
                comparison=Compared(Outcome.UNCHANGED, advanced, None)
            )

        def head_at(self, watermark):
            return {
                Watermark(captured.lineage, captured.ordinal): captured,
                Watermark(projected.lineage, projected.ordinal): projected,
                Watermark(advanced.lineage, advanced.ordinal): advanced,
            }[watermark]

        def close(self):
            closed.append("ledger")

    class Query:
        def open_snapshot(self, **kwargs):
            assert kwargs["captured_head"] == captured
            return snapshot

        def close(self):
            closed.append("query")

    class Registry:
        def open(self, descriptor):
            return Ledger(), Query()

    monkeypatch.setattr("engine.arrival_consumer.AttestedLedger", Ledger)
    request = FactRequest(limit=1, order="oldest")
    token = Continuation(
        captured,
        projected,
        request,
        FactCursor(1, 0, "first"),
        "view",
    )

    with open_read(
        Registry(),
        StoreDescriptor("file", "unused", role=Profile.AUTHORITY),
        requirement=ProjectionRequirement.ALLOW_BEHIND,
        continuation=token,
    ) as resumed:
        assert resumed.basis.captured_head == token.captured_head
        assert resumed.basis.projected_through == token.projected_through
        assert resumed.basis.view_generation == token.view_generation

    assert closed == ["snapshot", "query", "ledger"]


def test_fresh_consumer_clamps_a_custody_proven_projection_advance(monkeypatch):
    captured = Head("lineage", 3, "captured")
    advanced = Head("lineage", 4, "advanced")
    snapshot = SimpleNamespace(
        represented=Watermark(advanced.lineage, advanced.ordinal),
        declaration_anchor=DeclarationAnchor(None, None),
        view_generation="view",
        close=lambda: None,
    )

    class Ledger:
        def __init__(self):
            self.opened = SimpleNamespace(
                comparison=Compared(Outcome.UNCHANGED, captured, None)
            )

        def head_at(self, watermark):
            assert watermark == snapshot.represented
            return advanced

        def close(self):
            return None

    class Registry:
        def open(self, descriptor):
            return Ledger(), SimpleNamespace(
                open_snapshot=lambda **kwargs: snapshot,
                close=lambda: None,
            )

    monkeypatch.setattr("engine.arrival_consumer.AttestedLedger", Ledger)
    descriptor = StoreDescriptor("file", "unused", role=Profile.AUTHORITY)
    with open_read(Registry(), descriptor) as opened:
        assert opened.basis.captured_head == captured
        assert opened.basis.projected_through == captured


@pytest.mark.parametrize(
    "case", ("foreign", "missing", "substitution", "wrong-coordinate")
)
def test_fresh_consumer_completes_projection_custody_before_return(
    monkeypatch, case
):
    captured = Head("lineage", 3, "captured")
    represented = Watermark(
        "foreign" if case == "foreign" else captured.lineage,
        captured.ordinal + 1 if case == "missing" else captured.ordinal,
    )
    replacement = Head(captured.lineage, captured.ordinal, "replacement")
    closed: list[str] = []
    snapshot = SimpleNamespace(
        represented=represented,
        declaration_anchor=DeclarationAnchor(None, None),
        view_generation="view",
        close=lambda: closed.append("snapshot"),
    )

    class MissingPrefix(Exception):
        pass

    class Ledger:
        def __init__(self):
            self.opened = SimpleNamespace(
                comparison=Compared(Outcome.UNCHANGED, captured, None)
            )

        def head_at(self, watermark):
            if case == "foreign":
                raise AssertionError("foreign watermark reached custody lookup")
            if case == "missing":
                raise MissingPrefix("prefix absent")
            if case == "wrong-coordinate":
                return Head(captured.lineage, captured.ordinal - 1, "wrong")
            return replacement

        def close(self):
            closed.append("ledger")

    class Query:
        def open_snapshot(self, **kwargs):
            return snapshot

        def close(self):
            closed.append("query")

    class Registry:
        def open(self, descriptor):
            return Ledger(), Query()

    monkeypatch.setattr("engine.arrival_consumer.AttestedLedger", Ledger)
    descriptor = StoreDescriptor("file", "unused", role=Profile.AUTHORITY)
    expected = {
        "foreign": NotAuthority,
        "missing": MissingPrefix,
        "substitution": HeadMismatch,
        "wrong-coordinate": HeadMismatch,
    }[case]
    with pytest.raises(expected):
        open_read(Registry(), descriptor)
    assert closed == ["snapshot", "query", "ledger"]


def test_consumer_refuses_continuation_when_projection_disappears(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer, facts=2)
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    request = FactRequest(limit=1, order="oldest")
    with open_read(registry, descriptor) as opened:
        token = opened.continuation(request, opened.snapshot.facts(request))
        assert token is not None
    database.unlink()
    with pytest.raises(InvalidContinuation, match="disappeared"):
        open_read(
            registry,
            descriptor,
            requirement=ProjectionRequirement.ALLOW_BEHIND,
            continuation=token,
        )


def test_consumer_refuses_continuation_after_same_prefix_projection_change(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer, facts=2)
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    request = FactRequest(limit=1, order="oldest")
    with open_read(registry, descriptor) as opened:
        page = opened.snapshot.facts(request)
        token = opened.continuation(request, page)
        assert token is not None
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "UPDATE facts SET payload = ? WHERE id = ?",
            (json.dumps({"number": "rewritten"}), page.items[0].id),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(InvalidContinuation, match="view changed"):
        open_read(registry, descriptor, continuation=token)


def test_consumer_refuses_declaration_marker_not_licensed_by_arrival_lineage(
    tmp_path, keys, signer
):
    log, database = _build(tmp_path, keys, signer, facts=1)
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "INSERT OR REPLACE INTO store_meta(key, value) VALUES ('own_lineage', ?)",
            ("foreign-declaration",),
        )
        connection.commit()
    finally:
        connection.close()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    with pytest.raises(NotAuthority, match="declaration identity"):
        open_read(BackendRegistry.with_builtin_backends(), descriptor)


def test_current_continuation_refuses_a_token_from_allow_behind(
    tmp_path, keys, signer
):
    log, _database = _build(tmp_path, keys, signer, facts=2)
    log.append("note", {"message": "lagging projection"}, observer="kyle")
    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(
        backend="file", location=str(log.path), role=Profile.AUTHORITY
    )
    request = FactRequest(limit=1, order="oldest")
    with open_read(
        registry, descriptor, requirement=ProjectionRequirement.ALLOW_BEHIND
    ) as opened:
        token = opened.continuation(request, opened.snapshot.facts(request))
        assert token is not None
    with pytest.raises(ProjectionBehind):
        open_read(registry, descriptor, continuation=token)


def test_snapshot_declaration_fold_uses_explicit_anchor_and_keeps_foreign_rows_inert():
    genesis = Fact(
        id="own",
        kind=DECL_GENESIS,
        ts=1.0,
        observer="kyle",
        origin="",
        payload={
            "protocol": 1,
            "documents": [
                {"kind": DECL_VERTEX_DEFINED, "subject": "vertex", "payload": {"v": 1}}
            ],
        },
        arrival_ordinal=1,
        arrival_seq=0,
    )
    foreign = Fact(
        id="foreign-edit",
        kind=DECL_VERTEX_DEFINED,
        ts=2.0,
        observer="kyle",
        origin="",
        payload={"lineage": "foreign", "subject": "vertex", "payload": {"v": 2}},
        arrival_ordinal=2,
        arrival_seq=0,
    )
    docs = resolve_declaration_documents_from_snapshot(
        DeclarationAnchor("own", genesis), [genesis, foreign]
    )
    assert docs == [
        {"kind": DECL_VERTEX_DEFINED, "subject": "vertex", "payload": {"v": 1}}
    ]
    with pytest.raises(UnadoptedLineage):
        resolve_declaration_documents_from_snapshot(
            DeclarationAnchor(None, None), [genesis]
        )
