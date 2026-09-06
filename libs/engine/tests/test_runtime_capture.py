"""Immutable exact-head runtime capture and planning from captured evidence."""

from __future__ import annotations

import hashlib
import json

import pytest
from atoms import Fact as AtomFact

from engine.arrival_body import body_of_fact_row
from engine.arrival_file_backend import FileLedger
from engine.arrival_maintenance import sync_projection
from engine.declaration import SourceDrift, verify_source_pins_from_documents
from engine.handle import WriteCredentials
from engine.row_commitment import tick_row_hash
from engine.runtime_write import (
    BatchFactInput,
    RuntimeWriteRefused,
    capture_runtime,
    execute_batch_write,
    plan_batch_from_capture,
)
from tests.test_runtime_batch_write import _make_target


def _append_fact(target, identifier: str, kind: str, ts: float, signer, payload=None):
    target.log.append(
        "fact",
        body_of_fact_row(
            (
                identifier,
                kind,
                ts,
                "kyle",
                "capture-test",
                json.dumps(payload or {}),
                None,
            )
        ),
        observer="kyle",
        origin="capture-test",
        at=ts,
        signer=signer,
    )


def _sync(target) -> None:
    sync_projection(
        target.registry,
        target.descriptor,
        through=FileLedger(target.log).head(),
    )


@pytest.mark.parametrize("damage", ["marker", "genesis", "both"])
@pytest.mark.parametrize("source_mode", [False, True])
def test_capture_refuses_foreign_declaration_before_runtime_planning(
    tmp_path, monkeypatch, keys, signer, damage, source_mode
):
    import sqlite3

    from engine.arrival_consumer import open_read
    from engine.arrival_contract import NotAuthority
    from engine.arrival_file_backend import file_projection_path

    target = _make_target(
        tmp_path, monkeypatch, keys, signer, extra_loops='  boundary when="close"\n'
    )
    _append_fact(target, "close-one", "close", 4.0, signer)
    _sync(target)
    before = target.log.path.read_bytes()
    # Damage only derived evidence; custody and its watermark remain valid.
    with sqlite3.connect(file_projection_path(target.log.path)) as conn:
        if damage in {"marker", "both"}:
            conn.execute("UPDATE store_meta SET value='foreign' WHERE key='own_lineage'")
        if damage in {"genesis", "both"}:
            conn.execute("UPDATE facts SET id='foreign' WHERE kind='_decl.genesis'")

    with pytest.raises(NotAuthority), open_read(target.registry, target.descriptor):
        pass
    with pytest.raises(NotAuthority):
        capture_runtime(
            target.registry, target.descriptor, target.locator,
            source_mode=source_mode, evaluated_at=5.0,
        )
    assert target.log.path.read_bytes() == before


def test_capture_survives_locator_and_declaration_change_then_cas_refuses(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    capture = capture_runtime(target.registry, target.descriptor, target.locator)
    before = capture.basis.captured_head

    # Both the ingress locator and declaration ledger advance after H. Planning
    # must still use the bounded declaration; execution must reject the stale H.
    target.vertex.write_text(target.vertex.read_text().replace("note", "changed"), encoding="utf-8")
    _append_fact(target, "decl-change", "_decl.edit", 3.0, signer, {"generation": 2})
    plan = plan_batch_from_capture(
        capture,
        (BatchFactInput(AtomFact("note", 4.0, {}, observer="kyle"), fact_id="planned"),),
        credentials=WriteCredentials(),
    )

    assert plan.captured_head == before
    assert "note" in plan.effective_declaration.loops
    with pytest.raises(RuntimeWriteRefused, match="captured head changed"):
        execute_batch_write(target.registry, target.descriptor, plan)
    assert b'"planned"' not in target.log.path.read_bytes()


def test_repeated_planning_cannot_mutate_capture_evidence(tmp_path, monkeypatch, keys, signer):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    capture = capture_runtime(target.registry, target.descriptor, target.locator)
    exposed = capture.effective_declaration
    exposed.loops.clear()
    exposed_docs = capture.declaration_documents
    exposed_docs[0]["kind"] = "mutated"
    items = (
        BatchFactInput(
            AtomFact("note", 3.0, {"value": "same"}, observer="kyle"),
            fact_id="stable",
        ),
    )

    first = plan_batch_from_capture(capture, items, credentials=WriteCredentials())
    second = plan_batch_from_capture(capture, items, credentials=WriteCredentials())

    assert first == second
    assert "note" in capture.effective_declaration.loops
    assert capture.declaration_documents[0]["kind"] != "mutated"
    assert all(fact.id != "stable" for fact in capture.facts)


def test_pending_boundary_precedes_items_and_recorded_tick_is_not_reemitted(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "ok"})
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert [tick.name for tick in capture.pending_boundaries] == ["note"]

    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=WriteCredentials(tick_signer=lambda digest: signer("kyle", digest)),
        include_pending_boundaries=True,
    )
    assert [draft.kind for draft in plan.drafts] == ["tick"]
    assert plan.pending_tick_ids == (plan.drafts[0].body["id"],)
    assert plan.pending_tick_names == ("note",)
    assert plan.items == ()
    outcome = execute_batch_write(target.registry, target.descriptor, plan)
    assert outcome.pending_tick_ids == plan.pending_tick_ids
    _sync(target)

    recorded = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recorded.pending_boundaries == ()
    with pytest.raises(RuntimeWriteRefused, match="at least one fact or pending boundary"):
        plan_batch_from_capture(
            recorded,
            (),
            credentials=WriteCredentials(),
            include_pending_boundaries=True,
        )


def test_items_after_pending_boundary_use_the_reset_candidate_state(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"',
    )
    _append_fact(target, "old-note", "note", 3.0, signer, {"value": "old"})
    _append_fact(target, "old-seal", "seal", 4.0, signer)
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )

    plan = plan_batch_from_capture(
        capture,
        (
            BatchFactInput(
                AtomFact("note", 6.0, {"value": "new"}, observer="kyle"),
                fact_id="new-note",
            ),
            BatchFactInput(
                AtomFact("seal", 7.0, {}, observer="kyle"),
                fact_id="new-seal",
                admit_undeclared=True,
            ),
        ),
        credentials=WriteCredentials(),
        include_pending_boundaries=True,
    )
    assert [draft.kind for draft in plan.drafts] == ["tick", "batch", "tick"]
    pending_payload = json.loads(plan.drafts[0].body["payload"])
    next_payload = json.loads(plan.drafts[-1].body["payload"])
    assert [item["value"] for item in pending_payload["items"]] == ["old"]
    assert [item["value"] for item in next_payload["items"]] == ["new"]


def test_boundary_scan_state_is_retained_even_when_no_prelude_tick_fires(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="close"\n',
    )
    _append_fact(target, "period-start", "note", 3.0, signer)
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=4.0,
    )
    assert capture.pending_boundaries == ()

    plan = plan_batch_from_capture(
        capture,
        (
            BatchFactInput(
                AtomFact("close", 5.0, {}, observer="kyle"),
                fact_id="period-close",
                admit_undeclared=True,
            ),
        ),
        credentials=WriteCredentials(),
        include_pending_boundaries=True,
    )
    tick = next(draft for draft in plan.drafts if draft.kind == "tick")
    assert tick.body["name"] == "batch-target"
    assert tick.body["since"] == 2.0


def test_pending_boundary_preserves_period_window_and_signed_era(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer)
    _sync(target)
    first_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    first = plan_batch_from_capture(
        first_capture,
        (),
        credentials=WriteCredentials(tick_signer=lambda digest: signer("kyle", digest)),
        include_pending_boundaries=True,
    )
    first_tick = first.drafts[0].body
    assert first_tick["since"] == 3.0
    assert first_tick["fact_cursor"] == "seal-one"
    assert first_tick["window_hash"]
    assert first_tick["signature"] is not None
    execute_batch_write(target.registry, target.descriptor, first)
    _sync(target)

    _append_fact(target, "note-two", "note", 6.0, signer, {"value": "two"})
    _append_fact(target, "seal-two", "seal", 7.0, signer)
    _sync(target)
    second_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=8.0,
    )
    with pytest.raises(RuntimeWriteRefused, match="unsigned tick in the signed tick era"):
        plan_batch_from_capture(
            second_capture,
            (),
            credentials=WriteCredentials(),
            include_pending_boundaries=True,
        )


def test_multiple_pending_boundaries_form_one_exact_projected_chain(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"',
        extra_loops=(
            "  audit {\n"
            '    fold { items "collect" 20 }\n'
            '    boundary when="close"\n'
            "  }\n"
        ),
    )
    _append_fact(target, "note-one", "note", 3.0, signer)
    _append_fact(target, "audit-one", "audit", 4.0, signer)
    _append_fact(target, "seal-one", "seal", 5.0, signer)
    _append_fact(target, "close-one", "close", 6.0, signer)
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=7.0,
    )
    assert [tick.name for tick in capture.pending_boundaries] == ["note", "audit"]

    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=WriteCredentials(tick_signer=lambda digest: signer("kyle", digest)),
        include_pending_boundaries=True,
    )
    assert [draft.kind for draft in plan.drafts] == ["tick", "tick"]
    first, second = (draft.body for draft in plan.drafts)
    assert plan.pending_tick_names == ("note", "audit")
    assert plan.pending_tick_ids == (first["id"], second["id"])
    assert first["since"] == 3.0
    assert second["since"] == 4.0
    assert first["fact_cursor"] == second["fact_cursor"] == "close-one"
    assert second["prev_hash"] == tick_row_hash(
        (
            first["id"],
            first["name"],
            first["ts"],
            first["since"],
            first["origin"],
            first["payload"],
            first["prev_hash"],
            first["window_start"],
            first["fact_cursor"],
            first["window_hash"],
            first["signature"],
        )
    )
    assert second["window_start"] == "close-one"
    assert second["window_hash"] == hashlib.sha256().hexdigest()

    outcome = execute_batch_write(target.registry, target.descriptor, plan)
    assert outcome.commit is not None
    _sync(target)
    projected = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=7.0,
    )
    assert projected.pending_boundaries == ()
    committed = projected.ticks[-2:]
    assert tuple(tick.id for tick in committed) == plan.pending_tick_ids
    assert committed[1].prev_hash == second["prev_hash"]
    assert committed[1].window_hash == second["window_hash"]


def test_count_boundary_is_not_invented_during_pending_scan(tmp_path, monkeypatch, keys, signer):
    target = _make_target(tmp_path, monkeypatch, keys, signer, boundary="boundary every=2")
    _append_fact(target, "one", "note", 3.0, signer)
    _append_fact(target, "two", "note", 4.0, signer)
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert capture.pending_boundaries == ()
    plan = plan_batch_from_capture(
        capture,
        (BatchFactInput(AtomFact("note", 6.0, {}, observer="kyle"), fact_id="third"),),
        credentials=WriteCredentials(),
    )
    assert [draft.kind for draft in plan.drafts] == ["fact"]


def test_source_capture_reattaches_ingress_merges_template_specs_and_pins(
    tmp_path, monkeypatch, keys, signer
):
    template = tmp_path / "feed.loop"
    template.write_text(
        'source "echo generated"\nkind "{{kind}}"\nobserver "kyle"\n',
        encoding="utf-8",
    )
    source_text = """sources {
  template "./feed.loop" {
    with kind="generated"
    loop {
      fold {
        items "collect" 5
      }
    }
  }
}
"""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        source_text=source_text,
    )
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=3.0,
    )
    assert [source.kind for source, _cadence in capture.sources] == ["generated"]
    plan = plan_batch_from_capture(
        capture,
        (
            BatchFactInput(
                AtomFact("generated", 4.0, {}, observer="kyle"),
                fact_id="generated-fact",
            ),
        ),
        credentials=WriteCredentials(),
    )
    assert plan.items[0].fact_id == "generated-fact"

    ingress = _make_target(
        tmp_path / "ingress",
        monkeypatch,
        keys,
        signer,
        source_text="""sources "sequential" {
  source "echo inline" {
    kind "inline"
    observer "kyle"
    env TOKEN="captured-secret"
  }
}
""",
    )
    ingress_capture = capture_runtime(
        ingress.registry,
        ingress.descriptor,
        ingress.locator,
        source_mode=True,
        evaluated_at=3.0,
    )
    sequential = ingress_capture.sources[0][0]
    assert sequential.sources[0].env == {"TOKEN": "captured-secret"}
    caller_source = ingress.locator.sources_blocks[0].sources[0]
    object.__setattr__(caller_source, "env", (("TOKEN", "mutated-after-capture"),))
    ingress.locator.loops.clear()
    assert ingress_capture.sources[0][0].sources[0].env == {
        "TOKEN": "captured-secret"
    }
    assert ingress_capture.effective_declaration.sources_blocks[0].sources[0].env == (
        ("TOKEN", "captured-secret"),
    )

    template.write_text(template.read_text().replace("generated", "drifted"))
    assert plan_batch_from_capture(
        capture,
        (
            BatchFactInput(
                AtomFact("generated", 4.0, {}, observer="kyle"),
                fact_id="generated-fact",
            ),
        ),
        credentials=WriteCredentials(),
    ) == plan
    with pytest.raises(SourceDrift):
        capture_runtime(
            target.registry,
            target.descriptor,
            target.locator,
            source_mode=True,
            evaluated_at=3.0,
        )


def test_document_pin_helper_never_opens_a_store(tmp_path) -> None:
    source = tmp_path / "source.loop"
    source.write_text("stable", encoding="utf-8")
    documents = [
        {
            "kind": "_decl.source-defined",
            "subject": "source",
            "payload": {
                "path": "source.loop",
                "content_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
        }
    ]
    verify_source_pins_from_documents(documents, tmp_path)
    source.write_text("changed", encoding="utf-8")
    with pytest.raises(SourceDrift):
        verify_source_pins_from_documents(documents, tmp_path)
