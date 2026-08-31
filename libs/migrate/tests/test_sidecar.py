"""Tests for migrate.sidecar — the ArrivalSink orchestrator."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from custody.signing import ARRIVAL_DOMAIN
from engine.arrival import (
    ArrivalLog,
    ArrivalTornTail,
    _canonical_bytes,
    build_record,
    mint_lineage,
)
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Full, Head, RecordDraft, StoreDescriptor
from engine.arrival_head_attestation import Kind, Level, read_journal
from engine.arrival_head_seam import StoreLost
from engine.arrival_registry import BackendRegistry, descriptor_for
from lang import BackendDecl, parse_vertex, parse_vertex_file
from sign import ed25519

from migrate.legacy_ids import FactRow, Transform, ulid_migration
from migrate.refusals import (
    JournalPreflightRefused,
    LegacySourceRefused,
    LegacyStorageRefused,
    PublishPreconditionRefused,
    ReportBadSignatureRefused,
    ReportHeadMismatchRefused,
    ReportMalformedRefused,
    ReportMissingTargetRefused,
    ReportTargetUnopenableRefused,
    SourceChangedRefused,
    TargetMismatchOnResumeRefused,
    TargetUnopenable,
    TornTailRefused,
)
from migrate.sidecar import (
    edit_vertex_store_clause,
    run_migration,
    verify_migration_report,
)
from migrate.transform import transform

from ._fixtures import (
    FACT_UUID4_SIGNED,
    build_mixed_observer_jsonl,
    build_synthetic_jsonl,
    build_synthetic_sqlite,
)


class CustodianFixture:
    """One observer's real Ed25519 keypair plus injected signer/verifier."""

    def __init__(self, tmp_path: Path, name: str) -> None:
        self.name = name
        self.keypair = ed25519.load_or_generate(tmp_path / "keys" / name)
        self.public = self.keypair.public_b64

    def signer(self, observer: str, digest: str) -> str | None:
        return ed25519.sign(self.keypair, digest.encode(), domain=ARRIVAL_DOMAIN)

    def verify(self, key_b64: str, signature: str, digest: str) -> bool:
        try:
            pub = ed25519.public_key_from_b64(key_b64)
        except ValueError:
            return False
        return ed25519.verify(pub, signature, digest.encode(), domain=ARRIVAL_DOMAIN)


def _make_vertex_file(
    tmp_path: Path,
    custodian_name: str,
    custodian_key: str,
    other_observers: list[tuple[str, str | None]],
    store_rel_path: str = "./data/legacy.jsonl",
) -> Path:
    """Create a valid .vertex file on disk."""
    v_path = tmp_path / f"{custodian_name}.vertex"
    obs_lines = [
        f'  {custodian_name} {{\n    key "{custodian_key}"\n  }}',
    ]
    for name, key in other_observers:
        if key is not None:
            obs_lines.append(f'  {name} {{\n    key "{key}"\n  }}')
        else:
            obs_lines.append(f"  {name} {{ }}")

    obs_block = "\n".join(obs_lines)
    content = f"""name "{custodian_name}"
store "{store_rel_path}"

observers {{
{obs_block}
}}

loops {{
  concept {{ fold {{ items "collect" 100 }} }}
  claim {{ fold {{ items "collect" 100 }} }}
  event {{ fold {{ items "collect" 100 }} }}
}}
"""
    v_path.write_text(content, encoding="utf-8")
    return v_path


# ---------------------------------------------------------------------------
# Test 1: Full round-trip on synthetic legacy stores (both JSONL and SQLite arms)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_format", ["jsonl", "sqlite"])
def test_full_roundtrip_synthetic_store(tmp_path: Path, source_format: str) -> None:
    """(1) Full round-trip: inventory equality, signature preservation, Full verify,

    journal first entry is bootstrap/MINT, descriptor updated, report verifies.
    """
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)

    cust = CustodianFixture(tmp_path, "alice")
    bob_key = ed25519.load_or_generate(tmp_path / "keys" / "bob").public_b64
    carol_key = ed25519.load_or_generate(tmp_path / "keys" / "carol").public_b64

    if source_format == "jsonl":
        source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    else:
        source_path = build_synthetic_sqlite(store_dir / "legacy.db")

    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[("bob", bob_key), ("carol", carol_key)],
        store_rel_path=f"./data/{source_path.name}",
    )

    outcome = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
    )

    # 1. Target and report exist
    assert outcome.target_path.exists()
    assert outcome.report_path.exists()
    assert outcome.target_path.name == f"{outcome.lineage}.arrival"
    assert outcome.report_path.name == f"{outcome.lineage}.migration-report.json"

    # 2. Target verifies Full internally
    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(outcome.target_path))
    ledger, _ = registry.open(desc)
    verified_head = ledger.verify(Full(through=outcome.head))
    assert verified_head == outcome.head

    # 3. Journal first entry is bootstrap/MINT (§E gap 1)
    j_read = read_journal(outcome.lineage)
    assert len(j_read.entries) >= 1
    assert j_read.entries[0].kind == Kind.BOOTSTRAP
    assert j_read.entries[0].level == Level.MINT
    assert j_read.bootstrap == j_read.entries[0]

    # 4. Report verifies signature and matches target head claim (§I.1)
    assert verify_migration_report(
        report_path=outcome.report_path,
        public_key=cust.public,
        verify=cust.verify,
        target_path=outcome.target_path,
    )

    # 5. Authored inner signatures are preserved byte-for-byte (§I.2)
    records = list(ledger.scan(through=outcome.head))
    signed_facts = [
        r["body"]
        for r in records
        if r.get("k") == "fact" and r["body"].get("signature") is not None
    ]
    # Check that FACT_UUID4_SIGNED and FACT_CANONICAL_ULID_SIGNED kept their signatures
    assert any(f.get("signature") == "sig-alice-1" for f in signed_facts)
    assert any(f.get("signature") == "sig-alice-4" for f in signed_facts)

    # 6. Descriptor updated atomically with verification-by-re-parse (§H)
    post_ast = parse_vertex_file(v_path)
    assert post_ast.store_backend == BackendDecl(name="file")
    resolved_desc = descriptor_for(post_ast, v_path)
    assert resolved_desc is not None
    assert resolved_desc.backend == "file"
    assert Path(resolved_desc.location).resolve() == outcome.target_path.resolve()

    # 7. Legacy store is never mutated and never deleted (§Contract ruling 9)
    assert source_path.exists()


# ---------------------------------------------------------------------------
# Test 2: Kill-mid-append restart byte-identity gate (§I.4)
# ---------------------------------------------------------------------------


def test_kill_mid_append_restart_byte_identical(tmp_path: Path) -> None:
    """(2) Kill-mid-append restart: append N/2 drafts, abandon, re-run with

    resume_target= -> final target BYTE-IDENTICAL to uninterrupted run (§I.4).
    """
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    bob_key = ed25519.load_or_generate(tmp_path / "keys" / "bob").public_b64
    carol_key = ed25519.load_or_generate(tmp_path / "keys" / "carol").public_b64

    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[("bob", bob_key), ("carol", carol_key)],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    interrupted_target = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(interrupted_target), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    # Append half the drafts
    half = len(t_res.drafts) // 2
    records = []
    prev_rh = genesis_head.record_hash
    for i, d in enumerate(t_res.drafts[:half]):
        rec = build_record(
            lin=lineage,
            ordinal=genesis_head.ordinal + 1 + i,
            prev=prev_rh,
            k=d.kind,
            body=dict(d.body),
            observer=d.observer,
            origin=d.origin,
            at=d.authored_at,
            sig=d.signature,
        )
        records.append(rec)
        prev_rh = rec["rh"]
    ledger.replicate(expected=genesis_head, records=records)

    # Now resume with run_migration(..., resume_target=interrupted_target)
    outcome_resumed = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
        resume_target=interrupted_target,
    )

    # Generate reference uninterrupted file with identical lineage and drafts
    ref_path = tmp_path / "reference.arrival"
    ref_log = ArrivalLog.mint(
        ref_path,
        lineage=lineage,
        observer=cust.name,
        key=cust.public,
        signer=cust.signer,
        at=0.0,
    )
    gen_head = Head(lineage=lineage, ordinal=0, record_hash=ref_log.genesis()["rh"])
    ref_records = []
    prev_rh = gen_head.record_hash
    for i, d in enumerate(t_res.drafts):
        rec = build_record(
            lin=lineage,
            ordinal=gen_head.ordinal + 1 + i,
            prev=prev_rh,
            k=d.kind,
            body=dict(d.body),
            observer=d.observer,
            origin=d.origin,
            at=d.authored_at,
            sig=d.signature,
        )
        ref_records.append(rec)
        prev_rh = rec["rh"]
    ref_log.append_records(ref_records, following=gen_head)

    assert outcome_resumed.target_path.read_bytes() == ref_path.read_bytes(), (
        "Final target MUST be byte-identical to uninterrupted run"
    )


# ---------------------------------------------------------------------------
# Test 3: Resume against tampered target refuses with no repair (F2 gate)
# ---------------------------------------------------------------------------


def test_resume_against_tampered_target_refuses_no_repair(tmp_path: Path) -> None:
    """(3) Resume against tampered target -> typed refusal, target bytes unchanged (F2)."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )
    records = []
    prev_rh = genesis_head.record_hash
    for i, d in enumerate(t_res.drafts[:3]):
        rec = build_record(
            lin=lineage,
            ordinal=genesis_head.ordinal + 1 + i,
            prev=prev_rh,
            k=d.kind,
            body=dict(d.body),
            observer=d.observer,
            origin=d.origin,
            at=d.authored_at,
            sig=d.signature,
        )
        records.append(rec)
        prev_rh = rec["rh"]
    ledger.replicate(expected=genesis_head, records=records)

    # Tamper with an appended record: flip bytes inside the file (e.g. at byte offset 200)
    orig_bytes = bytearray(target_path.read_bytes())
    # Modify payload text inside the record
    tampered_bytes = bytearray(orig_bytes)
    tampered_bytes[len(tampered_bytes) - 50] ^= 0x01
    target_path.write_bytes(tampered_bytes)
    recorded_tampered_bytes = target_path.read_bytes()

    with pytest.raises(TargetUnopenable) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    assert isinstance(exc_info.value.cause, StoreLost)
    assert exc_info.value.target_path == str(target_path)

    # F2: Verification never repairs — target bytes MUST remain unchanged
    assert target_path.read_bytes() == recorded_tampered_bytes


# ---------------------------------------------------------------------------
# Test 4: Torn tail target refuses with typed refusal, no repair (§D.3)
# ---------------------------------------------------------------------------


def test_torn_tail_target_refuses_no_repair(tmp_path: Path) -> None:
    """(4) Torn tail target -> typed refusal TornTailRefused, bytes unchanged."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )
    records = []
    prev_rh = genesis_head.record_hash
    for i, d in enumerate(t_res.drafts[:3]):
        rec = build_record(
            lin=lineage,
            ordinal=genesis_head.ordinal + 1 + i,
            prev=prev_rh,
            k=d.kind,
            body=dict(d.body),
            observer=d.observer,
            origin=d.origin,
            at=d.authored_at,
            sig=d.signature,
        )
        records.append(rec)
        prev_rh = rec["rh"]
    ledger.replicate(expected=genesis_head, records=records)

    # Truncate mid-record: remove last 15 bytes (leaving unterminated record)
    full_bytes = target_path.read_bytes()
    torn_bytes = full_bytes[:-15]
    target_path.write_bytes(torn_bytes)

    with pytest.raises(TornTailRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    assert "ends mid-record" in str(exc_info.value)
    # F2: No repair — bytes must be untouched
    assert target_path.read_bytes() == torn_bytes


# ---------------------------------------------------------------------------
# Test 5: Second migration after abandoned attempt -> fresh lineage, no StoreLost
# ---------------------------------------------------------------------------


def test_second_migration_after_abandoned_attempt(tmp_path: Path) -> None:
    """(5) Second migration after an abandoned attempt -> fresh lineage, no StoreLost."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    # First attempt: partially mint and abandon
    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    first_lineage = mint_lineage()
    first_path = store_dir / f"{first_lineage}.arrival"
    registry = BackendRegistry.with_builtin_backends()
    desc1 = StoreDescriptor(backend="file", location=str(first_path), lineage=first_lineage)
    ledger1, _ = registry.open(desc1)
    ledger1.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": first_lineage,
            "at": 0.0,
        }
    )
    # Abandon first attempt here

    # Second fresh attempt (resume_target=None)
    outcome2 = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
    )

    assert outcome2.lineage != first_lineage
    assert outcome2.target_path.exists()
    assert first_path.exists()  # Abandoned attempt remains as read-only evidence


# ---------------------------------------------------------------------------
# Test 6: Source mutated during staging -> publish refused, descriptor unchanged
# ---------------------------------------------------------------------------


def test_source_mutated_during_staging_refuses_publish(tmp_path: Path) -> None:
    """(6) Source mutated during staging -> publish refused with SourceChangedRefused."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )
    pre_vertex_text = v_path.read_text(encoding="utf-8")

    # Hook during transform to mutate the source file after initial inventory
    original_transform = transform

    def mutating_transform(*args, **kwargs):
        res = original_transform(*args, **kwargs)
        # Mutate source by appending a new fact line
        extra_line = json.dumps(
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5F99",
                "kind": "concept",
                "ts": 2000.0,
                "observer": "alice",
                "origin": "origin",
                "payload": '{"text":"concurrent write"}',
            }
        )
        with source_path.open("a", encoding="utf-8") as f:
            f.write(extra_line + "\n")
        return res

    with (
        patch("migrate.sidecar.transform", side_effect=mutating_transform),
        pytest.raises(SourceChangedRefused) as exc_info,
    ):
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
        )

    assert "two histories, not a migration" in str(exc_info.value)
    # Descriptor MUST remain unchanged
    assert v_path.read_text(encoding="utf-8") == pre_vertex_text


# ---------------------------------------------------------------------------
# Test 7: Publish atomicity and verification-by-re-parse (§H)
# ---------------------------------------------------------------------------


def test_publish_atomicity_and_crash_simulation(tmp_path: Path) -> None:
    """(7) Publish atomicity: pre-edit parse equals post-edit parse in every

    non-store field; crash during replace leaves old descriptor intact.
    """
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )
    pre_ast = parse_vertex_file(v_path)
    pre_text = v_path.read_text(encoding="utf-8")

    # Simulate crash right before replacing .vertex
    orig_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if str(dst).endswith(".vertex"):
            raise OSError("Simulated crash between write and replace")
        return orig_replace(src, dst, *args, **kwargs)

    with patch("os.replace", side_effect=failing_replace), pytest.raises(OSError):
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
        )

    # Old descriptor remains completely intact
    assert v_path.read_text(encoding="utf-8") == pre_text
    post_ast = parse_vertex_file(v_path)
    assert post_ast.name == pre_ast.name
    assert post_ast.loops == pre_ast.loops
    assert post_ast.store == pre_ast.store


# ---------------------------------------------------------------------------
# Test 8: Refused inventory creates NO target path (WP1 gate re-checked)
# ---------------------------------------------------------------------------


def test_refused_inventory_creates_no_target(tmp_path: Path) -> None:
    """(8) Refused inventory (e.g. mixed-observer batch) creates NO target path."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    mixed_source = build_mixed_observer_jsonl(store_dir / "mixed.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    with pytest.raises(LegacySourceRefused):
        run_migration(
            source_path=mixed_source,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
        )

    # Assert NO .arrival target file exists in store_dir
    arrival_files = list(store_dir.glob("*.arrival"))
    assert arrival_files == [], "Refused migration must create no target file"


# ---------------------------------------------------------------------------
# Test 9: Journal pre-flight failure refuses before target creation (§D.3)
# ---------------------------------------------------------------------------


def test_journal_preflight_failure_refuses(tmp_path: Path) -> None:
    """Journal preflight failure raises JournalPreflightRefused before target creation."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    def failing_probe(path: Path):
        raise OSError("Permission denied: simulated unwritable state root")

    with (
        patch("migrate.sidecar.heads_dir", side_effect=OSError("Unwritable")),
        pytest.raises(JournalPreflightRefused),
    ):
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
        )

    arrival_files = list(store_dir.glob("*.arrival"))
    assert arrival_files == [], "Preflight failure must create no target file"


# ---------------------------------------------------------------------------
# Test 10: Legacy storage operational error wrapped into LegacyStorageRefused
# ---------------------------------------------------------------------------


def test_legacy_storage_operational_error_wrapped(tmp_path: Path) -> None:
    """Storage-level sqlite3 errors are wrapped into typed LegacyStorageRefused."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")

    # Create a broken SQLite store (table exists but lacks required columns)
    db_path = store_dir / "broken.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE facts (id TEXT PRIMARY KEY)")
    conn.execute("INSERT INTO facts VALUES ('01ARZ3NDEKTSV4RRFFQ69G5FA1')")
    conn.commit()
    conn.close()

    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    with pytest.raises(LegacyStorageRefused):
        run_migration(
            source_path=db_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
        )


# ---------------------------------------------------------------------------
# Test 11: F5 — The F2-resume-diff ratchet: valid chain with divergent content
# ---------------------------------------------------------------------------


def test_resume_against_divergent_valid_chain_refuses_target_mismatch(tmp_path: Path) -> None:
    """F5: Target with valid chain whose content diverges at ordinal 3
    -> TargetMismatchOnResumeRefused(ordinal=3)."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    # Append valid drafts 1 and 2 matching source
    ledger.append(genesis_head, t_res.drafts[:2])
    head_ord2 = ledger.head()

    # Append ordinal 3 with divergent content
    divergent_draft = RecordDraft(
        kind="fact",
        authored_at=9999.0,
        observer="alice",
        origin="",
        body=body_of_fact_row(
            (
                FACT_UUID4_SIGNED["id"],
                "concept",
                9999.0,
                "alice",
                "",
                '{"divergent": "payload"}',
                None,
            )
        ),
        signature=None,
    )
    ledger.append(head_ord2, [divergent_draft])
    target_bytes_before = target_path.read_bytes()

    with pytest.raises(TargetMismatchOnResumeRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    assert exc_info.value.ordinal == 3
    assert exc_info.value.target_path == str(target_path)
    assert target_path.read_bytes() == target_bytes_before


def test_resume_refuses_when_target_record_differs_only_in_signature(tmp_path: Path) -> None:
    """F2: A resume target whose record differs ONLY in signature
    raises TargetMismatchOnResumeRefused."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    exp_draft = t_res.drafts[0]
    assert exp_draft.signature is None  # expected-unsigned

    # Construct an outer-signed version of the EXACT same draft
    outer_signed_draft = RecordDraft(
        kind=exp_draft.kind,
        authored_at=exp_draft.authored_at,
        observer=exp_draft.observer,
        origin=exp_draft.origin,
        body=exp_draft.body,
        signature="fake-outer-signature-bytes",
    )
    ledger.append(genesis_head, [outer_signed_draft])

    with pytest.raises(TargetMismatchOnResumeRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    assert exc_info.value.ordinal == 1
    assert exc_info.value.target_path == str(target_path)


def test_resume_refuses_when_target_record_differs_only_in_authored_at(
    tmp_path: Path,
) -> None:
    """F2: A resume target whose record differs ONLY in authored_at
    raises TargetMismatchOnResumeRefused."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    genesis_head = ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    exp_draft = t_res.drafts[0]
    divergent_at_draft = RecordDraft(
        kind=exp_draft.kind,
        authored_at=exp_draft.authored_at + 123.456,
        observer=exp_draft.observer,
        origin=exp_draft.origin,
        body=exp_draft.body,
        signature=exp_draft.signature,
    )
    ledger.append(genesis_head, [divergent_at_draft])

    with pytest.raises(TargetMismatchOnResumeRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    assert exc_info.value.ordinal == 1
    assert exc_info.value.target_path == str(target_path)


def test_resume_refuses_when_target_filename_does_not_match_lineage(tmp_path: Path) -> None:
    """F3: Resuming against a target whose filename is not <genesis-lineage>.arrival
    (e.g. friendly-name target like 'friendly.arrival') raises TargetMismatchOnResumeRefused
    naming both filename and lineage."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    t_res = transform(source_path, parse_vertex_file(v_path), signer=cust.signer)
    lineage = mint_lineage()
    target_path = store_dir / "friendly.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    ledger.mint(
        {
            "observer": t_res.genesis.custodian,
            "signer": cust.signer,
            "key": t_res.genesis.key,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    with pytest.raises(TargetMismatchOnResumeRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

    msg = str(exc_info.value)
    assert "friendly.arrival" in msg
    assert lineage in msg
    assert exc_info.value.target_path == str(target_path)


# ---------------------------------------------------------------------------
# Test 12: F3 — Mallory foreign genesis rejected on resume
# ---------------------------------------------------------------------------


def test_resume_against_mallory_foreign_genesis_refuses(tmp_path: Path) -> None:
    """F3: Target with foreign genesis (observer/key != custodian)
    -> TargetMismatchOnResumeRefused(ordinal=0)."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    alice = CustodianFixture(tmp_path, "alice")
    mallory = CustodianFixture(tmp_path, "mallory")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=alice.name,
        custodian_key=alice.public,
        other_observers=[],
    )

    lineage = mint_lineage()
    target_path = store_dir / f"{lineage}.arrival"

    registry = BackendRegistry.with_builtin_backends()
    desc = StoreDescriptor(backend="file", location=str(target_path), lineage=lineage)
    ledger, _ = registry.open(desc)
    # Mallory mints the target instead of Alice
    ledger.mint(
        {
            "observer": mallory.name,
            "signer": mallory.signer,
            "key": mallory.public,
            "lineage": lineage,
            "at": 0.0,
        }
    )

    with pytest.raises(TargetMismatchOnResumeRefused) as exc_info:
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=alice.signer,
            resume_target=target_path,
        )

    assert exc_info.value.ordinal == 0
    assert (
        "genesis custodian 'mallory' does not match" in str(exc_info.value)
        or "genesis public key" in str(exc_info.value)
    )


# ---------------------------------------------------------------------------
# Test 13: F2 — Precondition refusals in edit_vertex_store_clause
# ---------------------------------------------------------------------------


def test_edit_vertex_store_clause_ambiguity_and_syntax_refusals(tmp_path: Path) -> None:
    """F2: edit_vertex_store_clause refuses ambiguous, commented, or duplicate store clauses."""
    loops_block = 'loops { concept { fold { items "collect" 100 } } }'
    # (a) Duplicate store nodes
    v_dup = tmp_path / "dup.vertex"
    v_dup.write_text(
        f'name "alice"\nstore "./data/a.jsonl"\nstore "./data/b.jsonl"\n{loops_block}\n',
        encoding="utf-8",
    )
    with pytest.raises(PublishPreconditionRefused) as exc_info:
        edit_vertex_store_clause(v_dup, "./data/target.arrival")
    assert exc_info.value.condition == "vertex_store_duplicate_nodes"

    # (b) Store inside block comment
    v_comment = tmp_path / "comment.vertex"
    v_comment.write_text(
        f'name "alice"\n/*\nstore "./data/legacy.jsonl"\n*/\n{loops_block}\n',
        encoding="utf-8",
    )
    with pytest.raises(PublishPreconditionRefused) as exc_info:
        edit_vertex_store_clause(v_comment, "./data/target.arrival")
    assert exc_info.value.condition == "vertex_store_ineffective"


def test_edit_vertex_store_clause_comment_shadowed_active_store(tmp_path: Path) -> None:
    """Comment-shadowed store clause: effective store is edited, commented one preserved."""
    loops_block = 'loops { concept { fold { items "collect" 100 } } }'
    v_shadow = tmp_path / "shadow.vertex"
    v_shadow.write_text(
        f'name "alice"\n/*\nstore "./data/legacy.jsonl"\n*/\n'
        f'store "./data/active.jsonl"\n{loops_block}\n',
        encoding="utf-8",
    )
    edit_vertex_store_clause(v_shadow, "./data/target.arrival", backend="file")
    text = v_shadow.read_text(encoding="utf-8")
    assert 'store "./data/legacy.jsonl"' in text
    assert 'store "./data/target.arrival" backend="file"' in text
    post_ast = parse_vertex(text, v_shadow)
    assert post_ast.store == Path("./data/target.arrival")
    assert post_ast.store_backend == BackendDecl(name="file")


def test_edit_vertex_store_clause_preserves_same_line_comments(tmp_path: Path) -> None:
    """F5: Same-line comments trailing the store clause (e.g. store "./a.jsonl" // KEEP)
    survive the surgical edit byte-for-byte."""
    loops_block = 'loops { concept { fold { items "collect" 100 } } }'
    v_comment = tmp_path / "keep.vertex"
    v_comment.write_text(
        f'name "alice"\nstore "./data/a.jsonl" // KEEP\n{loops_block}\n',
        encoding="utf-8",
    )
    edit_vertex_store_clause(v_comment, "./data/target.arrival", backend="file")
    text = v_comment.read_text(encoding="utf-8")
    assert 'store "./data/target.arrival" backend="file" // KEEP' in text
    post_ast = parse_vertex(text, v_comment)
    assert post_ast.store == Path("./data/target.arrival")
    assert post_ast.store_backend == BackendDecl(name="file")


# ---------------------------------------------------------------------------
# Test 14: F7(b) — verify_migration_report causes
# ---------------------------------------------------------------------------


def test_verify_migration_report_causes(tmp_path: Path) -> None:
    """F7(b): verify_migration_report discriminates causes with typed refusals."""
    import hashlib

    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[],
    )

    outcome = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
    )

    # 1. Valid report passes
    assert verify_migration_report(
        outcome.report_path,
        cust.public,
        verify=cust.verify,
        target_path=outcome.target_path,
    )

    # 2. Bad signature -> ReportBadSignatureRefused
    mallory = CustodianFixture(tmp_path, "mallory")
    with pytest.raises(ReportBadSignatureRefused):
        verify_migration_report(
            outcome.report_path,
            mallory.public,
            verify=mallory.verify,
            target_path=outcome.target_path,
        )

    # 3. Unknown top-level key -> ReportMalformedRefused
    doc = json.loads(outcome.report_path.read_text(encoding="utf-8"))
    doc["extra_top_level_key"] = "forbidden"
    bad_report = tmp_path / "bad_keys.json"
    bad_report.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ReportMalformedRefused):
        verify_migration_report(
            bad_report,
            cust.public,
            verify=cust.verify,
            target_path=outcome.target_path,
        )

    # 4. Missing target -> ReportMissingTargetRefused
    with pytest.raises(ReportMissingTargetRefused):
        verify_migration_report(
            outcome.report_path,
            cust.public,
            verify=cust.verify,
            target_path=tmp_path / "nonexistent.arrival",
        )

    # 5. Head mismatch -> ReportHeadMismatchRefused
    doc = json.loads(outcome.report_path.read_text(encoding="utf-8"))
    doc["body"]["target_head"]["ordinal"] = 99999
    # Re-sign the tampered doc
    signed_dict = {k: v for k, v in doc.items() if k != "signature"}
    digest = hashlib.sha256(_canonical_bytes(signed_dict)).hexdigest()
    sig = cust.signer("alice", digest)
    doc["signature"] = sig
    mismatched_report = tmp_path / "mismatch.json"
    mismatched_report.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ReportHeadMismatchRefused):
        verify_migration_report(
            mismatched_report,
            cust.public,
            verify=cust.verify,
            target_path=outcome.target_path,
        )

    # 6. Target unopenable (torn-tail target) -> ReportTargetUnopenableRefused
    full_bytes = outcome.target_path.read_bytes()
    try:
        outcome.target_path.write_bytes(full_bytes + b'{"incomplete": "record"')
        with pytest.raises(ReportTargetUnopenableRefused) as exc_info:
            verify_migration_report(
                outcome.report_path,
                cust.public,
                verify=cust.verify,
                target_path=outcome.target_path,
            )
        assert not isinstance(exc_info.value, ReportHeadMismatchRefused)
        assert exc_info.value.cause is not None
        assert isinstance(exc_info.value.cause, (StoreLost, ArrivalTornTail))
        assert isinstance(exc_info.value.__cause__, (StoreLost, ArrivalTornTail))
    finally:
        outcome.target_path.write_bytes(full_bytes)


# ---------------------------------------------------------------------------
# Test 15: F7(d) — Dropped units and ulid_migration() inventory equality
# ---------------------------------------------------------------------------


def test_migration_with_dropped_units_and_ulid_migration(tmp_path: Path) -> None:
    """F7(d): Migration succeeds with dropped units and with ulid_migration() rule."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "alice")
    bob_key = ed25519.load_or_generate(tmp_path / "keys" / "bob").public_b64
    carol_key = ed25519.load_or_generate(tmp_path / "keys" / "carol").public_b64

    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[("bob", bob_key), ("carol", carol_key)],
    )

    # 1. Whole-unit-dropping rule
    def drop_first_fact(row: FactRow) -> FactRow | None:
        if row.id == FACT_UUID4_SIGNED["id"]:
            return None
        return row

    drop_rule = Transform(rule="drop-first-fact", map_fact=drop_first_fact)
    outcome_drop = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
        transform_rule=drop_rule,
    )
    assert len(outcome_drop.exceptions.dropped_units) == 1
    assert outcome_drop.exceptions.dropped_units[0].fact_kinds == ("concept",)
    assert verify_migration_report(
        outcome_drop.report_path,
        cust.public,
        verify=cust.verify,
        target_path=outcome_drop.target_path,
    )

    # 2. ulid_migration() rule
    v_path2 = _make_vertex_file(
        tmp_path,
        custodian_name=cust.name,
        custodian_key=cust.public,
        other_observers=[("bob", bob_key), ("carol", carol_key)],
    )
    outcome_ulid = run_migration(
        source_path=source_path,
        vertex_path=v_path2,
        store_dir=store_dir,
        signer=cust.signer,
        transform_rule=ulid_migration(),
    )
    assert outcome_ulid.target_path.exists()
    assert verify_migration_report(
        outcome_ulid.report_path,
        cust.public,
        verify=cust.verify,
        target_path=outcome_ulid.target_path,
    )


def test_migration_with_display_name_differing_from_stem(tmp_path: Path) -> None:
    """F4: run_migration on a vertex whose declared name differs from filename stem
    derives custodian from stem and migrates successfully."""
    store_dir = tmp_path / "data"
    store_dir.mkdir(parents=True, exist_ok=True)
    cust = CustodianFixture(tmp_path, "kyle")
    source_path = build_synthetic_jsonl(store_dir / "legacy.jsonl")
    v_path = tmp_path / "kyle.vertex"
    v_content = f"""name "Display Name Project"
store "./data/legacy.jsonl"

observers {{
  kyle {{
    key "{cust.public}"
  }}
}}

loops {{
  concept {{ fold {{ items "collect" 100 }} }}
}}
"""
    v_path.write_text(v_content, encoding="utf-8")

    outcome = run_migration(
        source_path=source_path,
        vertex_path=v_path,
        store_dir=store_dir,
        signer=cust.signer,
    )
    assert outcome.target_path.exists()
    assert outcome.report_path.exists()
    assert verify_migration_report(
        outcome.report_path,
        cust.public,
        verify=cust.verify,
        target_path=outcome.target_path,
    )
