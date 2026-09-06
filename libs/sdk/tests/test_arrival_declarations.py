"""Declaration preparation/apply/recovery acceptance over a real Arrival store."""

from __future__ import annotations

import json
from pathlib import Path
from threading import Event, Thread

import pytest
from custody import arrival_signer_for, ensure_signing_key, fact_signer_for
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog, content_commitment
from engine.arrival_contract import (
    AtomicLimitExceeded,
    NotAuthority,
    Profile,
    StoreDescriptor,
)
from engine.arrival_declarations import (
    DeclarationApplyError,
    DeclarationCommittedIncomplete,
    DeclarationOutcomeUnknown,
    DeclarationPreparationRefused,
    DeclarationStale,
    DeclarationUnwitnessed,
    _declaration_lock,
    apply_declaration_edit,
    declaration_intent_path,
    prepare_declaration_edit,
    recover_declaration_edit,
)
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_seam import NotWitnessed
from engine.arrival_registry import BackendRegistry
from engine.handle import WriteCredentials
from sign import ed25519

from sdk import (
    ArrivalRefusal,
    add_kind,
    edit_declaration,
    emit_fact,
    grant_observer,
    init_vertex,
    plan_kind_mutation,
    recover_declaration,
)


@pytest.fixture(autouse=True)
def _isolated_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _verify(domain: str, key: str, signature: str, digest: str) -> bool:
    try:
        public = ed25519.public_key_from_b64(key)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=domain)


def _fixture(tmp_path: Path):
    target = tmp_path / "x.vertex"
    result = init_vertex(target, store_type="arrival", observer="alice")
    assert result.store is not None and result.lineage is not None
    descriptor = StoreDescriptor(
        result.store.backend,
        result.store.location,
        lineage=result.lineage,
        role=Profile.AUTHORITY,
    )
    arrival = arrival_signer_for(target)
    fact = fact_signer_for(target)
    assert arrival is not None and fact is not None
    credentials = WriteCredentials(fact_signer=fact, arrival_signer=arrival)
    return target, descriptor, credentials


def _plan(tmp_path: Path, proposed: str):
    target, descriptor, credentials = _fixture(tmp_path)
    return prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(),
        descriptor,
        target=target,
        proposed_text=proposed,
        observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )


def test_add_edit_remove_and_singleton_edits_prepare_signed_drafts(tmp_path: Path):
    target, descriptor, credentials = _fixture(tmp_path)
    current = target.read_text()
    add = current.replace(
        '  item {\n    fold {\n      items "collect" 100\n    }\n  }',
        "  item {\n"
        "    fold {\n"
        '      items "collect" 100\n'
        "    }\n"
        "  }\n"
        "  extra {\n"
        "    fold {\n"
        '      items "collect" 10\n'
        "    }\n"
        "  }",
    )
    add_plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=add, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert add_plan.status == "planned"
    assert any(change.subject == "extra" for change in add_plan.changes)
    assert len(add_plan.drafts) == 1

    edited = current.replace('items "collect" 100', 'items "collect" 101')
    edit_plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=edited, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert [change.annotation for change in edit_plan.changes] == ["modified"]

    singleton = current.replace('name "x"', 'name "x"\nstrict true')
    singleton_plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=singleton, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert singleton_plan.changes[0].kind == "_decl.vertex-defined"

    removed = add.replace(
        '  item {\n    fold {\n      items "collect" 100\n    }\n  }',
        "",
    )
    remove_plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=removed, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert any(change.annotation == "removed" for change in remove_plan.changes)
    assert any(change.kind == "_decl.kind-retired" for change in remove_plan.changes)


def test_noop_has_no_credentials_or_drafts_and_captures_cache(tmp_path: Path):
    target, descriptor, _credentials = _fixture(tmp_path)
    plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=target.read_text(), observer="alice",
        credentials=None,
        fact_verify=lambda *_args: True,
        arrival_verify=lambda *_args: True,
    )
    assert plan.status == "noop"
    assert plan.drafts == ()
    assert plan.old_cache_bytes == target.read_bytes()
    assert plan.old_cache_sha256 == __import__("hashlib").sha256(
        plan.old_cache_bytes
    ).hexdigest()


def test_invalid_proposal_residence_and_missing_signers_refuse_before_append(tmp_path: Path):
    target, descriptor, credentials = _fixture(tmp_path)
    current = target.read_text()
    bad_syntax = current + "\nthis is not KDL"
    with pytest.raises(DeclarationPreparationRefused, match="grammar/semantics"):
        _plan(tmp_path / "syntax", bad_syntax)

    bad_residence = current.replace("backend=\"file\"", "backend=\"remote\"")
    with pytest.raises(DeclarationPreparationRefused, match="residence"):
        prepare_declaration_edit(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, proposed_text=bad_residence, observer="alice",
            credentials=credentials,
            fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
            arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
        )

    edited = current.replace('items "collect" 100', 'items "collect" 101')
    with pytest.raises(DeclarationPreparationRefused, match="fact and Arrival"):
        prepare_declaration_edit(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, proposed_text=edited, observer="alice",
            credentials=None,
            fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
            arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
        )


def test_new_observer_key_is_introduced_before_declaration_batch(tmp_path: Path):
    target, descriptor, credentials = _fixture(tmp_path)
    key = ensure_signing_key(target, observer="bob").public_b64
    current = target.read_text()
    proposed = current.replace(
        "}\n\nloops {",
        f'  "bob" {{ key "{key}" }}\n}}\n\nloops {{',
    )
    plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=proposed, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert plan.key_introductions == ("bob",)
    assert [draft.kind for draft in plan.drafts] == ["key", "fact"]
    assert plan.drafts[0].authored_at == plan.drafts[-1].authored_at


def test_key_reuse_across_observers_still_requires_named_introduction(tmp_path: Path):
    target, descriptor, credentials = _fixture(tmp_path)
    alice_key = ensure_signing_key(target, observer="alice").public_b64
    current = target.read_text()
    proposed = current.replace(
        "}\n\nloops {",
        f'  "bob" {{ key "{alice_key}" }}\n}}\n\nloops {{',
    )
    plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=proposed, observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert plan.key_introductions == ("bob",)
    assert plan.drafts[0].body == {"observer": "bob", "key": alice_key}


def test_atomic_limit_refuses_final_drafts_before_append(tmp_path: Path, monkeypatch):
    target, descriptor, credentials = _fixture(tmp_path)
    key = ensure_signing_key(target, observer="bob").public_b64
    current = target.read_text()
    proposed = current.replace(
        "}\n\nloops {",
        f'  "bob" {{ key "{key}" }}\n}}\n\nloops {{',
    )
    original = FileLedger.capabilities

    def capped(self):
        from dataclasses import replace

        return replace(original(self), max_atomic_records=1)

    monkeypatch.setattr(FileLedger, "capabilities", capped)
    arrival_path = Path(descriptor.location)
    before = arrival_path.read_bytes()
    with pytest.raises(AtomicLimitExceeded, match="atomic limit"):
        prepare_declaration_edit(
            BackendRegistry.with_builtin_backends(), descriptor,
            target=target, proposed_text=proposed, observer="alice",
            credentials=credentials,
            fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
            arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
        )
    assert arrival_path.read_bytes() == before


def _edited_text(target: Path) -> str:
    return target.read_text().replace('items "collect" 100', 'items "collect" 101')


def _prepared_edit(tmp_path: Path):
    target, descriptor, credentials = _fixture(tmp_path)
    plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=_edited_text(target), observer="alice",
        credentials=credentials,
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    return target, descriptor, plan


def test_noop_apply_does_not_append_or_publish(tmp_path: Path):
    target, descriptor, _credentials = _fixture(tmp_path)
    plan = prepare_declaration_edit(
        BackendRegistry.with_builtin_backends(), descriptor,
        target=target, proposed_text=target.read_text(), observer="alice",
        credentials=None, fact_verify=lambda *_args: True,
        arrival_verify=lambda *_args: True,
    )
    before = Path(descriptor.location).read_bytes()
    result = apply_declaration_edit(BackendRegistry.with_builtin_backends(), plan)
    assert result.status == "noop"
    assert Path(descriptor.location).read_bytes() == before
    assert not declaration_intent_path(target).exists()


def test_stale_cache_refuses_before_intent_or_append(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    arrival = Path(descriptor.location)
    before = arrival.read_bytes()
    target.write_bytes(plan.old_cache_bytes + b"\n")
    with pytest.raises(DeclarationStale, match="cache changed"):
        apply_declaration_edit(BackendRegistry.with_builtin_backends(), plan)
    assert arrival.read_bytes() == before
    assert not declaration_intent_path(target).exists()


def test_nested_draft_mutation_refuses_before_append(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    arrival = Path(descriptor.location)
    before = arrival.read_bytes()
    plan.drafts[-1].body["rows"] = []
    with pytest.raises(Exception, match="drafts changed"):
        apply_declaration_edit(BackendRegistry.with_builtin_backends(), plan)
    assert arrival.read_bytes() == before
    assert not declaration_intent_path(target).exists()


def test_post_append_failure_retains_commit_and_recovery_finishes(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    def fail(phase: str) -> None:
        if phase == "after-append":
            raise OSError("injected after append")

    with pytest.raises(DeclarationCommittedIncomplete) as caught:
        apply_declaration_edit(registry, plan, failure_hook=fail)
    error = caught.value
    assert error.commit is not None
    assert error.head == error.commit.after
    intent = declaration_intent_path(target)
    assert intent.exists()
    recovered = recover_declaration_edit(registry, intent)
    assert recovered.status == "recovered"
    assert recovered.commit is None
    assert recovered.basis == plan.basis
    assert recovered.changes is None
    assert target.read_text() == plan.proposed_text
    assert not intent.exists()


def test_sdk_recover_declaration_serializes_interrupted_committed_edit(
    tmp_path: Path,
):
    target, _descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    def fail(phase: str) -> None:
        if phase == "after-append":
            raise OSError("injected after append")

    with pytest.raises(DeclarationCommittedIncomplete) as caught:
        apply_declaration_edit(registry, plan, failure_hook=fail)

    recovered = recover_declaration(caught.value.intent_path, registry=registry)

    assert recovered.status == "recovered"
    assert recovered.basis is not None
    assert recovered.basis["captured_head"]["record_hash"] == (
        plan.captured_head.record_hash
    )
    assert recovered.captured_head == recovered.basis["captured_head"]
    assert recovered.commit is None
    assert recovered.changes is None
    assert recovered.file_written is True
    assert not caught.value.intent_path.exists()
    json.dumps(recovered.as_dict(), allow_nan=False)


@pytest.mark.parametrize("phase", ["after-cache-link", "before-intent-remove"])
def test_sdk_recovery_does_not_claim_an_already_published_cache_write(tmp_path, phase):
    target, _descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    def fail(actual_phase):
        if actual_phase == phase:
            raise OSError("interrupted after cache publication")

    with pytest.raises(DeclarationCommittedIncomplete) as caught:
        apply_declaration_edit(registry, plan, failure_hook=fail)
    before = (target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns)

    recovered = recover_declaration(caught.value.intent_path, registry=registry)

    assert recovered.status == "recovered"
    assert recovered.phase == "published"
    assert recovered.file_written is False
    assert recovered.commit is None
    assert recovered.changes is None
    assert (target.read_bytes(), target.stat().st_ino, target.stat().st_mtime_ns) == before
    assert not caught.value.intent_path.exists()
    assert recovered.as_dict()["file_written"] is False


def test_sdk_recover_declaration_serializes_known_not_applied_intent(
    tmp_path: Path,
):
    target, _descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    with pytest.raises(DeclarationApplyError, match="append did not start"):
        apply_declaration_edit(
            registry,
            plan,
            failure_hook=lambda phase: (
                (_ for _ in ()).throw(OSError("injected before append"))
                if phase == "after-intent"
                else None
            ),
        )

    intent = declaration_intent_path(target)
    intent_data = json.loads(intent.read_text())
    intent_data.pop("basis")
    intent.write_text(json.dumps(intent_data), encoding="utf-8")
    recovered = recover_declaration(
        intent, registry=registry
    )

    assert recovered.status == "not-applied"
    assert recovered.basis is not None
    assert recovered.basis["captured_head"] == recovered.captured_head
    assert recovered.basis["projected_through"] is None
    assert recovered.basis["view_generation"] is None
    assert recovered.head == recovered.captured_head
    assert recovered.commit is None
    assert recovered.changes is None
    assert recovered.file_written is False
    json.dumps(recovered.as_dict(), allow_nan=False)


def test_after_intent_mutation_cannot_change_detached_append_snapshot(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    original_body = dict(plan.drafts[-1].body)

    def mutate(phase: str) -> None:
        if phase == "after-intent":
            plan.drafts[-1].body["rows"] = []

    result = apply_declaration_edit(registry, plan, failure_hook=mutate)
    assert result.status == "applied"
    ledger, query = registry.open(descriptor)
    try:
        record = ledger.read(result.head.ordinal)
        assert record["body"] == original_body
    finally:
        query.close()
        ledger.close()


def test_recovery_rejects_corrupt_prepared_cache_temp(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    def fail(phase: str) -> None:
        if phase == "after-cache-temp":
            raise OSError("crash after complete temp")

    with pytest.raises(DeclarationCommittedIncomplete):
        apply_declaration_edit(registry, plan, failure_hook=fail)
    intent = declaration_intent_path(target)
    temp = Path(json.loads(intent.read_text())["cache_temp"])
    temp.write_bytes(b"truncated cache")
    with pytest.raises(DeclarationCommittedIncomplete) as caught:
        recover_declaration_edit(registry, intent)
    assert isinstance(caught.value.__cause__, DeclarationStale)
    assert target.read_bytes() == plan.old_cache_bytes
    assert intent.exists()


def test_recovery_validates_captured_predecessor_full_hash(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    intent = declaration_intent_path(target)

    def fail(phase: str) -> None:
        if phase == "after-intent":
            raise OSError("crash before append")

    with pytest.raises(DeclarationApplyError, match="append did not start"):
        apply_declaration_edit(registry, plan, failure_hook=fail)
    data = json.loads(intent.read_text())
    data["captured_head"]["record_hash"] = "0" * 64
    intent.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(DeclarationStale, match="predecessor head"):
        recover_declaration_edit(registry, intent)
    assert intent.exists()


@pytest.mark.parametrize(
    "malformation",
    ("projected-through", "view-generation"),
)
def test_recovery_rejects_malformed_persisted_basis_before_side_effects(
    tmp_path: Path,
    malformation: str,
):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    intent = declaration_intent_path(target)

    with pytest.raises(DeclarationApplyError, match="append did not start"):
        apply_declaration_edit(
            registry,
            plan,
            failure_hook=lambda phase: (
                (_ for _ in ()).throw(OSError("crash before append"))
                if phase == "after-intent"
                else None
            ),
        )

    arrival = Path(descriptor.location)
    arrival_before = arrival.read_bytes()
    cache_before = target.read_bytes()
    data = json.loads(intent.read_text())
    if malformation == "projected-through":
        data["basis"]["projected_through"]["record_hash"] = "0" * 64
    else:
        data["basis"]["view_generation"] = {"invalid": True}
    intent.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(
        (DeclarationApplyError, DeclarationStale), match="basis"
    ):
        recover_declaration_edit(registry, intent)

    assert intent.exists()
    assert arrival.read_bytes() == arrival_before
    assert target.read_bytes() == cache_before


@pytest.mark.parametrize("damage", ("marker", "genesis", "both"))
def test_prepare_refuses_foreign_derived_declaration_anchor_before_signing(
    tmp_path: Path,
    damage: str,
):
    import sqlite3

    from engine.arrival_file_backend import file_projection_path

    target, descriptor, _credentials = _fixture(tmp_path)
    arrival = Path(descriptor.location)
    arrival_before = arrival.read_bytes()
    cache_before = target.read_bytes()
    with sqlite3.connect(file_projection_path(arrival)) as conn:
        if damage in {"marker", "both"}:
            conn.execute(
                "UPDATE store_meta SET value = 'foreign' WHERE key = 'own_lineage'"
            )
        if damage in {"genesis", "both"}:
            conn.execute(
                "UPDATE facts SET id = 'foreign' WHERE kind = '_decl.genesis'"
            )

    signing_attempted = False

    def unexpected_signing(_author: str, _digest: str) -> str:
        nonlocal signing_attempted
        signing_attempted = True
        raise AssertionError("foreign projection identity reached signing")

    with pytest.raises(
        DeclarationPreparationRefused, match="preparation basis"
    ) as caught:
        prepare_declaration_edit(
            BackendRegistry.with_builtin_backends(),
            descriptor,
            target=target,
            proposed_text=_edited_text(target),
            observer="alice",
            credentials=WriteCredentials(
                fact_signer=unexpected_signing,
                arrival_signer=unexpected_signing,
            ),
            fact_verify=lambda *_args: True,
            arrival_verify=lambda *_args: True,
        )

    assert isinstance(caught.value.__cause__, NotAuthority)
    assert signing_attempted is False
    assert not declaration_intent_path(target).exists()
    assert arrival.read_bytes() == arrival_before
    assert target.read_bytes() == cache_before


def test_recovery_of_intent_before_append_is_typed_and_allows_later_edit(
    tmp_path: Path,
):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()

    with pytest.raises(DeclarationApplyError, match="append did not start"):
        apply_declaration_edit(
            registry, plan,
            failure_hook=lambda phase: (
                (_ for _ in ()).throw(OSError("crash before append"))
                if phase == "after-intent" else None
            ),
        )
    recovered = recover_declaration_edit(registry, declaration_intent_path(target))
    assert recovered.status == "not-applied"
    assert recovered.file_written is False
    arrival = arrival_signer_for(target)
    fact = fact_signer_for(target)
    assert arrival is not None and fact is not None
    next_plan = prepare_declaration_edit(
        registry, descriptor, target=target, proposed_text=plan.proposed_text,
        observer="alice", credentials=WriteCredentials(
            fact_signer=fact, arrival_signer=arrival
        ),
        fact_verify=lambda key, sig, digest: _verify(FACT_DOMAIN, key, sig, digest),
        arrival_verify=lambda key, sig, digest: _verify(ARRIVAL_DOMAIN, key, sig, digest),
    )
    assert next_plan.status == "planned"


def test_registry_open_failure_is_known_pre_append_refusal(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    arrival = Path(descriptor.location)
    before = arrival.read_bytes()

    class RefusingRegistry:
        def open(self, _descriptor):
            raise RuntimeError("adapter refused open")

    with pytest.raises(DeclarationApplyError, match="before entering"):
        apply_declaration_edit(RefusingRegistry(), plan)
    assert arrival.read_bytes() == before
    assert declaration_intent_path(target).exists()


def test_target_operation_lock_serializes_concurrent_recovery_workers(
    tmp_path: Path,
):
    target = tmp_path / "x.vertex"
    target.write_text("cache")
    entered = Event()
    release = Event()
    acquired_second = Event()

    def first_worker() -> None:
        with _declaration_lock(target):
            entered.set()
            release.wait(timeout=2)

    def second_worker() -> None:
        entered.wait(timeout=2)
        with _declaration_lock(target):
            acquired_second.set()

    first = Thread(target=first_worker)
    second = Thread(target=second_worker)
    first.start()
    assert entered.wait(timeout=2)
    second.start()
    assert not acquired_second.wait(timeout=0.05)
    release.set()
    assert acquired_second.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)


def test_sdk_edit_declaration_routes_explicit_arrival_with_public_evidence(
    tmp_path: Path,
):
    target, _descriptor, credentials = _fixture(tmp_path)
    result = edit_declaration(
        target,
        _edited_text(target),
        observer="alice",
        credentials=credentials,
    )
    assert result.schema == "loops.sdk/declaration-edit/v2"
    assert result.status == "applied"
    assert result.commit is not None
    assert result.captured_head is not None
    assert result.head is not None
    assert result.commit.after.record_hash == result.head["record_hash"]
    assert result.file_written is True
    assert result.as_dict()["commit"]["after"]["record_hash"] == result.head["record_hash"]
    json.dumps(result.as_dict(), allow_nan=False)


def test_sdk_kind_entrypoint_uses_arrival_coordinator(tmp_path: Path):
    target, _descriptor, _credentials = _fixture(tmp_path)
    preview = plan_kind_mutation(target, "add", "extra")
    assert preview.mode == "arrival-semantic-preview"
    assert preview.applicable is True
    result = add_kind(target, "extra", observer="alice")
    assert result.status == "applied"
    assert result.commit is not None
    assert result.file_written is True


def test_arrival_kind_preview_refuses_new_vertex_name_loop_collision(tmp_path: Path):
    """A proposed loop cannot take the exact effective vertex name."""
    target, descriptor, _credentials = _fixture(tmp_path)
    before = Path(descriptor.location).read_bytes()

    with pytest.raises(ArrivalRefusal) as caught:
        plan_kind_mutation(target, "add", "x")

    assert caught.value.source_type == "DeclarationPreparationRefused"
    assert str(caught.value) == (
        "Arrival runtime reserves vertex name 'x' from the loop-name namespace"
    )
    assert Path(descriptor.location).read_bytes() == before


def test_arrival_kind_preview_keeps_case_distinct_loop_names(tmp_path: Path):
    """The reservation compares declared labels exactly; it does not rename them."""
    target, _descriptor, _credentials = _fixture(tmp_path)

    preview = plan_kind_mutation(target, "add", "X")

    assert preview.applicable is True


def test_arrival_kind_preview_refuses_drifted_cache(tmp_path: Path):
    target, _descriptor, _credentials = _fixture(tmp_path)
    target.write_text(target.read_text().replace('items "collect" 100', 'items "collect" 101'))
    preview = plan_kind_mutation(target, "add", "extra")
    assert preview.applicable is False
    assert "differs from CURRENT" in preview.reason


def test_arrival_duplicate_kind_preview_retains_v2_result(tmp_path: Path):
    target, _descriptor, _credentials = _fixture(tmp_path)
    preview = plan_kind_mutation(target, "add", "item")
    assert preview.applicable is False
    assert preview.schema == "loops.sdk/declaration-preview/v2"
    assert preview.read_path == "arrival"
    json.dumps(preview.as_dict(), allow_nan=False)


def test_keyed_grant_then_emit_verifies_inner_and_outer_domains(tmp_path: Path):
    target, descriptor, _credentials = _fixture(tmp_path)
    bob_key = ensure_signing_key(target, observer="bob").public_b64
    grant = grant_observer(
        target, "bob", key=bob_key, grants=["item"], observer="alice"
    )
    assert grant.status == "applied"
    emitted = emit_fact(target, "item", {"value": 3}, observer="bob", ts=3.0)
    assert emitted.commit is not None
    records = list(ArrivalLog(descriptor.location).walk())
    record = records[-1]
    envelope_digest = content_commitment(
        record["k"], record["at"], record["observer"], record["origin"], record["body"]
    )
    public = ed25519.public_key_from_b64(bob_key)
    assert ed25519.verify(
        public, record["sig"], envelope_digest.encode(), domain=ARRIVAL_DOMAIN
    )
    row = record["body"]
    inner_digest = fact_commitment_hash(
        row["kind"], row["ts"], row["observer"], row["origin"], row["payload"]
    )
    assert ed25519.verify(
        public, row["signature"], inner_digest.encode(), domain=FACT_DOMAIN
    )
    assert not ed25519.verify(
        public, record["sig"], envelope_digest.encode(), domain=FACT_DOMAIN
    )
    assert not ed25519.verify(
        public, row["signature"], inner_digest.encode(), domain=ARRIVAL_DOMAIN
    )


def test_arrival_kind_edit_refuses_unabsorbed_local_drift(tmp_path: Path):
    target, descriptor, _credentials = _fixture(tmp_path)
    target.write_text(
        target.read_text().replace('items "collect" 100', 'items "collect" 999')
    )
    before = Path(descriptor.location).read_bytes()
    with pytest.raises(ArrivalRefusal, match="CURRENT Arrival history"):
        add_kind(target, "extra", observer="alice")
    assert Path(descriptor.location).read_bytes() == before


def test_unwitnessed_append_retains_commit_identity_and_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    from engine.arrival_head_seam import AttestedLedger

    original = AttestedLedger._witness

    def fail(self, commit):
        raise NotWitnessed("injected witness failure", head=commit.after, commit=commit)

    monkeypatch.setattr(AttestedLedger, "_witness", fail)
    with pytest.raises(DeclarationUnwitnessed) as caught:
        apply_declaration_edit(registry, plan)
    error = caught.value
    assert error.commit is not None
    assert error.head == error.commit.after
    monkeypatch.setattr(AttestedLedger, "_witness", original)
    recovered = recover_declaration_edit(registry, error.intent_path)
    assert recovered.status == "recovered"
    assert target.read_text() == plan.proposed_text


def test_unknown_append_retains_intent_and_recovery_verifies_exact_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    from engine.arrival_head_seam import AttestedLedger

    original = AttestedLedger.append

    def unknown(self, expected, drafts):
        self._ledger.append(expected, drafts)
        raise OSError("transport lost after durable append")

    monkeypatch.setattr(AttestedLedger, "append", unknown)
    with pytest.raises(DeclarationOutcomeUnknown) as caught:
        apply_declaration_edit(registry, plan)
    error = caught.value
    assert error.head is None
    assert error.intent_path.exists()
    monkeypatch.setattr(AttestedLedger, "append", original)
    recovered = recover_declaration_edit(registry, error.intent_path)
    assert recovered.status == "recovered"
    assert target.read_text() == plan.proposed_text


def test_competing_cache_after_detach_is_not_overwritten(tmp_path: Path):
    target, descriptor, plan = _prepared_edit(tmp_path)
    registry = BackendRegistry.with_builtin_backends()
    competing = b"editor-created declaration"

    def race(phase: str) -> None:
        if phase == "after-cache-detach":
            target.write_bytes(competing)

    with pytest.raises(DeclarationCommittedIncomplete):
        apply_declaration_edit(registry, plan, failure_hook=race)
    assert target.read_bytes() == competing
    with pytest.raises(DeclarationCommittedIncomplete) as caught:
        recover_declaration_edit(registry, declaration_intent_path(target))
    assert isinstance(caught.value.__cause__, DeclarationStale)
    assert caught.value.head is not None
    assert target.read_bytes() == competing
