"""Declaration-update orchestration — plan → apply → recover (S2 oracle).

LIBS_CHANGES P0.2 + P0.3 acceptance, parametrized over BOTH canonical
residences: (1) end-to-end plan→apply (genesis, then add/modify/retire)
with the store authoritative and the ``.vertex`` file replaced atomically;
(2) a stale preview refuses with the canonical log byte-identical and the
file untouched; (3) interrupt-then-recover idempotence via the injectable
file-write seam — safe-to-finish completes once, a second recover is an
already-applied no-op, and a concurrent writer classifies conflict with
nothing clobbered; (4) ``audit_deep`` passes after every JSONL ceremony.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from lang import parse_vertex
from lang.document import vertex_to_documents

from engine.canonical_audit import audit_deep
from engine.ceremony import (
    IntentCorrupt,
    _fingerprint_documents,
    _open_store,
    apply_declaration_update,
    intent_path_for,
    plan_declaration_update,
    recover_declaration_update,
)
from engine.declaration import resolve_declaration_documents
from engine.handle import WriteCredentials

# --- fixtures --------------------------------------------------------------

BASE = (
    'name "x"\n{store}\nloops {{\n'
    '  a {{ fold {{ n "latest" }} }}\n  b {{ fold {{ n "latest" }} }}\n}}\n'
)
# add c, modify b, retire a — one ceremony exercising all three change kinds
EDIT = (
    'name "x"\n{store}\nloops {{\n'
    '  b {{ fold {{ n "inc" }} }}\n  c {{ fold {{ n "latest" }} }}\n}}\n'
)


def _signer(observer: str, digest: str) -> str | None:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


class Creds:
    def for_write(self, vertex: Path) -> WriteCredentials:
        return WriteCredentials(fact_signer=_signer)


@pytest.fixture(params=["jsonl", "sqlite"])
def world(request, tmp_path: Path):
    locator = "./x.jsonl" if request.param == "jsonl" else "./x.db"
    store_line = f'store "{locator}"'
    vertex = tmp_path / "x.vertex"
    vertex.write_text(BASE.format(store=store_line), encoding="utf-8")
    return {
        "mode": request.param,
        "vertex": vertex,
        "base": BASE.format(store=store_line),
        "edit": EDIT.format(store=store_line),
        "log": tmp_path / "x.jsonl",
        "index": tmp_path / ("x.db"),
    }


def _audit_ok(world) -> None:
    if world["mode"] == "jsonl":
        report = audit_deep(world["log"])
        assert report.ok, report
    else:
        # sqlite-canonical has no log; the store IS the db — nothing to audit
        assert not world["log"].exists()


def _resolved_docs(world) -> list[dict]:
    return resolve_declaration_documents(world["index"])


def _apply_genesis(world):
    preview = plan_declaration_update(world["vertex"])
    result = apply_declaration_update(preview, observer="obs", credentials=Creds())
    assert result.status == "applied", result
    return preview, result


# --- oracle 1: end-to-end plan→apply on both backends ----------------------


def test_plan_exposes_genesis_shape(world):
    preview = plan_declaration_update(world["vertex"])
    assert preview.mode == "genesis"
    assert preview.declaration_status == "file-pre-genesis"
    assert preview.authority == "file"
    assert preview.canonical_mode == world["mode"]
    assert preview.expected_head is None
    assert preview.applicable
    assert preview.changes == ()
    assert preview.proposed_text == world["base"]
    assert preview.pending_intent is None


def test_genesis_plan_apply_end_to_end(world):
    _, result = _apply_genesis(world)
    assert result.receipt["lineage"]
    assert result.file_written
    # Store authoritative: resolution matches the proposal projection.
    docs = _resolved_docs(world)
    want = [d.as_json() for d in vertex_to_documents(parse_vertex(world["base"]))]
    assert _fingerprint_documents(docs) == _fingerprint_documents(want)
    # File intact, intent cleared.
    assert world["vertex"].read_text(encoding="utf-8") == world["base"]
    assert not intent_path_for(world["vertex"]).exists()
    _audit_ok(world)


def test_edit_plan_apply_add_modify_retire(world):
    _apply_genesis(world)
    world["vertex"].write_text(world["edit"], encoding="utf-8")
    preview = plan_declaration_update(world["vertex"])
    assert preview.mode == "edit"
    assert preview.declaration_status == "store"
    assert preview.authority == "store"
    assert preview.expected_head is not None
    annotations = sorted(c.annotation for c in preview.changes)
    assert annotations == ["added", "modified", "removed"]

    result = apply_declaration_update(preview, observer="obs", credentials=Creds())
    assert result.status == "applied", result

    # Declaration resolution round-trips the edited file's projection.
    docs = _resolved_docs(world)
    want = [d.as_json() for d in vertex_to_documents(parse_vertex(world["edit"]))]
    assert _fingerprint_documents(docs) == _fingerprint_documents(want)
    subjects = {(d["kind"], d["subject"]) for d in docs}
    assert ("_decl.kind-defined", "a") not in subjects  # retired
    assert ("_decl.kind-defined", "c") in subjects  # added
    assert world["vertex"].read_text(encoding="utf-8") == world["edit"]
    assert not intent_path_for(world["vertex"]).exists()
    _audit_ok(world)


def test_unchanged_file_is_a_noop(world):
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"])
    assert preview.changes == ()
    before = _canonical_bytes(world)
    result = apply_declaration_update(preview, observer="obs", credentials=Creds())
    assert result.status == "noop"
    assert _canonical_bytes(world) == before


def test_unsigned_apply_refuses_and_leaves_no_intent(world):
    preview = plan_declaration_update(world["vertex"])
    result = apply_declaration_update(preview, observer="obs", credentials=None)
    assert result.status == "refused"
    assert not intent_path_for(world["vertex"]).exists()
    if world["mode"] == "jsonl":
        assert not world["log"].exists() or world["log"].read_text() == ""


# --- oracle 2: stale-preview refusal ---------------------------------------


def _canonical_bytes(world) -> bytes:
    path = world["log"] if world["mode"] == "jsonl" else world["index"]
    return path.read_bytes() if path.exists() else b""


def test_stale_preview_refuses_log_byte_identical_file_untouched(world):
    _apply_genesis(world)
    # Preview A against the genesis head…
    world["vertex"].write_text(world["edit"], encoding="utf-8")
    preview_a = plan_declaration_update(world["vertex"])
    # …then a concurrent edit lands (its own full plan→apply).
    other = world["base"].replace(
        'b { fold { n "latest" } }', 'b { fold { n "inc" } }'
    )
    preview_b = plan_declaration_update(world["vertex"], proposed_text=other)
    assert apply_declaration_update(
        preview_b, observer="obs", credentials=Creds()
    ).status == "applied"

    log_before = _canonical_bytes(world) if world["mode"] == "jsonl" else None
    docs_before = _resolved_docs(world)
    file_before = world["vertex"].read_text(encoding="utf-8")

    result = apply_declaration_update(preview_a, observer="obs", credentials=Creds())
    assert result.status == "stale"
    if world["mode"] == "jsonl":
        assert _canonical_bytes(world) == log_before  # byte-identical log
    assert _resolved_docs(world) == docs_before
    assert world["vertex"].read_text(encoding="utf-8") == file_before
    assert not intent_path_for(world["vertex"]).exists()
    _audit_ok(world)


def test_stale_genesis_preview_refuses(world):
    preview_a = plan_declaration_update(world["vertex"])
    _apply_genesis(world)  # concurrent absorb opens the lineage first
    result = apply_declaration_update(preview_a, observer="obs", credentials=Creds())
    assert result.status == "stale"
    assert not intent_path_for(world["vertex"]).exists()


# --- oracle 3: interrupt-then-recover idempotence --------------------------


def _boom(vertex_path: Path, proposed_text: str | None) -> None:
    raise RuntimeError("killed between store commit and file replace")


def test_interrupt_then_recover_safe_to_finish_then_noop(world):
    _apply_genesis(world)
    world["vertex"].write_text(world["base"], encoding="utf-8")  # pre-edit file
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    result = apply_declaration_update(
        preview, observer="obs", credentials=Creds(), write_file=_boom
    )
    assert result.status == "needs-recovery"
    intent = result.intent_path
    assert intent is not None and intent.exists()
    # Store committed, file stranded at the old text.
    assert world["vertex"].read_text(encoding="utf-8") == world["base"]

    outcome = recover_declaration_update(intent)
    assert outcome.classification == "safe-to-finish"
    assert outcome.finished
    assert world["vertex"].read_text(encoding="utf-8") == world["edit"]
    assert not intent.exists()

    # Second recover: already-applied no-op.
    again = recover_declaration_update(intent)
    assert again.classification == "already-applied"
    assert not again.finished
    docs = _resolved_docs(world)
    want = [d.as_json() for d in vertex_to_documents(parse_vertex(world["edit"]))]
    assert _fingerprint_documents(docs) == _fingerprint_documents(want)
    _audit_ok(world)


def test_recover_conflict_leaves_everything_untouched(world):
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    result = apply_declaration_update(
        preview, observer="obs", credentials=Creds(), write_file=_boom
    )
    intent = result.intent_path

    # A foreign writer lands ANOTHER edit directly on the store meanwhile.
    from lang.document import diff_documents

    other_ast = parse_vertex(
        world["edit"].replace('c { fold { n "latest" } }', 'd { fold { n "latest" } }')
    )
    store = _open_store(preview.canonical_path)
    try:
        head = resolve_declaration_documents(world["index"])
        store.absorb_edit(
            diff_documents(head, vertex_to_documents(other_ast)),
            observer="other",
            origin="",
            fact_signer=_signer,
        )
    finally:
        store.close()

    file_before = world["vertex"].read_text(encoding="utf-8")
    intent_before = intent.read_bytes()
    outcome = recover_declaration_update(intent)
    assert outcome.classification == "conflict"
    assert not outcome.finished
    assert intent.exists() and intent.read_bytes() == intent_before
    assert world["vertex"].read_text(encoding="utf-8") == file_before
    _audit_ok(world)


def test_recover_not_applied_discards_void_intent(world):
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    # Death BEFORE the store commit: intent written, ceremony never ran.
    from engine.ceremony import _write_intent

    intent = _write_intent(preview, "obs")
    docs_before = _resolved_docs(world)
    outcome = recover_declaration_update(intent)
    assert outcome.classification == "not-applied"
    assert not intent.exists()
    assert _resolved_docs(world) == docs_before
    assert world["vertex"].read_text(encoding="utf-8") == world["base"]


def test_recover_not_applied_genesis_intent(world):
    preview = plan_declaration_update(world["vertex"])
    from engine.ceremony import _write_intent

    intent = _write_intent(preview, "obs")
    outcome = recover_declaration_update(intent)
    assert outcome.classification == "not-applied"
    assert not intent.exists()


def test_pending_intent_blocks_plan_and_apply(world):
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    apply_declaration_update(
        preview, observer="obs", credentials=Creds(), write_file=_boom
    )
    blocked = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    assert not blocked.applicable
    assert blocked.pending_intent == intent_path_for(world["vertex"])
    res = apply_declaration_update(blocked, observer="obs", credentials=Creds())
    assert res.status == "pending-intent"
    # A fresh-looking preview is equally blocked (apply re-checks the disk).
    res2 = apply_declaration_update(preview, observer="obs", credentials=Creds())
    assert res2.status == "pending-intent"


def test_corrupt_intent_refuses_loudly(world):
    intent = intent_path_for(world["vertex"])
    intent.write_text("{not json", encoding="utf-8")
    with pytest.raises(IntentCorrupt):
        recover_declaration_update(intent)
    assert intent.exists()


def test_recover_after_index_loss_classifies_from_the_log(world):
    """JSONL only: killing between log append + index commit AND losing the
    derived index still classifies applied — the log is the store."""
    if world["mode"] != "jsonl":
        pytest.skip("index-loss recovery is a JSONL-canonical property")
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    result = apply_declaration_update(
        preview, observer="obs", credentials=Creds(), write_file=_boom
    )
    world["index"].unlink()  # the derived index is disposable
    # A rebuilt index has no own_lineage marker (identity is adopted, never
    # inferred — the S1b ratchet); recovery surfaces that typed refusal.
    from engine.declaration import UnadoptedLineage

    with pytest.raises(UnadoptedLineage):
        recover_declaration_update(result.intent_path)
    store = _open_store(preview.canonical_path)
    try:
        store.adopt_lineage()
    finally:
        store.close()
    outcome = recover_declaration_update(result.intent_path)
    assert outcome.classification == "safe-to-finish" and outcome.finished
    assert world["vertex"].read_text(encoding="utf-8") == world["edit"]
    _audit_ok(world)


# --- canonical-store writability (SOL-R1-04) --------------------------------


def _chmod_canonical_readonly(world) -> Path:
    canonical = world["log"] if world["mode"] == "jsonl" else world["index"]
    canonical.chmod(0o444)
    return canonical


def test_plan_on_readonly_canonical_store_is_not_applicable(world):
    """SOL-R1-04: applicability must evaluate the CANONICAL store's
    writability, not just the vertex file's — on both backends."""
    import os

    _apply_genesis(world)
    canonical = _chmod_canonical_readonly(world)
    if os.access(canonical, os.W_OK):
        pytest.skip("cannot make file read-only here (running as root?)")
    try:
        preview = plan_declaration_update(
            world["vertex"], proposed_text=world["edit"]
        )
        assert preview.applicable is False
        assert "not writable" in preview.reason
        assert str(canonical) in preview.reason
    finally:
        canonical.chmod(0o644)


def test_forced_apply_on_readonly_store_refuses_typed_with_no_intent(world):
    """SOL-R1-04: a forced apply (preview.applicable overridden) must be a
    typed refusal BEFORE intent creation — no intent residue, no raw
    OperationalError."""
    import dataclasses
    import os

    _apply_genesis(world)
    good_preview = plan_declaration_update(
        world["vertex"], proposed_text=world["edit"]
    )
    canonical = _chmod_canonical_readonly(world)
    if os.access(canonical, os.W_OK):
        pytest.skip("cannot make file read-only here (running as root?)")
    try:
        forced = dataclasses.replace(good_preview, applicable=True)
        result = apply_declaration_update(
            forced, observer="obs", credentials=Creds()
        )
        assert result.status == "refused"
        assert "not writable" in result.reason
        assert not intent_path_for(world["vertex"]).exists()
    finally:
        canonical.chmod(0o644)


# --- intent record shape ----------------------------------------------------


def test_intent_is_a_discoverable_sibling_with_pinned_fields(world):
    _apply_genesis(world)
    preview = plan_declaration_update(world["vertex"], proposed_text=world["edit"])
    result = apply_declaration_update(
        preview, observer="obs", credentials=Creds(), write_file=_boom
    )
    intent = result.intent_path
    assert intent == world["vertex"].parent / "x.vertex.intent"
    record = json.loads(intent.read_text(encoding="utf-8"))
    for key in (
        "v", "mode", "vertex_path", "canonical_path", "old_decl_head",
        "old_store_fingerprint", "proposed_fingerprint",
        "proposed_documents", "proposed_text",
    ):
        assert key in record
    assert record["mode"] == "edit"
    assert record["old_decl_head"] == list(preview.expected_head)
    recover_declaration_update(intent)  # leave the world clean
