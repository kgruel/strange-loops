"""Descriptor-first ordinary emission stays on attested Arrival paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog, content_commitment, verify_authorship
from engine.arrival_binding import file_binding
from engine.arrival_body import body_of_fact_row, body_of_tick_row
from engine.arrival_contract import (
    AtomicLimitExceeded,
    Commit,
    DurabilityProfile,
    DurabilityReceipt,
    Head,
    ProjectionAbsent,
    ProjectionBehind,
)
from engine.arrival_file_backend import FileLedger, FileQuery
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_registry import BackendRegistry
from engine.handle import WriteCredentials
from engine.residence import index_path_for
from engine.runtime_write import BatchWriteCommitUnknown, WriteCommitUnknown
from lang import genesis_payload, parse_vertex_file
from lang.vertex_mutation import remove_vertex_kind
from sign import ed25519

from sdk import (
    AdmissionFailed,
    ArrivalRefusal,
    CommittedOutcomeUnknown,
    CommittedProjectionFailed,
    CommittedUnwitnessed,
    InvalidEmissionRequest,
    TargetUnsupported,
    edit_declaration,
    emit_batch,
    emit_fact,
    export_target,
    init_vertex,
    inspect_declaration,
    plan_kind_mutation,
    preview_emission,
    read_fact_by_id,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
    resolve_entity,
    sync_target,
)


class _UnsignedCredentials:
    def for_write(self, _vertex: Path) -> WriteCredentials:
        return WriteCredentials()


def _sign(_observer: str, commitment: str) -> str:
    return "test-signature:" + commitment


def _make_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    boundary: str = "",
    observers: tuple[str, ...] = ("alice",),
    vertex_name: str = "locator",
    loop_name: str = "note",
    extra_loop_names: tuple[str, ...] = (),
) -> tuple[Path, ArrivalLog]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    keypair = ed25519.load_or_generate(tmp_path / "fixture-keys")

    def arrival_sign(_observer: str, commitment: str) -> str:
        return ed25519.sign(keypair, commitment.encode(), domain=ARRIVAL_DOMAIN)

    def fact_sign(commitment: str) -> str:
        return ed25519.sign(keypair, commitment.encode(), domain=FACT_DOMAIN)

    # Direct append helpers later in this test module must use the same
    # custody key as the fixture genesis.
    monkeypatch.setitem(globals(), "_sign", arrival_sign)
    log = ArrivalLog.mint(
        tmp_path / "emit.arrival",
        observer="physical-custodian",
        signer=arrival_sign,
        key=keypair.public_b64,
        at=1.0,
    )
    vertex = tmp_path / "emit.vertex"
    observer_nodes = "".join(f"  {name} {{ }}\n" for name in observers)
    extra_loops = "".join(
        "  " + name + " {\n"
        '    fold { items "collect" 5 }\n'
        "  }\n"
        for name in extra_loop_names
    )
    vertex.write_text(
        f'name "{vertex_name}"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        "strict true\n"
        f"observers {{\n{observer_nodes}}}\n"
        "loops {\n"
        f"  {loop_name} {{\n"
        '    fold { items "collect" 5 }\n'
        f"    {boundary}\n"
        "  }\n"
        f"{extra_loops}"
        "}\n",
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(vertex)))
    declaration_signature = fact_sign(
        fact_commitment_hash("_decl.genesis", 2.0, "physical-custodian", "test", declaration),
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "physical-custodian",
                "test",
                declaration,
                declaration_signature,
            )
        ),
        observer="physical-custodian",
        origin="test",
        at=2.0,
        signer=arrival_sign,
    )
    sync_target(vertex)
    return vertex, log


@pytest.fixture
def arrival_emit_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ArrivalLog]:
    return _make_target(tmp_path, monkeypatch)


@pytest.mark.parametrize("boundary", ("", "boundary every=2"), ids=("passive", "count"))
def test_arrival_runtime_identity_collision_refuses_public_writes_before_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """A historized loop matching its vertex name cannot plan any Arrival write."""
    vertex, log = _make_target(
        tmp_path,
        monkeypatch,
        vertex_name="collision",
        loop_name="collision",
        boundary=boundary,
    )
    before = log.path.read_bytes()

    for invoke in (
        lambda: preview_emission(vertex, "collision", {}, observer="alice"),
        lambda: emit_fact(vertex, "collision", {}, observer="alice"),
        lambda: emit_batch(vertex, [_batch_item("collision", 3.0)]),
    ):
        with pytest.raises(ArrivalRefusal) as caught:
            invoke()
        assert caught.value.source_type == "RuntimeWriteRefused"
        assert str(caught.value) == (
            "Arrival runtime reserves vertex name 'collision' from the loop-name namespace"
        )

    assert log.path.read_bytes() == before
    assert not (vertex.parent / "keys").exists()


def test_arrival_runtime_identity_uses_effective_history_and_allows_repair_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A safe local cache cannot bypass a collision adopted in Arrival history."""
    vertex, log = _make_target(
        tmp_path,
        monkeypatch,
        vertex_name="collision",
        loop_name="collision",
        extra_loop_names=("safe",),
    )
    repair = plan_kind_mutation(vertex, "remove", "collision")
    assert repair.applicable is True

    local_text = remove_vertex_kind(vertex.read_text(encoding="utf-8"), "collision")
    vertex.write_text(
        local_text.replace('name "collision"', 'name "local-only"'), encoding="utf-8"
    )
    local = parse_vertex_file(vertex)
    assert local.name not in local.loops
    evidence = read_summary(vertex)
    assert evidence.read_path == "arrival" and evidence.basis is not None
    state = read_state(vertex)
    assert state.read_path == "arrival" and state.basis == evidence.basis

    before = log.path.read_bytes()
    with pytest.raises(ArrivalRefusal) as caught:
        emit_fact(vertex, "safe", {}, observer="alice")
    assert caught.value.source_type == "RuntimeWriteRefused"
    assert log.path.read_bytes() == before


def test_collision_history_keeps_tick_evidence_inspection_and_exact_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _make_target(
        tmp_path, monkeypatch, vertex_name="collision", loop_name="collision"
    )
    log.append(
        "fact",
        body_of_fact_row(
            ("historical-fact", "collision", 2.5, "alice", "collision", "{}", None)
        ),
        observer="physical-custodian", origin="collision", at=2.5, signer=_sign,
    )
    log.append(
        "tick",
        body_of_tick_row(
            ("ambiguous-tick", "collision", 3.0, None, "collision", "{}",
             None, None, None, None, None)
        ),
        observer="physical-custodian", origin="collision", at=3.0, signer=_sign,
    )
    sync_target(vertex)
    before = log.path.read_bytes()
    ticks = read_ticks(vertex)
    assert [tick["id"] for tick in ticks.items] == ["ambiguous-tick"]
    assert ticks.items[0]["name"] == ticks.items[0]["origin"] == "collision"
    assert read_fact_by_id(vertex, "historical-fact").fact["kind"] == "collision"
    assert "ambiguous-tick" in {event.id for event in read_timeline(vertex).events}
    assert "collision" in inspect_declaration(vertex).declared_kinds
    output = tmp_path / "ambiguous-export.jsonl"
    exported = export_target(vertex, output)
    assert output.read_bytes() == before == log.path.read_bytes()
    assert exported.head == ticks.basis.captured_head
    with pytest.raises(ArrivalRefusal, match="reserves vertex name 'collision'"):
        preview_emission(vertex, "collision", {}, observer="alice")


def test_tick_free_collision_can_be_corrected_by_signed_append_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _make_target(
        tmp_path, monkeypatch, vertex_name="collision", loop_name="collision",
        extra_loop_names=("safe",),
    )
    assert read_ticks(vertex).items == []
    before = log.path.read_bytes()
    keypair = ed25519.load(tmp_path / "fixture-keys")

    def fact_sign(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=FACT_DOMAIN)

    repaired = edit_declaration(
        vertex,
        remove_vertex_kind(vertex.read_text(encoding="utf-8"), "collision"),
        observer="physical-custodian",
        credentials=WriteCredentials(fact_signer=fact_sign, arrival_signer=_sign),
    )
    assert repaired.commit is not None
    assert repaired.file_written is True
    assert log.path.read_bytes().startswith(before)
    assert read_ticks(vertex).items == []
    assert "collision" not in inspect_declaration(vertex).declared_kinds
    emitted = emit_fact(vertex, "safe", {"value": 1}, observer="alice")
    assert emitted.commit is not None
    assert emitted.commit.after.ordinal > repaired.commit.after.ordinal
    assert log.path.read_bytes().startswith(before)


def test_arrival_resolve_entity_uses_receipt_order_and_keeps_basis_on_miss(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    for identifier, ts in (("newer-time", 10.0), ("backdated-later", 1.0)):
        log.append(
            "fact",
            body_of_fact_row(
                (identifier, "note", ts, "alice", "test", json.dumps({"key": "same"}), None)
            ),
            observer="alice",
            origin="test",
            at=ts,
            signer=_sign,
        )
    sync_target(vertex)
    found = resolve_entity(vertex, "note", "key", "same")
    missing = resolve_entity(vertex, "note", "key", "missing")
    assert found.found and found.fact_id == "backdated-later"
    assert found.read_path == "arrival" and found.basis is not None
    assert not missing.found and missing.fact_id is None
    assert missing.basis == found.basis


def test_arrival_resolve_entity_stays_at_captured_head_during_concurrent_append(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A projection advanced after custody capture cannot leak into this read."""
    vertex, log = arrival_emit_target
    log.append(
        "fact",
        body_of_fact_row(
            ("before-capture", "note", 1.0, "alice", "test", json.dumps({"key": "same"}), None)
        ),
        observer="alice",
        origin="test",
        at=1.0,
        signer=_sign,
    )
    sync_target(vertex)

    original_open_snapshot = FileQuery.open_snapshot
    captured: list[Head] = []
    injected = False

    def append_before_snapshot(
        query: FileQuery,
        *,
        captured_head: Head,
        requirement,
        continuation=None,
    ):
        nonlocal injected
        if not injected:
            injected = True
            captured.append(captured_head)
            log.append(
                "fact",
                body_of_fact_row(
                    (
                        "after-capture",
                        "note",
                        2.0,
                        "alice",
                        "test",
                        json.dumps({"key": "same"}),
                        None,
                    )
                ),
                observer="alice",
                origin="test",
                at=2.0,
                signer=_sign,
            )
            # This is an explicit projection advance, not a timing race.  Its
            # own query open goes through this wrapper after ``injected``.
            sync_target(vertex)
        return original_open_snapshot(
            query,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    monkeypatch.setattr(FileQuery, "open_snapshot", append_before_snapshot)

    captured_read = resolve_entity(vertex, "note", "key", "same")
    assert injected and captured == [captured_read.basis.captured_head]
    assert captured_read.found and captured_read.fact_id == "before-capture"

    subsequent_read = resolve_entity(vertex, "note", "key", "same")
    assert subsequent_read.found and subsequent_read.fact_id == "after-capture"
    assert subsequent_read.basis.captured_head.ordinal > captured_read.basis.captured_head.ordinal


def test_arrival_timeline_uses_timestamp_order_with_receipt_ties(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    for identifier, ts in (("newer-time", 10.0), ("backdated-later", 1.0), ("same-time-fact", 5.0)):
        log.append(
            "fact",
            body_of_fact_row(
                (identifier, "note", ts, "alice", "test", json.dumps({"id": identifier}), None)
            ),
            observer="alice",
            origin="test",
            at=ts,
            signer=_sign,
        )
    log.append(
        "tick",
        body_of_tick_row(
            (
                "same-time-tick",
                "checkpoint",
                5.0,
                None,
                "test",
                json.dumps({"count": 1}),
                None,
                None,
                None,
                None,
                None,
            )
        ),
        observer="physical-custodian",
        origin="test",
        at=5.0,
        signer=_sign,
    )
    sync_target(vertex)

    oldest = read_timeline(vertex, start_ts=0.0, end_ts=10.0, limit=10)
    newest = read_timeline(vertex, start_ts=0.0, end_ts=10.0, limit=10, order="newest")

    assert [event.id for event in oldest.events] == [
        "backdated-later",
        "same-time-fact",
        "same-time-tick",
        "newer-time",
    ]
    assert [event.id for event in newest.events] == list(
        reversed([event.id for event in oldest.events])
    )
    assert oldest.events[0].id == "backdated-later"  # later receipt, earlier clock time
    assert oldest.read_path == "arrival"
    assert oldest.store is not None and oldest.basis is not None
    assert oldest.total_events == 4 and not oldest.truncated

    capped = read_timeline(vertex, start_ts=0.0, end_ts=10.0, limit=3)
    assert [event.id for event in capped.events] == [
        "backdated-later",
        "same-time-fact",
        "same-time-tick",
    ]
    assert capped.total_events == 4 and capped.truncated


def test_arrival_timeline_empty_window_retains_basis(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    log.append(
        "fact",
        body_of_fact_row(
            (
                "outside-window",
                "note",
                1.0,
                "alice",
                "test",
                json.dumps({"id": "outside-window"}),
                None,
            )
        ),
        observer="alice",
        origin="test",
        at=1.0,
        signer=_sign,
    )
    sync_target(vertex)

    result = read_timeline(vertex, start_ts=20.0, end_ts=30.0)

    assert result.events == [] and result.total_events == 0 and not result.truncated
    assert result.read_path == "arrival"
    assert result.store is not None and result.basis is not None


def test_arrival_timeline_stays_at_captured_head_during_concurrent_append(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    log.append(
        "fact",
        body_of_fact_row(
            ("visible-fact", "note", 1.0, "alice", "test", json.dumps({"id": "visible"}), None)
        ),
        observer="alice",
        origin="test",
        at=1.0,
        signer=_sign,
    )
    log.append(
        "tick",
        body_of_tick_row(
            ("visible-tick", "checkpoint", 2.0, None, "test", "{}", None, None, None, None, None)
        ),
        observer="physical-custodian",
        origin="test",
        at=2.0,
        signer=_sign,
    )
    sync_target(vertex)

    original_open_snapshot = FileQuery.open_snapshot
    captured: list[Head] = []
    injected = False

    def append_before_snapshot(
        query: FileQuery,
        *,
        captured_head: Head,
        requirement,
        continuation=None,
    ):
        nonlocal injected
        if not injected:
            injected = True
            captured.append(captured_head)
            log.append(
                "fact",
                body_of_fact_row(
                    (
                        "hidden-fact",
                        "note",
                        3.0,
                        "alice",
                        "test",
                        json.dumps({"id": "hidden"}),
                        None,
                    )
                ),
                observer="alice",
                origin="test",
                at=3.0,
                signer=_sign,
            )
            log.append(
                "tick",
                body_of_tick_row(
                    (
                        "hidden-tick",
                        "checkpoint",
                        4.0,
                        None,
                        "test",
                        "{}",
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                ),
                observer="physical-custodian",
                origin="test",
                at=4.0,
                signer=_sign,
            )
            sync_target(vertex)
        return original_open_snapshot(
            query,
            captured_head=captured_head,
            requirement=requirement,
            continuation=continuation,
        )

    monkeypatch.setattr(FileQuery, "open_snapshot", append_before_snapshot)

    captured_read = read_timeline(vertex)
    assert injected and captured == [captured_read.basis.captured_head]
    assert [event.id for event in captured_read.events] == ["visible-fact", "visible-tick"]

    subsequent_read = read_timeline(vertex)
    assert [event.id for event in subsequent_read.events] == [
        "visible-fact",
        "visible-tick",
        "hidden-fact",
        "hidden-tick",
    ]
    assert subsequent_read.basis.captured_head.ordinal > captured_read.basis.captured_head.ordinal


@pytest.mark.parametrize(
    ("mode", "refusal"),
    [("missing", ProjectionAbsent), ("behind", ProjectionBehind)],
)
def test_arrival_timeline_current_projection_refuses_without_repair(
    arrival_emit_target: tuple[Path, ArrivalLog], mode: str, refusal: type[Exception]
) -> None:
    vertex, log = arrival_emit_target
    index = index_path_for(log.path)
    if mode == "missing":
        index.unlink()
    else:
        log.append(
            "fact",
            body_of_fact_row(
                (
                    "unprojected",
                    "note",
                    3.0,
                    "alice",
                    "test",
                    json.dumps({"id": "unprojected"}),
                    None,
                )
            ),
            observer="alice",
            origin="test",
            at=3.0,
            signer=_sign,
        )
    ledger_before = log.path.read_bytes()
    index_before = None if mode == "missing" else index.read_bytes()

    with pytest.raises(refusal):
        read_timeline(vertex)

    assert log.path.read_bytes() == ledger_before
    if mode == "missing":
        assert not index.exists()
    else:
        assert index.read_bytes() == index_before


@pytest.mark.parametrize(
    ("identifier", "payload", "query", "expected"),
    [
        ("absent", {}, "x", False),
        ("null", {"key": None}, None, True),
        ("text", {"key": "1"}, "1", True),
        ("number", {"key": 1}, 1, True),
        ("boolean", {"key": True}, True, True),
    ],
)
def test_arrival_resolve_entity_matches_exact_top_level_key_types(
    arrival_emit_target: tuple[Path, ArrivalLog],
    identifier: str,
    payload: dict,
    query,
    expected: bool,
) -> None:
    vertex, log = arrival_emit_target
    log.append(
        "fact",
        body_of_fact_row((identifier, "note", 3.0, "alice", "test", json.dumps(payload), None)),
        observer="alice",
        origin="test",
        at=3.0,
        signer=_sign,
    )
    sync_target(vertex)
    result = resolve_entity(vertex, "note", "key", query)
    assert result.found is expected
    assert result.fact_id == (identifier if expected else None)
    assert result.address == {"kind": "note", "key": "key", "value": query}
    assert result.store is not None and result.basis is not None
    json.dumps(result.as_dict())


def test_arrival_preview_uses_snapshot_declaration_and_never_writes(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()

    preview = preview_emission(
        vertex,
        "note",
        {"title": "planned"},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )

    assert preview.schema == "loops.sdk/emit-preview/v2"
    assert preview.read_path == "arrival"
    assert preview.store is not None and preview.store.lineage == log.lineage()
    assert preview.captured_head is not None
    assert preview.admitted is True
    assert preview.kind_declared is True
    assert preview.would_store is True
    assert preview.would_fold is True
    assert log.path.read_bytes() == before


def test_arrival_preview_default_credentials_do_not_create_keys(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()
    keys = vertex.parent / "keys"
    assert not keys.exists()

    preview = preview_emission(vertex, "note", {"title": "keyless"}, observer="alice")

    assert preview.admitted is True
    assert not keys.exists()
    assert log.path.read_bytes() == before


def test_arrival_preview_id_override_reports_idempotence_and_divergence(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    receipt = emit_fact(
        vertex,
        "note",
        {"title": "stable"},
        observer="alice",
        ts=5.0,
        credentials=_UnsignedCredentials(),
    )
    before = log.path.read_bytes()

    equal = preview_emission(
        vertex,
        "note",
        {"title": "stable"},
        observer="alice",
        ts=5.0,
        id_override=receipt.id,
        credentials=_UnsignedCredentials(),
    )
    assert equal.admitted is True
    assert equal.would_store is False

    with pytest.raises(ArrivalRefusal, match="different content"):
        preview_emission(
            vertex,
            "note",
            {"title": "different"},
            observer="alice",
            ts=5.0,
            id_override=receipt.id,
            credentials=_UnsignedCredentials(),
        )
    assert log.path.read_bytes() == before


def test_arrival_emit_uses_effective_snapshot_policy_after_locator_changes(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, _log = arrival_emit_target
    locator = vertex.read_text(encoding="utf-8")
    vertex.write_text(
        locator.replace("observers { alice { } }", "observers { bob { } }").replace(
            "  note {", "  stale {"
        ),
        encoding="utf-8",
    )

    preview = preview_emission(
        vertex,
        "note",
        {"title": "effective"},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )
    assert preview.admitted is True
    assert preview.kind_declared is True

    receipt = emit_fact(
        vertex,
        "note",
        {"title": "effective"},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )
    assert receipt.stored is True


def test_arrival_admission_refusal_leaves_physical_bytes_unchanged(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()

    refused = preview_emission(
        vertex,
        "note",
        {"title": "refused"},
        observer="bob",
        credentials=_UnsignedCredentials(),
    )
    assert refused.read_path == "arrival"
    assert refused.admitted is False
    assert refused.kind_declared is True
    assert refused.would_store is False
    assert refused.would_fold is False
    assert refused.captured_head is not None

    with pytest.raises(AdmissionFailed) as caught:
        emit_fact(
            vertex,
            "note",
            {"title": "refused"},
            observer="bob",
            credentials=_UnsignedCredentials(),
        )
    assert caught.value.observer == "bob"
    assert log.path.read_bytes() == before


def test_arrival_strict_kind_preview_and_emit_keep_established_message(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()
    message = "vertex 'locator' declares strict — kind 'other' is not declared"

    preview = preview_emission(
        vertex,
        "other",
        {},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )
    assert preview.admitted is False
    assert preview.strict is True
    assert preview.kind_declared is False
    assert preview.reason == message

    with pytest.raises(AdmissionFailed, match=message) as caught:
        emit_fact(
            vertex,
            "other",
            {},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )
    assert caught.value.kind == "other"
    assert caught.value.vertex == "locator"
    assert log.path.read_bytes() == before


def test_arrival_unknown_observer_reason_is_not_masked_by_strict_kind(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()

    preview = preview_emission(
        vertex,
        "other",
        {},
        observer="bob",
        credentials=_UnsignedCredentials(),
    )

    assert preview.admitted is False
    assert preview.kind_declared is False
    assert preview.reason is not None
    assert "observer 'bob' is not declared" in preview.reason
    assert "kind 'other' is not declared" not in preview.reason
    assert log.path.read_bytes() == before


def test_arrival_emit_commits_then_synchronizes_for_current_read(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before_head = log.head()

    receipt = emit_fact(
        vertex,
        "note",
        {"title": "committed"},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )

    assert receipt.schema == "loops.sdk/emit-receipt/v2"
    assert receipt.write_path == "arrival"
    assert receipt.store is not None and receipt.store.lineage == log.lineage()
    assert receipt.stored is True
    assert receipt.captured_head is not None
    assert receipt.captured_head.ordinal == before_head["ord"]
    assert receipt.commit is not None
    assert receipt.commit.before == receipt.captured_head
    assert receipt.commit.after.ordinal == before_head["ord"] + 1
    assert receipt.witnessed is True
    assert receipt.projection == "synced"
    assert receipt.state_change is None
    assert receipt.delta_count is None
    encoded = receipt.as_dict()
    assert encoded["commit"]["after"]["ordinal"] == receipt.commit.after.ordinal
    assert encoded["commit"]["record_count"] == 1
    assert encoded["commit"]["durability"]["profile"] == "host"

    lookup = read_fact_by_id(vertex, receipt.id)
    assert lookup.fact is not None
    assert lookup.fact["payload"] == {"title": "committed"}
    assert lookup.basis is not None
    assert lookup.basis.captured_head == receipt.commit.after
    assert lookup.basis.projected_through == receipt.commit.after

    retry = emit_fact(
        vertex,
        "note",
        {"title": "committed"},
        observer="alice",
        ts=lookup.fact["ts"],
        id_override=receipt.id,
        credentials=_UnsignedCredentials(),
    )
    assert retry.id == receipt.id
    assert retry.stored is False
    assert retry.commit is None
    assert retry.witnessed is None
    assert retry.projection == "not-requested"
    assert log.head()["ord"] == receipt.commit.after.ordinal


def test_arrival_boundary_emit_returns_tick_and_two_record_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _make_target(tmp_path, monkeypatch, boundary="boundary every=1")

    receipt = emit_fact(
        vertex,
        "note",
        {"title": "boundary"},
        observer="alice",
        credentials=_UnsignedCredentials(),
    )

    assert receipt.tick_mark == "note"
    assert receipt.tick_id is not None
    assert receipt.commit is not None
    assert receipt.as_dict()["commit"]["record_count"] == 2
    ticks = read_ticks(vertex, name="note")
    assert [item["id"] for item in ticks.items] == [receipt.tick_id]


def test_arrival_emit_reports_durable_commit_when_projection_sync_fails(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    projected_before = FileQuery(index_path_for(log.path)).projected_through()

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("injected projection outage")

    monkeypatch.setattr("engine.arrival_maintenance.sync_projection", fail_sync)

    with pytest.raises(CommittedProjectionFailed) as caught:
        emit_fact(
            vertex,
            "note",
            {"title": "durable"},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )

    error = caught.value.as_dict()
    assert error["outcome"] == "committed-projection-failed"
    assert error["details"]["fact_id"]
    assert error["details"]["commit"]["after"]["ordinal"] == log.head()["ord"]
    assert "projection outage" in str(caught.value.__cause__.cause)
    assert FileQuery(index_path_for(log.path)).projected_through() == projected_before


def test_arrival_emit_unknown_outcome_retains_identity_and_is_not_retried(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()
    attempts = 0

    def unknown(_registry, _descriptor, plan, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise WriteCommitUnknown(plan, RuntimeError("transport lost after append call"))

    monkeypatch.setattr("engine.runtime_write.execute_ordinary_write", unknown)

    with pytest.raises(CommittedOutcomeUnknown) as caught:
        emit_fact(
            vertex,
            "note",
            {"title": "uncertain"},
            observer="alice",
            id_override="01UNKNOWN00000000000000000",
            credentials=_UnsignedCredentials(),
        )

    assert attempts == 1
    assert caught.value.details["fact_id"] == "01UNKNOWN00000000000000000"
    assert caught.value.details["captured_head"]["ordinal"] == log.head()["ord"]
    assert caught.value.as_dict()["outcome"] == "unknown"
    assert log.path.read_bytes() == before


def test_arrival_emit_cas_refusal_retains_plan_identity_and_does_not_retry(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    from engine import runtime_write

    initial = log.head()["ord"]
    original_prepare = runtime_write.prepare_ordinary_write
    original_execute = runtime_write.execute_ordinary_write
    attempts = 0

    def prepare_then_advance(*args, **kwargs):
        plan = original_prepare(*args, **kwargs)
        log.append(
            "fact",
            body_of_fact_row(
                (
                    "intervening",
                    "note",
                    8.0,
                    "alice",
                    "test",
                    json.dumps({"title": "intervening"}),
                    None,
                )
            ),
            observer="alice",
            origin="test",
            at=8.0,
            signer=_sign,
        )
        return plan

    def counted_execute(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(runtime_write, "prepare_ordinary_write", prepare_then_advance)
    monkeypatch.setattr(runtime_write, "execute_ordinary_write", counted_execute)

    with pytest.raises(ArrivalRefusal) as caught:
        emit_fact(
            vertex,
            "note",
            {"title": "planned"},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )

    assert attempts == 1
    assert caught.value.source_type == "RuntimeWriteRefused"
    assert caught.value.details["fact_id"]
    assert caught.value.details["captured_head"]["ordinal"] == initial
    assert log.head()["ord"] == initial + 1


def test_arrival_emit_unwitnessed_commit_is_distinct_from_unknown(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target

    def unwitnessed(_registry, _descriptor, plan, **_kwargs):
        after = Head(
            plan.captured_head.lineage,
            plan.captured_head.ordinal + 1,
            "unwitnessed-head",
        )
        commit = Commit(
            before=plan.captured_head,
            records=(),
            after=after,
            durability=DurabilityReceipt(
                profile=DurabilityProfile.HOST,
                mechanism="test",
            ),
        )
        raise NotWitnessed("journal unavailable after durable append", head=after, commit=commit)

    monkeypatch.setattr("engine.runtime_write.execute_ordinary_write", unwitnessed)

    with pytest.raises(CommittedUnwitnessed) as caught:
        emit_fact(
            vertex,
            "note",
            {"title": "unwitnessed"},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )

    assert caught.value.as_dict()["outcome"] == "committed-unwitnessed"
    assert caught.value.details["fact_id"]
    assert caught.value.details["captured_head"]["ordinal"] == log.head()["ord"]
    assert caught.value.details["commit"]["before"]["ordinal"] == log.head()["ord"]
    assert caught.value.details["commit"]["after"]["ordinal"] == log.head()["ord"] + 1


def test_arrival_empty_batch_is_descriptor_first_zero_append(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = arrival_emit_target
    monkeypatch.setattr(
        "sdk.emit.resolve_target",
        lambda _target: pytest.fail("Arrival batch fell through to legacy probing"),
    )

    result = emit_batch(vertex, [], observer="alice")
    assert result.write_path == "arrival"
    assert result.store is not None and result.store.backend == "file"
    assert result.items == []
    assert result.atomic and result.atomicity == "empty-noop"
    assert result.commit is None and result.witnessed is None
    assert result.projection == "not-requested"


def test_batch_normalizes_every_item_before_descriptor_or_legacy_probe(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = arrival_emit_target
    monkeypatch.setattr(
        "sdk.emit._arrival_descriptor",
        lambda _target: pytest.fail("target resolution ran before input normalization"),
    )
    with pytest.raises(InvalidEmissionRequest, match="unsupported batch fact item shape"):
        emit_batch(
            vertex,
            [_batch_item("valid", 3.0), object()],  # type: ignore[list-item]
            observer="alice",
        )


def _batch_item(
    identifier: str,
    ts: float,
    *,
    observer: str = "alice",
    value: str | None = None,
    kind: str = "note",
    admit_undeclared: bool | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": identifier,
        "kind": kind,
        "payload": {"value": value or identifier},
        "observer": observer,
        "origin": "sdk-test",
        "ts": ts,
    }
    if admit_undeclared is not None:
        item["admit_undeclared"] = admit_undeclared
    return item


@pytest.mark.parametrize(
    ("observers", "expected_records"),
    [(("alice",), 1), (("alice", "bob"), 2)],
)
def test_arrival_batch_has_one_shared_commit_for_same_and_mixed_observers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    observers: tuple[str, ...],
    expected_records: int,
) -> None:
    vertex, log = _make_target(tmp_path, monkeypatch, observers=observers)
    items = [_batch_item("one", 3.0)]
    if len(observers) == 1:
        items.append(_batch_item("two", 4.0))
    else:
        items.append(_batch_item("two", 4.0, observer="bob"))

    result = emit_batch(vertex, items, credentials=_UnsignedCredentials())

    assert result.write_path == "arrival"
    assert result.atomic and result.atomicity == "single-append"
    assert result.commit is not None
    assert len(result.commit.records) == expected_records
    assert result.commit.after.ordinal == result.commit.before.ordinal + expected_records
    assert result.captured_head == result.commit.before
    assert result.witnessed is True and result.projection == "synced"
    assert [receipt.id for receipt in result] == ["one", "two"]
    assert all(receipt.commit is None for receipt in result)
    assert all(receipt.stored for receipt in result)
    assert FileLedger(log).head() == result.commit.after
    encoded = json.dumps(result.as_dict())
    assert '"schema": "loops.sdk/batch-emit/v2"' in encoded
    assert '"record_count": ' + str(expected_records) in encoded
    assert '"body"' not in encoded


def test_default_custody_signs_inner_facts_and_outer_arrival_envelopes_by_domain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    vertex = tmp_path / "kyle.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="kyle")
    ordinary = emit_fact(vertex, "item", {"name": "ordinary"}, observer="kyle", ts=10.0)
    batch = emit_batch(
        vertex,
        [
            _batch_item("batch-one", 11.0, observer="kyle", kind="item"),
            _batch_item("batch-two", 12.0, observer="kyle", kind="item"),
        ],
    )
    assert ordinary.commit is not None and batch.commit is not None
    assert initialized.store_path is not None
    log = ArrivalLog((vertex.parent / initialized.store_path).resolve())

    def verify_arrival(key: str, signature: str, digest: str) -> bool:
        return ed25519.verify(
            ed25519.public_key_from_b64(key),
            signature,
            digest.encode(),
            domain=ARRIVAL_DOMAIN,
        )

    # Whole-log authorship validates every signed envelope, including the two
    # records just produced by the public SDK operations.
    verified = verify_authorship(log, verify_arrival)
    assert [row.ordinal for row in verified][-2:] == [
        ordinary.commit.after.ordinal,
        batch.commit.after.ordinal,
    ]

    records = list(log.walk())
    public = ed25519.public_key_from_b64(records[0]["body"]["key"])
    emitted = records[-2:]
    assert [record["k"] for record in emitted] == ["fact", "batch"]
    for record in emitted:
        envelope_digest = content_commitment(
            record["k"],
            record["at"],
            record["observer"],
            record["origin"],
            record["body"],
        )
        assert ed25519.verify(
            public,
            record["sig"],
            envelope_digest.encode(),
            domain=ARRIVAL_DOMAIN,
        )
        assert not ed25519.verify(
            public,
            record["sig"],
            envelope_digest.encode(),
            domain=FACT_DOMAIN,
        )
        rows = [record["body"]] if record["k"] == "fact" else record["body"]["rows"]
        for row in rows:
            inner_digest = fact_commitment_hash(
                row["kind"],
                row["ts"],
                row["observer"],
                row["origin"],
                row["payload"],
            )
            assert ed25519.verify(
                public,
                row["signature"],
                inner_digest.encode(),
                domain=FACT_DOMAIN,
            )
            assert not ed25519.verify(
                public,
                row["signature"],
                inner_digest.encode(),
                domain=ARRIVAL_DOMAIN,
            )


def test_arrival_batch_invalid_later_item_and_conflicts_append_nothing(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    before = log.path.read_bytes()
    with pytest.raises(AdmissionFailed) as invalid:
        emit_batch(
            vertex,
            [_batch_item("valid", 3.0), _batch_item("invalid", 4.0, kind="other")],
            credentials=_UnsignedCredentials(),
        )
    assert invalid.value.details["item_index"] == 1
    assert log.path.read_bytes() == before

    emit_batch(
        vertex,
        [_batch_item("existing", 5.0, value="first")],
        credentials=_UnsignedCredentials(),
    )
    after_existing = log.path.read_bytes()
    with pytest.raises(ArrivalRefusal) as existing_conflict:
        emit_batch(
            vertex,
            [_batch_item("existing", 5.0, value="different")],
            credentials=_UnsignedCredentials(),
        )
    assert existing_conflict.value.details["item_index"] == 0
    assert log.path.read_bytes() == after_existing

    with pytest.raises(ArrivalRefusal) as pending_conflict:
        emit_batch(
            vertex,
            [
                _batch_item("pending", 6.0, value="first"),
                _batch_item("pending", 6.0, value="different"),
            ],
            credentials=_UnsignedCredentials(),
        )
    assert pending_conflict.value.details["item_index"] == 1
    assert log.path.read_bytes() == after_existing


def test_arrival_batch_equal_duplicates_are_explicit_item_noops(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, _log = arrival_emit_target
    emit_batch(
        vertex,
        [_batch_item("existing", 3.0, value="same")],
        credentials=_UnsignedCredentials(),
    )
    result = emit_batch(
        vertex,
        [
            _batch_item("existing", 3.0, value="same"),
            _batch_item("new", 4.0, value="new"),
            _batch_item("new", 4.0, value="new"),
        ],
        credentials=_UnsignedCredentials(),
    )
    assert [receipt.stored for receipt in result] == [False, True, False]
    assert [receipt.id for receipt in result] == ["existing", "new", "new"]
    assert result.commit is not None and len(result.commit.records) == 1


def test_arrival_batch_boundary_receipt_and_lookup_share_synced_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _make_target(tmp_path, monkeypatch, boundary="boundary every=2")
    result = emit_batch(
        vertex,
        [_batch_item("one", 3.0), _batch_item("two", 4.0), _batch_item("three", 5.0)],
        credentials=_UnsignedCredentials(),
    )
    assert result.commit is not None and len(result.commit.records) == 3
    assert result.items[1].tick_id is not None
    assert result.items[1].tick_mark == "note"
    assert result.projection == "synced"
    assert all(read_fact_by_id(vertex, item.id).found for item in result.items)
    ticks = read_ticks(vertex)
    assert len(ticks.items) == 1
    assert ticks.basis is not None and ticks.basis.captured_head == result.commit.after


def test_arrival_batch_atomic_cap_counts_packed_records_before_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _make_target(tmp_path, monkeypatch, observers=("alice", "bob"))
    registry = BackendRegistry()
    registry.register(
        "file",
        lambda _descriptor: (
            FileLedger(log, max_atomic_records=1),
            FileQuery(index_path_for(log.path)),
        ),
        binding_provider=lambda descriptor: file_binding(descriptor.location),
    )
    before = log.path.read_bytes()
    with pytest.raises(ArrivalRefusal) as caught:
        emit_batch(
            vertex,
            [_batch_item("alice", 3.0), _batch_item("bob", 4.0, observer="bob")],
            credentials=_UnsignedCredentials(),
            registry=registry,
        )
    assert caught.value.source_type == AtomicLimitExceeded.__name__
    assert log.path.read_bytes() == before


def test_arrival_batch_stale_plan_refuses_once_without_planned_append(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    from engine import runtime_write

    original_prepare = runtime_write.prepare_batch_write
    original_execute = runtime_write.execute_batch_write
    attempts = 0

    def prepare_then_advance(*args, **kwargs):
        plan = original_prepare(*args, **kwargs)
        log.append(
            "fact",
            body_of_fact_row(("interloper", "note", 2.5, "alice", "test", "{}", None)),
            observer="alice",
            origin="test",
            at=2.5,
            signer=_sign,
        )
        return plan

    def counted_execute(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(runtime_write, "prepare_batch_write", prepare_then_advance)
    monkeypatch.setattr(runtime_write, "execute_batch_write", counted_execute)
    with pytest.raises(ArrivalRefusal) as caught:
        emit_batch(
            vertex,
            [_batch_item("planned-one", 3.0), _batch_item("planned-two", 4.0)],
            credentials=_UnsignedCredentials(),
        )
    assert attempts == 1
    assert caught.value.source_type == "RuntimeWriteRefused"
    assert caught.value.details["fact_ids"] == ["planned-one", "planned-two"]
    assert b"planned-one" not in log.path.read_bytes()
    assert b"interloper" in log.path.read_bytes()


def test_arrival_batch_unknown_and_unwitnessed_keep_every_planned_id(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    from engine import runtime_write

    before = log.path.read_bytes()
    attempts = 0

    def unknown(_registry, _descriptor, plan, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise BatchWriteCommitUnknown(plan, RuntimeError("adapter response lost"))

    monkeypatch.setattr(runtime_write, "execute_batch_write", unknown)
    items = [_batch_item("one", 3.0), _batch_item("two", 4.0)]
    with pytest.raises(CommittedOutcomeUnknown) as uncertain:
        emit_batch(vertex, items, credentials=_UnsignedCredentials())
    assert attempts == 1
    assert uncertain.value.details["fact_ids"] == ["one", "two"]
    assert uncertain.value.details["captured_head"]["ordinal"] == log.head()["ord"]
    assert log.path.read_bytes() == before

    def unwitnessed(_registry, _descriptor, plan, **_kwargs):
        after = Head(plan.captured_head.lineage, plan.captured_head.ordinal + 1, "unknown")
        commit = Commit(
            before=plan.captured_head,
            records=(),
            after=after,
            durability=DurabilityReceipt(DurabilityProfile.HOST, "test"),
        )
        raise NotWitnessed("durable append could not be witnessed", head=after, commit=commit)

    monkeypatch.setattr(runtime_write, "execute_batch_write", unwitnessed)
    with pytest.raises(CommittedUnwitnessed) as not_witnessed:
        emit_batch(vertex, items, credentials=_UnsignedCredentials())
    assert not_witnessed.value.details["fact_ids"] == ["one", "two"]
    assert not_witnessed.value.details["commit"]["after"]["ordinal"] == log.head()["ord"] + 1
    assert log.path.read_bytes() == before


def test_arrival_batch_projection_failure_retains_shared_durable_commit(
    arrival_emit_target: tuple[Path, ArrivalLog], monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = arrival_emit_target
    projected_before = FileQuery(index_path_for(log.path)).projected_through()

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError("injected batch projection outage")

    monkeypatch.setattr("engine.arrival_maintenance.sync_projection", fail_sync)
    with pytest.raises(CommittedProjectionFailed) as caught:
        emit_batch(
            vertex,
            [_batch_item("one", 3.0), _batch_item("two", 4.0)],
            credentials=_UnsignedCredentials(),
        )
    assert caught.value.details["fact_ids"] == ["one", "two"]
    assert caught.value.details["commit"]["after"]["ordinal"] == log.head()["ord"]
    assert FileQuery(index_path_for(log.path)).projected_through() == projected_before


def test_arrival_batch_per_item_admission_override_is_explicit(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, _log = arrival_emit_target
    result = emit_batch(
        vertex,
        [_batch_item("custom", 3.0, kind="other", admit_undeclared=True)],
        credentials=_UnsignedCredentials(),
    )
    assert result.items[0].stored is True
    assert read_fact_by_id(vertex, "custom").found


def test_arrival_replica_emit_refuses_without_touching_ledger(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    vertex.write_text(
        vertex.read_text(encoding="utf-8").replace('role="authority"', 'role="replica"'),
        encoding="utf-8",
    )
    before = log.path.read_bytes()

    with pytest.raises(ArrivalRefusal, match="Authority descriptor"):
        emit_fact(
            vertex,
            "note",
            {"title": "forbidden"},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )

    assert log.path.read_bytes() == before


def test_arrival_resolve_refuses_missing_projection_without_materializing(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    index = index_path_for(log.path)
    before = log.path.read_bytes()
    index.unlink()
    with pytest.raises(ProjectionAbsent):
        resolve_entity(vertex, "note", "key", "missing")
    assert log.path.read_bytes() == before
    assert not index.exists()


def test_arrival_resolve_excludes_internal_facts(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    log.append(
        "fact",
        body_of_fact_row(
            ("internal", "_decl.private", 4.0, "alice", "test", json.dumps({"key": "x"}), None)
        ),
        observer="alice",
        origin="test",
        at=4.0,
        signer=_sign,
    )
    sync_target(vertex)
    result = resolve_entity(vertex, "_decl.private", "key", "x")
    assert not result.found and result.fact_id is None


def test_arrival_preview_refuses_missing_projection_without_materializing(
    arrival_emit_target: tuple[Path, ArrivalLog],
) -> None:
    vertex, log = arrival_emit_target
    index = index_path_for(log.path)
    index.unlink()

    with pytest.raises(ArrivalRefusal) as caught:
        preview_emission(
            vertex,
            "note",
            {"title": "no projection"},
            observer="alice",
            credentials=_UnsignedCredentials(),
        )

    assert caught.value.source_type == "ProjectionAbsent"
    assert not index.exists()


@pytest.mark.parametrize(
    "invoke",
    [
        lambda path: preview_emission(path, "note", {}, observer="alice"),
        lambda path: emit_fact(path, "note", {}, observer="alice"),
        lambda path: emit_batch(path, [], observer="alice"),
    ],
)
def test_arrival_descriptor_member_aggregate_refuses_before_legacy_write(
    arrival_emit_target: tuple[Path, ArrivalLog], invoke
) -> None:
    member, log = arrival_emit_target
    root = member.parent / "root.vertex"
    root.write_text(
        f'name "root"\ncombine {{ vertex "{member}" as="member" }}\n',
        encoding="utf-8",
    )
    before = log.path.read_bytes()

    with pytest.raises(TargetUnsupported, match="descriptor-backed member"):
        invoke(root)

    assert log.path.read_bytes() == before
