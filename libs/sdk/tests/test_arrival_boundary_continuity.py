"""Public C6 boundary-continuity acceptance over declared Arrival history."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row, body_of_tick_row
from engine.handle import WriteCredentials
from lang import genesis_payload, parse_vertex, parse_vertex_file, vertex_to_documents
from lang.ast import FoldCollect, FoldDecl, LoopDef
from lang.vertex_mutation import add_vertex_kind, remove_vertex_kind
from sign import ed25519

from sdk import (
    ArrivalRefusal,
    add_kind,
    edit_declaration,
    emit_fact,
    export_target,
    init_vertex,
    plan_kind_mutation,
    read_state,
    read_ticks,
)


@pytest.fixture(autouse=True)
def _isolated_custody(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _ticked_target(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real Arrival target whose ``item`` loop already sealed once."""
    target = tmp_path / "continuity.vertex"
    initialized = init_vertex(target, store_type="arrival", observer="alice")
    assert initialized.store is not None
    log_path = Path(initialized.store.location)
    current = target.read_text(encoding="utf-8")
    item = '  item {\n    fold {\n      items "collect" 100\n    }\n  }'
    bounded_item = item.replace('\n  }', '\n    boundary every=1\n  }')
    keep = '  keep {\n    fold {\n      items "collect" 100\n    }\n  }'
    assert item in current
    bounded = current.replace(item, bounded_item + "\n" + keep)
    changed = edit_declaration(target, bounded, observer="alice")
    assert changed.commit is not None
    sealed = emit_fact(target, "item", {"n": 1}, observer="alice", ts=1.0)
    assert sealed.tick_id is not None
    return target, log_path


def _ambiguous_vertex_tick_target(tmp_path: Path) -> tuple[Path, Path, WriteCredentials]:
    """Bootstrap pre-C5 history with a vertex-shaped local tick as evidence."""
    keypair = ed25519.load_or_generate(tmp_path / "fixture-key")

    def arrival_sign(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    def fact_sign(_observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain=FACT_DOMAIN)

    log = ArrivalLog.mint(
        tmp_path / "ambiguous.arrival",
        observer="physical-custodian",
        signer=arrival_sign,
        key=keypair.public_b64,
        at=1.0,
    )
    target = tmp_path / "ambiguous.vertex"
    target.write_text(
        f'name "collision"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'observers { "alice" { } }\n'
        'loops {\n'
        '  collision { fold { items "collect" 5 } }\n'
        '  safe { fold { items "collect" 5 } }\n'
        '}\n',
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(target)))
    inner = fact_sign(
        "physical-custodian",
        fact_commitment_hash(
            "_decl.genesis", 2.0, "physical-custodian", "fixture", declaration
        ),
    )
    log.append(
        "fact",
        body_of_fact_row(
            (
                log.lineage(),
                "_decl.genesis",
                2.0,
                "physical-custodian",
                "fixture",
                declaration,
                inner,
            )
        ),
        observer="physical-custodian",
        origin="fixture",
        at=2.0,
        signer=arrival_sign,
    )
    log.append(
        "tick",
        body_of_tick_row(
            (
                "ambiguous-period",
                "collision",
                3.0,
                None,
                "collision",
                "{}",
                None,
                None,
                None,
                None,
                None,
            )
        ),
        observer="physical-custodian",
        origin="collision",
        at=3.0,
        signer=arrival_sign,
    )
    from sdk import sync_target

    sync_target(target)
    return target, log.path, WriteCredentials(
        fact_signer=fact_sign, arrival_signer=arrival_sign
    )


def _verified_generated_ticked_target(tmp_path: Path) -> Path:
    """Declare a generated loop whose historical parameter bytes are pinned."""
    (tmp_path / "template.loop").write_text(
        'source #"echo never-executed"#\n'
        'kind "{{kind}}"\n'
        'observer "alice"\n'
        'format "json"\n',
        encoding="utf-8",
    )
    (tmp_path / "params.txt").write_text("kind\ngenerated\n", encoding="utf-8")
    target = tmp_path / "sourcehistory.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    current = target.read_text(encoding="utf-8")
    declared = current.replace(
        "loops {",
        'sources {\n'
        '  template "template.loop" {\n'
        '    from file "params.txt"\n'
        '    loop {\n'
        '      fold { count "inc" }\n'
        '      boundary every=1\n'
        '    }\n'
        '  }\n'
        '}\n\nloops {',
    )
    adopted = edit_declaration(target, declared, observer="alice")
    assert adopted.commit is not None
    sealed = emit_fact(target, "generated", {"n": 1}, observer="alice", ts=1.0)
    assert sealed.tick_id is not None
    return target


def _inline_generated_ticked_target(tmp_path: Path) -> Path:
    """Declare a generated loop whose literal row is embedded in history."""
    (tmp_path / "template.loop").write_text(
        'source #"echo never-executed"#\n'
        'kind "{{kind}}"\n'
        'observer "alice"\n'
        'format "json"\n',
        encoding="utf-8",
    )
    target = tmp_path / "inlinehistory.vertex"
    init_vertex(target, store_type="arrival", observer="alice")
    current = target.read_text(encoding="utf-8")
    declared = current.replace(
        "loops {",
        'sources {\n'
        '  template "template.loop" {\n'
        '    with kind="inline_generated"\n'
        '    loop {\n'
        '      fold { count "inc" }\n'
        '      boundary every=1\n'
        '    }\n'
        '  }\n'
        '}\n\nloops {',
    )
    source_document = next(
        document.as_json()
        for document in vertex_to_documents(parse_vertex(declared, path=target))
        if document.kind == "_decl.source-defined"
    )
    assert source_document["payload"]["params"] == [
        {"values": {"kind": "inline_generated"}}
    ]
    adopted = edit_declaration(target, declared, observer="alice")
    assert adopted.commit is not None
    sealed = emit_fact(
        target, "inline_generated", {"n": 1}, observer="alice", ts=1.0
    )
    assert sealed.tick_id is not None
    return target


def test_ticked_retirement_refuses_same_name_readd_without_writing_and_keeps_evidence(
    tmp_path: Path,
) -> None:
    """A retired name cannot reuse its earlier local edge through the SDK."""
    target, log_path = _ticked_target(tmp_path)
    retired_text = remove_vertex_kind(target.read_text(encoding="utf-8"), "item")
    before_retirement = log_path.read_bytes()
    retired = edit_declaration(target, retired_text, observer="alice")
    assert retired.commit is not None
    assert log_path.read_bytes().startswith(before_retirement)
    before_refusal = log_path.read_bytes()

    with pytest.raises(ArrivalRefusal) as preview:
        plan_kind_mutation(target, "add", "item")
    assert preview.value.source_type == "DeclarationPreparationRefused"
    evidence = preview.value.details["evidence"]
    assert evidence["phase"] == "prepare"
    assert evidence["effects"]["custody"] == {
        "attempt": "not-entered", "state": "not-attempted"
    }
    assert evidence["cause"]["type"] == "BoundaryContinuityConflict"
    assert evidence["cause"]["details"]["tick_id"]
    assert log_path.read_bytes() == before_refusal

    ticks = read_ticks(target)
    assert len(ticks.items) == 1
    assert ticks.basis is not None
    state = read_state(target)
    assert state.read_path == "arrival" and state.basis == ticks.basis
    exported_path = tmp_path / "retired-evidence.arrival.jsonl"
    exported = export_target(target, exported_path)
    assert exported.head == ticks.basis.captured_head
    assert exported_path.read_bytes() == before_refusal

    fresh_text = add_vertex_kind(
        retired_text, "item_v2", LoopDef(folds=(FoldDecl("items", FoldCollect(100)),))
    )
    fresh = edit_declaration(target, fresh_text, observer="alice")
    assert fresh.commit is not None
    assert log_path.read_bytes().startswith(before_refusal)


def test_in_place_count_and_fold_edit_inherits_the_sealed_edge(tmp_path: Path) -> None:
    """An edit changes interpretation but does not restart a ticked loop."""
    target, _log_path = _ticked_target(tmp_path)
    before = read_ticks(target)
    assert len(before.items) == 1 and before.basis is not None

    current = target.read_text(encoding="utf-8")
    proposed = current.replace('items "collect" 100', 'items "collect" 2').replace(
        "boundary every=1", "boundary every=2"
    )
    edited = edit_declaration(target, proposed, observer="alice")
    assert edited.commit is not None

    first = emit_fact(target, "item", {"n": 2}, observer="alice", ts=2.0)
    second = emit_fact(target, "item", {"n": 3}, observer="alice", ts=3.0)
    assert first.tick_id is None
    assert second.tick_id is not None and second.tick_mark == "item"

    after = read_ticks(target)
    assert len(after.items) == 2
    assert after.basis is not None
    assert after.basis.captured_head.ordinal > before.basis.captured_head.ordinal


def test_disabling_a_boundary_keeps_the_ticked_loop_identity(tmp_path: Path) -> None:
    """Boundary disable is an in-place interpretation edit, not retirement."""
    target, _log_path = _ticked_target(tmp_path)
    disabled = target.read_text(encoding="utf-8").replace("    boundary every=1\n", "", 1)
    applied = edit_declaration(target, disabled, observer="alice")
    assert applied.commit is not None

    emitted = emit_fact(target, "item", {"n": 2}, observer="alice", ts=2.0)
    assert emitted.tick_id is None
    assert len(read_ticks(target).items) == 1


def test_verified_parameter_rows_license_generated_ticked_loop_across_preview_edit_and_runtime(
    tmp_path: Path,
) -> None:
    """The SDK supplies historical pinned rows to all C6 consumers it owns."""
    target = _verified_generated_ticked_target(tmp_path)

    preview = plan_kind_mutation(target, "add", "unrelated")
    assert preview.applicable is True
    changed = add_kind(target, "unrelated", observer="alice")
    assert changed.commit is not None

    again = emit_fact(target, "generated", {"n": 2}, observer="alice", ts=2.0)
    assert again.tick_id is not None and again.tick_mark == "generated"
    assert [tick["name"] for tick in read_ticks(target).items] == [
        "generated",
        "generated",
    ]


def test_inline_parameter_rows_license_generated_ticked_loop_across_preview_edit_and_runtime(
    tmp_path: Path,
) -> None:
    """Literal ``with`` rows use the exact source-document payload shape."""
    target = _inline_generated_ticked_target(tmp_path)

    preview = plan_kind_mutation(target, "add", "unrelated")
    assert preview.applicable is True
    changed = add_kind(target, "unrelated", observer="alice")
    assert changed.commit is not None

    again = emit_fact(
        target, "inline_generated", {"n": 2}, observer="alice", ts=2.0
    )
    assert again.tick_id is not None and again.tick_mark == "inline_generated"
    assert [tick["name"] for tick in read_ticks(target).items] == [
        "inline_generated",
        "inline_generated",
    ]


def test_ambiguous_vertex_tick_allows_consumer_removal_but_refuses_readdition(
    tmp_path: Path,
) -> None:
    """A C5 correction may retain evidence until a vertex boundary consumes it."""
    target, log_path, credentials = _ambiguous_vertex_tick_target(tmp_path)
    corrected = remove_vertex_kind(target.read_text(encoding="utf-8"), "collision")
    repaired = edit_declaration(
        target,
        corrected,
        observer="physical-custodian",
        credentials=credentials,
    )
    assert repaired.commit is not None
    before_refusal = log_path.read_bytes()

    with pytest.raises(ArrivalRefusal) as refusal:
        edit_declaration(
            target,
            corrected.replace("loops {\n", 'loops {\n  boundary when="safe"\n'),
            observer="physical-custodian",
            credentials=credentials,
        )
    assert refusal.value.source_type == "DeclarationPreparationRefused"
    assert refusal.value.details["evidence"]["cause"]["type"] == "BoundaryContinuityConflict"
    assert refusal.value.details["evidence"]["cause"]["details"]["tick_id"] == (
        "ambiguous-period"
    )
    assert log_path.read_bytes() == before_refusal
