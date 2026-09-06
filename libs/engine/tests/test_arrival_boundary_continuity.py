"""Focused C6 continuity checks over receipt-ordered declaration evidence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from engine.arrival_boundary_continuity import (
    BoundaryContinuityConflict,
    analyze_boundary_continuity,
    collect_verified_parameter_rows,
)
from engine.arrival_contract import DeclarationAnchor, Fact, Tick
from engine.declaration import DeclarationResolutionError

LINEAGE = "01C6LINEAGE0000000000000000"


def _vertex_docs(*, name: str = "v", loops: tuple[str, ...] = (), vertex_boundary: bool = False):
    vertex_payload = {
        "name": name,
        "boundary": [
            {"type": "when", "kind": "seal", "match": [], "conditions": [], "run": None}
        ] if vertex_boundary else [],
    }
    return [
        {"kind": "_decl.vertex-defined", "subject": name, "payload": vertex_payload},
        *[
            {
                "kind": "_decl.kind-defined",
                "subject": loop,
                "payload": {"folds": [], "boundary": None},
            }
            for loop in loops
        ],
    ]


def _anchor(documents, *, arrival_ordinal: int = 0):
    genesis = Fact(
        id=LINEAGE,
        kind="_decl.genesis",
        ts=0.0,
        observer="alice",
        origin="",
        payload={"protocol": 1, "documents": documents},
        arrival_ordinal=arrival_ordinal,
        arrival_seq=0,
        payload_text="{}",
    )
    return DeclarationAnchor(LINEAGE, genesis)


def _fact(fid, kind, payload, ordinal, *, lineage=LINEAGE, seq=0):
    body = dict(payload)
    if kind != "_decl.genesis":
        body.setdefault("lineage", lineage)
    return Fact(
        id=fid,
        kind=kind,
        ts=float(ordinal),
        observer="alice",
        origin="",
        payload=body,
        arrival_ordinal=ordinal,
        arrival_seq=seq,
        payload_text="{}",
    )


def _tick(tid, name, ordinal, *, origin="v", ts=2.0, seq=0):
    return Tick(
        id=tid,
        name=name,
        ts=ts,
        since=None,
        origin=origin,
        payload={},
        arrival_ordinal=ordinal,
        arrival_seq=seq,
        payload_text="{}",
    )


def _analyze(
    anchor,
    facts=(),
    ticks=(),
    *,
    target_documents,
    compiled_loop_names=None,
    verified_params=None,
):
    return analyze_boundary_continuity(
        anchor,
        tuple(facts),
        tuple(ticks),
        target_documents=target_documents,
        compiled_loop_names=compiled_loop_names,
        verified_params=verified_params,
    )


def _reason(anchor, facts, ticks, *, target_documents, compiled_loop_names=None):
    with pytest.raises(BoundaryContinuityConflict) as raised:
        _analyze(
            anchor,
            facts,
            ticks,
            target_documents=target_documents,
            compiled_loop_names=compiled_loop_names,
        )
    return raised.value.issue.reason


def test_remove_recreate_same_name_refuses_only_when_owned_tick_exists():
    documents = _vertex_docs(loops=("pulse",))
    anchor = _anchor(documents)
    retired = _fact("retire", "_decl.kind-retired", {"subject": "pulse"}, 2)
    redefined = _fact(
        "redefine",
        "_decl.kind-defined",
        {"subject": "pulse", "payload": {"folds": [], "boundary": None}},
        3,
    )
    assert _reason(
        anchor,
        (retired, redefined),
        (_tick("old", "pulse", 1),),
        target_documents=documents,
    ) == "prior-incarnation"
    assert _analyze(
        anchor,
        (retired, redefined),
        (),
        target_documents=documents,
    ).provable_names >= {"pulse", "cite"}


def test_owned_loop_tick_crossing_vertex_identity_is_refused():
    documents = _vertex_docs(name="v", loops=("pulse",))
    renamed = _fact(
        "rename-away",
        "_decl.vertex-defined",
        {"subject": "v", "payload": {"name": "u", "boundary": []}},
        2,
    )
    returned = _fact(
        "rename-back",
        "_decl.vertex-defined",
        {"subject": "v", "payload": {"name": "v", "boundary": []}},
        3,
    )
    assert _reason(
        _anchor(documents),
        (renamed, returned),
        (_tick("old", "pulse", 1),),
        target_documents=documents,
    ) == "prior-incarnation"


def test_atomic_declaration_group_does_not_expose_transient_retirement():
    documents = _vertex_docs(loops=("pulse",))
    retired = _fact("retire", "_decl.kind-retired", {"subject": "pulse"}, 2)
    redefined = _fact(
        "redefine",
        "_decl.kind-defined",
        {"subject": "pulse", "payload": {"folds": [], "boundary": None}},
        2,
        seq=1,
    )
    result = _analyze(
        _anchor(documents),
        (retired, redefined),
        (_tick("old", "pulse", 1),),
        target_documents=documents,
    )
    assert "pulse" in result.provable_names


def test_absent_retired_target_is_not_attached_by_old_tick_name():
    documents = _vertex_docs(loops=("pulse",))
    retired = _fact("retire", "_decl.kind-retired", {"subject": "pulse"}, 2)
    result = _analyze(
        _anchor(documents),
        (retired,),
        (_tick("old", "pulse", 1),),
        target_documents=_vertex_docs(),
    )
    assert "pulse" not in result.provable_names


def test_foreign_declarations_and_originless_ticks_are_inert():
    documents = _vertex_docs(loops=("pulse",))
    anchor = _anchor(documents)
    foreign_retirement = _fact(
        "foreign-retire",
        "_decl.kind-retired",
        {"subject": "pulse"},
        2,
        lineage="FOREIGN",
    )
    result = _analyze(
        anchor,
        (foreign_retirement,),
        (_tick("originless", "pulse", 1, origin=""),),
        target_documents=documents,
    )
    assert "pulse" in result.provable_names


def test_implicit_cite_is_present_even_without_explicit_document():
    documents = _vertex_docs()
    result = _analyze(
        _anchor(documents),
        (),
        (_tick("cite-tick", "cite", 1),),
        target_documents=documents,
    )
    assert "cite" in result.provable_names


def test_historical_collision_refuses_only_with_vertex_boundary_consumer():
    historical = _vertex_docs(name="v", loops=("v",), vertex_boundary=False)
    retirement = _fact("retire-v", "_decl.kind-retired", {"subject": "v"}, 2)
    old = _tick("collision", "v", 1)
    no_consumer = _analyze(
        _anchor(historical),
        (retirement,),
        (old,),
        target_documents=_vertex_docs(name="v", loops=()),
    )
    assert "cite" in no_consumer.provable_names

    with_consumer = _vertex_docs(name="v", loops=(), vertex_boundary=True)
    assert _reason(
        _anchor(historical),
        (retirement,),
        (old,),
        target_documents=with_consumer,
    ) == "ambiguous-tick-role"


def test_vertex_name_tick_does_not_enter_loop_branch_without_vertex_consumer():
    dynamic = _template_document(params=({"kind": "$DYNAMIC_KIND"},))
    documents = [*_vertex_docs(name="v"), dynamic]
    result = _analyze(
        _anchor(documents),
        (),
        (_tick("ambiguous-v", "v", 1),),
        target_documents=documents,
    )
    assert result.has_unknown_generators is True


def test_same_receipt_ordinal_declaration_and_owned_tick_is_invalid_shape():
    documents = _vertex_docs(loops=("pulse",))
    retirement = _fact("retire", "_decl.kind-retired", {"subject": "pulse"}, 2)
    observer = _fact(
        "observer-pulse",
        "_decl.observer-defined",
        {"subject": "pulse", "payload": {}},
        2,
        seq=1,
    )
    assert _reason(
        _anchor(documents),
        (retirement, observer),
        (_tick("same-receipt", "pulse", 2, seq=2),),
        target_documents=documents,
    ) == "invalid-projection-shape"


def test_later_absence_with_mixed_subject_declarations_identifies_loop_fact():
    documents = _vertex_docs(loops=("pulse",))
    retired = _fact("retire-pulse", "_decl.kind-retired", {"subject": "pulse"}, 2)
    observer = _fact(
        "observer-pulse",
        "_decl.observer-defined",
        {"subject": "pulse", "payload": {}},
        2,
        seq=1,
    )
    with pytest.raises(BoundaryContinuityConflict) as raised:
        _analyze(
            _anchor(documents),
            (retired, observer),
            (_tick("old-pulse", "pulse", 1),),
            target_documents=documents,
        )
    assert raised.value.issue.reason == "prior-incarnation"
    assert raised.value.issue.declaration_fact_id == "retire-pulse"


def test_same_receipt_unknown_declaration_kind_is_typed_invalid_shape():
    documents = _vertex_docs(loops=("pulse",))
    future = _fact(
        "future",
        "_decl.future",
        {"subject": "pulse", "payload": {}},
        2,
    )
    assert _reason(
        _anchor(documents),
        (future,),
        (_tick("same-receipt", "pulse", 2, seq=1),),
        target_documents=documents,
    ) == "invalid-projection-shape"


def test_tick_before_genesis_cannot_use_an_earlier_overlay():
    documents = _vertex_docs(loops=())
    anchor = _anchor(documents, arrival_ordinal=10)
    defined = _fact(
        "early-define",
        "_decl.kind-defined",
        {"subject": "pulse", "payload": {"folds": [], "boundary": None}},
        3,
    )
    with pytest.raises(BoundaryContinuityConflict) as raised:
        _analyze(
            anchor,
            (defined,),
            (_tick("pre-genesis", "pulse", 5),),
            target_documents=_vertex_docs(loops=("pulse",)),
        )
    assert raised.value.issue.reason in {"unproven-loop-role", "prior-incarnation"}


def test_negative_event_time_is_still_receipt_ordered():
    documents = _vertex_docs(loops=("pulse",))
    result = _analyze(
        _anchor(documents),
        (),
        (_tick("pre-epoch", "pulse", 1, ts=-1.0),),
        target_documents=documents,
    )
    assert "pulse" in result.provable_names


def test_generated_name_cross_check_and_dynamic_unknown_membership():
    documents = _vertex_docs(loops=("pulse",))
    result = _analyze(
        _anchor(documents),
        (),
        (),
        target_documents=documents,
        compiled_loop_names=("pulse", "cite"),
    )
    assert result.has_unknown_generators is False
    assert _reason(
        _anchor(documents),
        (),
        (),
        target_documents=documents,
        compiled_loop_names=("cite",),
    ) == "runtime-namespace-mismatch"
    with pytest.raises(BoundaryContinuityConflict):
        _analyze(
            _anchor(documents),
            (),
            (),
            target_documents=documents,
            compiled_loop_names=("pulse", "unrecorded-env-kind"),
        )


def _template_document(*, params=(), from_document=None):
    return {
        "kind": "_decl.source-defined",
        "subject": "generated-template",
        "payload": {
            "form": "template",
            "template": "template.loop",
            "content_sha256": None,
            "params": [{"values": dict(values)} for values in params],
            "from": from_document,
            "loop": {"folds": [], "boundary": None},
        },
    }


def test_literal_dollar_escape_and_verified_params_are_historical_names(tmp_path: Path):
    params_path = tmp_path / "params.txt"
    params_bytes = b"kind\nfrom-file\n"
    params_path.write_bytes(params_bytes)
    pin = hashlib.sha256(params_bytes).hexdigest()
    source = _template_document(
        params=({"kind": "$$literal"},),
        from_document={
            "strategy": "file",
            "path": "params.txt",
            "params_sha256": pin,
        },
    )
    documents = [*_vertex_docs(), source]
    rows = collect_verified_parameter_rows(
        _anchor(documents), (), target_documents=documents, base_dir=tmp_path
    )
    result = _analyze(
        _anchor(documents),
        (),
        (),
        target_documents=documents,
        verified_params=rows,
        compiled_loop_names=("cite", "$literal", "from-file"),
    )
    assert result.provable_names >= {"cite", "$literal", "from-file"}
    assert result.has_unknown_generators is False


def test_dynamic_kind_is_unknown_and_refuses_owned_edge():
    source = _template_document(params=({"kind": "$DYNAMIC_KIND"},))
    documents = [*_vertex_docs(), source]
    reason = _reason(
        _anchor(documents),
        (),
        (_tick("dynamic-tick", "runtime-value", 1),),
        target_documents=documents,
    )
    assert reason == "unproven-generated-incarnation"


def test_unknown_generator_between_owned_ticks_refuses_earlier_interval():
    known_generated = _template_document(params=({"kind": "pulse"},))
    unknown_generated = _template_document(params=({"kind": "$DYNAMIC_KIND"},))
    documents = [*_vertex_docs(), known_generated]
    introduced = _fact(
        "unknown-generated",
        "_decl.source-defined",
        unknown_generated,
        2,
    )
    restored = _fact(
        "known-generated",
        "_decl.source-defined",
        known_generated,
        3,
    )
    before_and_after = (
        _tick("before-unknown", "pulse", 1),
        _tick("after-unknown", "pulse", 4),
    )
    assert _reason(
        _anchor(documents),
        (introduced, restored),
        before_and_after,
        target_documents=documents,
    ) == "unproven-generated-incarnation"
    after_retirement = _analyze(
        _anchor(documents),
        (introduced, restored),
        (
            _tick("after-unknown-1", "pulse", 4),
            _tick("after-unknown-2", "pulse", 5),
        ),
        target_documents=documents,
    )
    assert "pulse" in after_retirement.provable_names


def test_unknown_generator_does_not_poison_proven_direct_membership():
    source = _template_document(params=({"kind": "$DYNAMIC_KIND"},))
    documents = [*_vertex_docs(loops=("pulse",)), source]
    result = _analyze(
        _anchor(documents),
        (),
        (_tick("pulse-tick", "pulse", 1),),
        target_documents=documents,
    )
    assert result.has_unknown_generators is True
    assert "pulse" in result.provable_names


def test_pre_genesis_owned_tick_is_unproven():
    documents = _vertex_docs(loops=("pulse",))
    assert _reason(
        _anchor(documents),
        (),
        (_tick("old", "pulse", -1),),
        target_documents=documents,
    ) == "unproven-loop-role"


def test_vertex_document_without_name_is_not_inferred_from_subject():
    documents = _vertex_docs()
    documents[0]["payload"].pop("name")
    with pytest.raises(DeclarationResolutionError):
        _analyze(_anchor(documents), target_documents=documents)


def test_unknown_old_membership_does_not_attach_by_current_name():
    genesis_documents = _vertex_docs(loops=())
    current_documents = _vertex_docs(loops=("ghost",))
    defined = _fact(
        "define-ghost",
        "_decl.kind-defined",
        {"subject": "ghost", "payload": {"folds": [], "boundary": None}},
        3,
    )
    assert _reason(
        _anchor(genesis_documents),
        (defined,),
        (_tick("old-ghost", "ghost", 1),),
        target_documents=current_documents,
    ) == "unproven-loop-role"


def test_parameter_collector_does_not_open_foreign_source_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    documents = _vertex_docs()
    foreign = _fact(
        "foreign-source",
        "_decl.source-defined",
        {
            "subject": "foreign-template",
            "payload": {
                "form": "template",
                "template": "foreign.loop",
                "params": [],
                "from": {
                    "strategy": "file",
                    "path": "foreign-secret.params",
                    "params_sha256": "0" * 64,
                },
                "loop": {"folds": [], "boundary": None},
            },
        },
        2,
        lineage="FOREIGN",
    )

    original_read_bytes = Path.read_bytes

    def fail_foreign_read(self):
        if self.name == "foreign-secret.params":
            raise AssertionError("foreign source path was opened")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", fail_foreign_read)
    assert collect_verified_parameter_rows(
        _anchor(documents),
        (foreign,),
        target_documents=documents,
        base_dir=tmp_path,
    ) == {}
