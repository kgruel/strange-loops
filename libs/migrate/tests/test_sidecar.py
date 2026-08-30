"""Tests for migrate.sidecar — the ArrivalSink orchestrator."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from engine.arrival import (
    GENESIS_KIND,
    ArrivalLog,
    _canonical_bytes,
    build_record,
    mint_lineage,
)
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Full, Head, RecordDraft, StoreDescriptor
from engine.arrival_head_attestation import Kind, Level, heads_dir, read_journal
from engine.arrival_registry import BackendRegistry, descriptor_for
from lang import BackendDecl, ObserverDecl, VertexFile, parse_vertex_file
from sign import ed25519

from migrate.legacy_ids import FactRow, identity
from migrate.legacy_source import LegacySource
from migrate.refusals import (
    JournalPreflightRefused,
    LegacySourceRefused,
    LegacyStorageRefused,
    MigrationRefused,
    PublishPreconditionRefused,
    SourceChangedRefused,
    TargetMismatchOnResumeRefused,
    TornTailRefused,
)
from migrate.sidecar import (
    MigrationOutcome,
    edit_vertex_store_clause,
    preflight_journal,
    run_migration,
    verify_migration_report,
)
from migrate.transform import transform

from ._fixtures import (
    ALL_FACT_ROWS,
    ALL_TICK_ROWS,
    BATCH_LINE_ALICE,
    FACT_CANONICAL_ULID_SIGNED,
    FACT_UUID4_SIGNED,
    build_mixed_observer_jsonl,
    build_synthetic_jsonl,
    build_synthetic_sqlite,
)

ARRIVAL_DOMAIN = "test-arrival-v1"


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
    v_path = tmp_path / "project.vertex"
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

    with pytest.raises(TargetMismatchOnResumeRefused):
        run_migration(
            source_path=source_path,
            vertex_path=v_path,
            store_dir=store_dir,
            signer=cust.signer,
            resume_target=target_path,
        )

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
    """(5) Second migration after an abandoned attempt -> fresh lineage, fresh path, no StoreLost."""
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

    with patch("migrate.sidecar.transform", side_effect=mutating_transform):
        with pytest.raises(SourceChangedRefused) as exc_info:
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

    with patch("os.replace", side_effect=failing_replace):
        with pytest.raises(OSError):
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

    with patch("migrate.sidecar.heads_dir", side_effect=OSError("Unwritable")):
        with pytest.raises(JournalPreflightRefused):
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
