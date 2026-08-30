"""Migration sidecar sink: staging, restart, verification, publish.

Contract & Architectural Discipline
-----------------------------------
1. Ordinary contract path only: The target opens through :class:`engine.arrival_registry.BackendRegistry`
   on a staging descriptor; drafts append through the registry-wrapped
   :class:`engine.arrival_head_seam.AttestedLedger`. No privileged path, no direct
   :class:`engine.arrival.ArrivalLog` writes, no reaching around the seam.

2. First touch is mint() through the wrapper: Never open-then-mint, never a direct
   bootstrap() call. Minting writes the bootstrap journal entry at Level.MINT.
   The journal side is pre-flighted FIRST (§D.3): resolve state root, create heads/
   if absent, write-and-remove a probe entry — eliminating common NotWitnessed
   causes while failure is still free. The residual (disk fills between probe and genesis)
   is named, not detected.

3. Staging path is LINEAGE-NAMED (ratified M-2): `<store-dir>/<lineage>.arrival` where
   `<lineage>` is the freshly minted lineage id. A fresh attempt mints a fresh lineage at a
   fresh path (PRE_GENESIS branch; no binding, no journal). No rename at cutover — the
   descriptor names the staging path directly. An abandoned attempt stays as read-only
   evidence. The sidecar NEVER runs trust-reset, never clears a binding, never touches the
   abandoned-epoch fence (interim law refuse-and-re-decree;
   design:arrival-reset-descendant-acceptance is open at Kyle's slice-6 gate).

4. Resume is DERIVED, never stored (§D.1): On restart, open the target through the
   registry, take the seam-vouched head, re-run LegacySource+Transformer from the start,
   diff the expected prefix against the target's scan through the head — any mismatch is a
   typed REFUSAL, never a repair (F2: verification-never-repairs). Resume appending at the
   first expected record beyond the head. No cursor file, no sidecar-side state.

5. Torn-tail target -> typed refusal, no repair (§D.3): truncate_torn_tail stays
   unreachable through the wrapper; the refusal names target and condition with out-of-band
   recovery as advisory prose only (content-vs-storage discipline).

6. Verification = BOTH gates (§I.2): verify(Full(through=head)) on the target (internal
   consistency) AND the equivalence re-run (re-derive expected rows from the unmodified
   source, compare row by row over logical row fields `(kind, ts, observer, origin, payload_text, signature)`
   with transform id mapping; framing/ordinals excluded). Both run; the report carries both.

7. Atomic descriptor publish (§H): Surgical `.vertex` store-clause edit, then re-parse and
   assert: parses, names the new location and backend, and every other parsed field equals
   the pre-edit parse (verification-by-re-parse). Write temp file in the same directory,
   fsync, os.replace. Publish REFUSED unless all five preconditions hold (§H.2):
   - Target verifies Full;
   - Equivalence re-run matches;
   - Journal's FIRST entry for lineage is bootstrap/MINT;
   - Inventory equality (per-kind counts, tick count, observer census; record counts excluded);
   - Source content hash unchanged since snapshot (two histories, not a migration).

8. The migration report (§I.1, ratified M-3): `<lineage>.migration-report.json` beside
   the target, signed by the custodian, referenced by nothing in the ledger.
   Signing covers the canonical JSON bytes (RFC 8785 JCS) of the report body dictionary:
   `canonical_bytes = _canonical_bytes(report_body)`
   `digest = sha256(canonical_bytes).hexdigest()`
   `sig = signer(custodian, digest)`
   Report file format:
   `{"body": report_body, "signature": sig, "signer": custodian}`

9. Legacy store is never mutated and never deleted: Remains read-only archival evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import rfc8785
from engine.arrival import (
    GENESIS_KIND,
    KEY_INTRODUCTION_KIND,
    ArrivalCorrupt,
    ArrivalError,
    Signer,
    Verify,
    _canonical_bytes,
    build_record,
    mint_lineage,
)
from engine.arrival_body import (
    BATCH_KIND,
    FACT_KIND,
    TICK_KIND,
    rows_of_body,
)
from engine.arrival_contract import (
    Full,
    Head,
    RecordDraft,
    StoreDescriptor,
)
from engine.arrival_head_attestation import (
    Kind,
    Level,
    heads_dir,
    read_journal,
    state_root,
)
from engine.arrival_head_seam import StoreLost
from engine.arrival_registry import BackendRegistry, descriptor_for
from lang import BackendDecl, VertexFile, parse_vertex, parse_vertex_file

from .inventory import SourceInventory, inventory
from .legacy_ids import FactRow, Transform, identity
from .legacy_source import BatchUnit, FlatFactUnit, LegacySource, TickUnit
from .refusals import (
    JournalPreflightRefused,
    LegacyStorageRefused,
    MigrationRefused,
    PublishPreconditionRefused,
    SourceChangedRefused,
    TargetMismatchOnResumeRefused,
    TornTailRefused,
)
from .transform import (
    DroppedUnit,
    GenesisRequirements,
    TransformExceptions,
    TransformResult,
    coerce_vertex,
    transform,
)

__all__ = [
    "MigrationOutcome",
    "EquivalenceResult",
    "preflight_journal",
    "edit_vertex_store_clause",
    "verify_migration_report",
    "run_migration",
]


@dataclass(frozen=True)
class MigrationOutcome:
    """Outcome of a successful migration run."""

    target_path: Path
    lineage: str
    head: Head
    report_path: Path
    exceptions: TransformExceptions


@dataclass(frozen=True)
class EquivalenceResult:
    """Result of the deterministic equivalence re-run comparison."""

    matched: bool
    source_rows: int
    target_rows: int
    mismatches: tuple[str, ...] = ()


def _is_torn_tail_error(exc: BaseException) -> bool:
    """Determine whether an exception indicates an incomplete record or torn tail."""
    curr: BaseException | None = exc
    while curr is not None:
        msg = str(curr)
        if (
            "ends mid-record" in msg
            or "torn tail" in msg
            or "truncated" in msg
            or "no complete first record" in msg
        ):
            return True
        curr = curr.__cause__ or curr.__context__
    return False


def _drafts_to_records(
    lineage: str, start_head: Head, drafts: Sequence[RecordDraft]
) -> list[dict[str, Any]]:
    """Convert sequence of RecordDraft into full pre-coordinated records chaining onto start_head."""
    records: list[dict[str, Any]] = []
    prev_rh = start_head.record_hash
    for i, d in enumerate(drafts):
        ord_num = start_head.ordinal + 1 + i
        rec = build_record(
            lin=lineage,
            ordinal=ord_num,
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
    return records


def _append_drafts_through_wrapper(
    ledger: Any,
    lineage: str,
    current_head: Head,
    drafts: Sequence[RecordDraft],
    chunk_size: int = 500,
) -> Head:
    """Append drafts through AttestedLedger in chunks using the replication contract path."""
    head = current_head
    for i in range(0, len(drafts), chunk_size):
        chunk_drafts = drafts[i : i + chunk_size]
        chunk_records = _drafts_to_records(lineage, head, chunk_drafts)
        commit = ledger.replicate(expected=head, records=chunk_records)
        head = commit.after
    return head


def preflight_journal() -> None:
    """Pre-flight head journal directory and write permissions (§D.3).

    Ensures the state root and heads/ directory exist and can be written to
    before minting genesis, eliminating common NotWitnessed failure causes
    while failure is still free.

    Raises:
        JournalPreflightRefused: If heads directory cannot be created or written.
    """
    try:
        hdir = heads_dir()
        hdir.mkdir(parents=True, exist_ok=True)
        probe_path = hdir / f".probe_preflight_{uuid4().hex}"
        probe_path.write_bytes(b"probe\n")
        probe_path.unlink()
    except OSError as exc:
        raise JournalPreflightRefused(
            f"Head journal preflight failed: {exc}. "
            "Advisory: check that state root ($XDG_STATE_HOME or ~/.local/state) "
            "exists and is writable by the current user.",
            path=str(locals().get("hdir", "")),
        ) from exc


def edit_vertex_store_clause(
    vertex_path: Path | str,
    target_location: str,
    *,
    backend: str = "file",
) -> None:
    """Surgically edit the store clause in a .vertex file with verification-by-re-parse (§H.1).

    Replaces the positional location and sets backend="file", writes to a temp file
    in the same directory, fsyncs, and atomically replaces the .vertex file.

    Args:
        vertex_path: Path to the .vertex file to edit.
        target_location: Formatted location string to put in the store clause.
        backend: Backend name (defaults to 'file').

    Raises:
        PublishPreconditionRefused: If verification-by-re-parse fails.
        FileNotFoundError: If vertex_path does not exist.
    """
    v_path = Path(vertex_path).resolve()
    if not v_path.exists():
        raise FileNotFoundError(f"Vertex file not found: {v_path}")

    original_text = v_path.read_text(encoding="utf-8")
    pre_ast = parse_vertex(original_text, v_path)

    new_store_clause = f'store "{target_location}" backend="{backend}"'
    if re.search(r"^[ \t]*store\b.*$", original_text, flags=re.MULTILINE):
        edited_text = re.sub(
            r"^[ \t]*store\b.*$",
            new_store_clause,
            original_text,
            flags=re.MULTILINE,
            count=1,
        )
    else:
        if re.search(r'^[ \t]*name\s+"[^"]*".*$', original_text, flags=re.MULTILINE):
            edited_text = re.sub(
                r'(^[ \t]*name\s+"[^"]*".*$)',
                r"\1\n" + new_store_clause,
                original_text,
                flags=re.MULTILINE,
                count=1,
            )
        else:
            edited_text = f"{new_store_clause}\n\n{original_text}"

    # Verification-by-re-parse
    try:
        post_ast = parse_vertex(edited_text, v_path)
    except Exception as exc:
        raise PublishPreconditionRefused(
            f"Verification-by-re-parse failed: edited .vertex could not be parsed: {exc}. "
            "Advisory: check .vertex file syntax.",
            condition="vertex_reparse",
        ) from exc

    if post_ast.store_backend != BackendDecl(name=backend):
        raise PublishPreconditionRefused(
            f"Verification-by-re-parse failed: expected store_backend={backend!r}, got {post_ast.store_backend!r}. "
            "Advisory: check store clause backend property.",
            condition="vertex_store_backend",
        )

    # Assert every non-store field is untouched
    field_mismatches: list[str] = []
    if post_ast.name != pre_ast.name:
        field_mismatches.append(f"name ({pre_ast.name!r} != {post_ast.name!r})")
    if post_ast.loops != pre_ast.loops:
        field_mismatches.append("loops")
    if post_ast.discover != pre_ast.discover:
        field_mismatches.append("discover")
    if post_ast.sources != pre_ast.sources:
        field_mismatches.append("sources")
    if post_ast.vertices != pre_ast.vertices:
        field_mismatches.append("vertices")
    if post_ast.routes != pre_ast.routes:
        field_mismatches.append("routes")
    if post_ast.emit != pre_ast.emit:
        field_mismatches.append("emit")
    if post_ast.combine != pre_ast.combine:
        field_mismatches.append("combine")
    if post_ast.sources_blocks != pre_ast.sources_blocks:
        field_mismatches.append("sources_blocks")
    if post_ast.observers != pre_ast.observers:
        field_mismatches.append("observers")
    if post_ast.lens != pre_ast.lens:
        field_mismatches.append("lens")
    if post_ast.boundary != pre_ast.boundary:
        field_mismatches.append("boundary")
    if post_ast.observer_scoped != pre_ast.observer_scoped:
        field_mismatches.append("observer_scoped")
    if post_ast.strict != pre_ast.strict:
        field_mismatches.append("strict")

    if field_mismatches:
        raise PublishPreconditionRefused(
            f"Verification-by-re-parse failed: non-store fields modified during surgical edit: {', '.join(field_mismatches)}. "
            "Advisory: verify .vertex file format.",
            condition="vertex_fields_equality",
        )

    # Atomic write via temp file in the same directory + fsync + os.replace
    v_dir = v_path.parent
    temp_path = v_dir / f".tmp_{v_path.name}_{uuid4().hex}"
    try:
        with temp_path.open("w", encoding="utf-8") as f:
            f.write(edited_text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, v_path)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _check_equivalence(
    source_path: Path,
    target_records: list[dict[str, Any]],
    rule: Transform,
    custodian: str,
) -> EquivalenceResult:
    """Compare expected logical rows derived from unmodified source against target records."""
    src = LegacySource.read(source_path)

    expected_rows: list[dict[str, Any]] = []
    for unit in src.units:
        if isinstance(unit, FlatFactUnit):
            mf = rule.map_fact(unit.row)
            if mf is not None:
                expected_rows.append(
                    {
                        "row_kind": "fact",
                        "id": mf.id,
                        "kind": mf.kind,
                        "ts": mf.ts,
                        "observer": mf.observer,
                        "origin": mf.origin,
                        "payload": mf.payload,
                        "signature": mf.signature,
                    }
                )
        elif isinstance(unit, BatchUnit):
            for r in unit.rows:
                mf = rule.map_fact(r)
                if mf is not None:
                    expected_rows.append(
                        {
                            "row_kind": "fact",
                            "id": mf.id,
                            "kind": mf.kind,
                            "ts": mf.ts,
                            "observer": mf.observer,
                            "origin": mf.origin,
                            "payload": mf.payload,
                            "signature": mf.signature,
                        }
                    )
        elif isinstance(unit, TickUnit):
            expected_rows.append(
                {
                    "row_kind": "tick",
                    "id": unit.id,
                    "name": unit.name,
                    "ts": unit.ts,
                    "since": unit.since,
                    "origin": unit.origin,
                    "payload": unit.payload,
                    "prev_hash": unit.prev_hash,
                    "window_start": unit.window_start,
                    "fact_cursor": unit.fact_cursor,
                    "window_hash": unit.window_hash,
                    "signature": unit.signature,
                }
            )

    target_rows: list[dict[str, Any]] = []
    for rec in target_records:
        k = rec.get("k")
        if k in {GENESIS_KIND, KEY_INTRODUCTION_KIND}:
            continue
        if k not in {FACT_KIND, BATCH_KIND, TICK_KIND}:
            continue

        expanded = rows_of_body(k, rec["body"])
        for row_k, row_tuple in expanded:
            if row_k == FACT_KIND:
                fact_id, kind, ts, observer, origin, payload, sig = row_tuple
                target_rows.append(
                    {
                        "row_kind": "fact",
                        "id": fact_id,
                        "kind": kind,
                        "ts": ts,
                        "observer": observer,
                        "origin": origin,
                        "payload": payload,
                        "signature": sig,
                    }
                )
            elif row_k == TICK_KIND:
                (
                    tick_id,
                    name,
                    ts,
                    since,
                    origin,
                    payload,
                    prev_hash,
                    window_start,
                    fact_cursor,
                    window_hash,
                    sig,
                ) = row_tuple
                target_rows.append(
                    {
                        "row_kind": "tick",
                        "id": tick_id,
                        "name": name,
                        "ts": ts,
                        "since": since,
                        "origin": origin,
                        "payload": payload,
                        "prev_hash": prev_hash,
                        "window_start": window_start,
                        "fact_cursor": fact_cursor,
                        "window_hash": window_hash,
                        "signature": sig,
                    }
                )

    mismatches: list[str] = []
    if len(expected_rows) != len(target_rows):
        mismatches.append(
            f"row count mismatch: expected {len(expected_rows)} logical rows, found {len(target_rows)}"
        )
    else:
        for i, (exp, tgt) in enumerate(zip(expected_rows, target_rows, strict=True)):
            if exp != tgt:
                diff_keys = [k for k in exp if exp.get(k) != tgt.get(k)]
                mismatches.append(
                    f"row {i} mismatch on {diff_keys}: expected {exp} != target {tgt}"
                )

    return EquivalenceResult(
        matched=(len(mismatches) == 0),
        source_rows=len(expected_rows),
        target_rows=len(target_rows),
        mismatches=tuple(mismatches),
    )


def _check_inventory_equality(
    source_inv: SourceInventory,
    target_records: list[dict[str, Any]],
    exceptions: TransformExceptions,
) -> None:
    """Assert inventory equality per §I.3 between source inventory and target projection.

    Compares per-kind row counts, tick count, and observer census (accounting for
    dropped units). Record counts are deliberately NOT compared (§I.3).

    Raises:
        PublishPreconditionRefused: If any inventory metric diverges.
    """
    target_per_kind: dict[str, int] = defaultdict(int)
    target_observer_census: dict[str, int] = defaultdict(int)
    target_tick_count = 0

    for rec in target_records:
        k = rec.get("k")
        if k in {GENESIS_KIND, KEY_INTRODUCTION_KIND}:
            continue
        if k not in {FACT_KIND, BATCH_KIND, TICK_KIND}:
            continue

        expanded = rows_of_body(k, rec["body"])
        for row_k, row_tuple in expanded:
            if row_k == FACT_KIND:
                fact_id, kind, ts, observer, origin, payload, sig = row_tuple
                target_per_kind[kind] += 1
                target_observer_census[observer] += 1
            elif row_k == TICK_KIND:
                target_tick_count += 1

    expected_per_kind = dict(source_inv.per_kind_counts)
    expected_observer_census = dict(source_inv.observer_census)
    expected_tick_count = source_inv.tick_count

    mismatches: list[str] = []
    if dict(target_per_kind) != expected_per_kind:
        mismatches.append(
            f"per-kind counts mismatch: source/expected={expected_per_kind} != target={dict(target_per_kind)}"
        )
    if dict(target_observer_census) != expected_observer_census:
        mismatches.append(
            f"observer census mismatch: source/expected={expected_observer_census} != target={dict(target_observer_census)}"
        )
    if target_tick_count != expected_tick_count:
        mismatches.append(
            f"tick count mismatch: source/expected={expected_tick_count} != target={target_tick_count}"
        )

    if mismatches:
        raise PublishPreconditionRefused(
            f"Inventory equality check failed: {'; '.join(mismatches)}. "
            "Advisory: source and target contents diverge in census projection.",
            condition="inventory_equality",
        )


def verify_migration_report(
    report_path: Path | str,
    public_key: str,
    *,
    verify: Verify | None = None,
    target_path: Path | str | None = None,
) -> bool:
    """Verify a migration report's signature and re-check target head claim (§I.1).

    Args:
        report_path: Path to the signed <lineage>.migration-report.json file.
        public_key: Public Ed25519 key of the custodian (base64 string).
        verify: Injected Verify function (key_b64, sig, digest) -> bool.
        target_path: Optional explicit path to the target arrival store.
            If omitted, defaults to `<store_dir>/<lineage>.arrival` beside the report.

    Returns:
        True if the signature is valid and the target head claim matches live target.
    """
    r_path = Path(report_path).resolve()
    if not r_path.exists():
        return False

    try:
        report_doc = json.loads(r_path.read_text(encoding="utf-8"))
    except Exception:
        return False

    body = report_doc.get("body")
    signature = report_doc.get("signature")
    if not isinstance(body, dict) or not isinstance(signature, str):
        return False

    # Verify signature over canonical JSON bytes of body
    canonical_bytes = _canonical_bytes(body)
    digest = hashlib.sha256(canonical_bytes).hexdigest()

    if verify is None:
        raise ValueError(
            "verify function must be provided (verify is injected per Rule 4/11)"
        )

    if not verify(public_key, signature, digest):
        return False

    # Re-check target head claim against live target
    target_head_claim = body.get("target_head")
    if not isinstance(target_head_claim, dict):
        return False

    lineage = target_head_claim.get("lineage")
    if not lineage:
        return False

    if target_path is None:
        t_path = r_path.parent / f"{lineage}.arrival"
    else:
        t_path = Path(target_path).resolve()

    if not t_path.exists():
        return False

    registry = BackendRegistry.with_builtin_backends()
    descriptor = StoreDescriptor(backend="file", location=str(t_path))
    try:
        ledger, _ = registry.open(descriptor)
        live_head = ledger.head()
    except Exception:
        return False

    if (
        live_head.lineage != target_head_claim.get("lineage")
        or live_head.ordinal != target_head_claim.get("ordinal")
        or live_head.record_hash != target_head_claim.get("record_hash")
    ):
        return False

    return True


def run_migration(
    source_path: Path | str,
    vertex_path: Path | str,
    *,
    store_dir: Path | str,
    signer: Signer,
    transform_rule: Transform | None = None,
    resume_target: Path | str | None = None,
    custodian: str | None = None,
    custodian_key: str | None = None,
    tool_version: str = "0.1.0",
) -> MigrationOutcome:
    """Run full migration pipeline from legacy store to Arrival store.

    Stages:
    1. Inventory pass: validates legacy store format and defects before any target touch.
    2. Deterministic transform: transforms source units into record drafts.
    3. Journal pre-flight: probes state root and heads/ directory.
    4. Target open & mint (fresh) / scan & diff (resume).
    5. Append loop: commits drafts through AttestedLedger.
    6. Verification: verify(Full) + equivalence re-run.
    7. Migration report: builds and signs migration report with custodian key.
    8. Preconditions check: asserts all 5 publish preconditions hold.
    9. Atomic publish: surgical .vertex store clause edit with verification-by-re-parse.

    Args:
        source_path: Path to legacy .jsonl or .sqlite store.
        vertex_path: Path to target .vertex file.
        store_dir: Directory where staging .arrival store and report will be created.
        signer: Injected Signer for custodian signatures.
        transform_rule: Deterministic fact transform rule (defaults to identity()).
        resume_target: Explicit staging target path when resuming an interrupted migration.
        custodian: Custodian observer name override (defaults to vertex name).
        custodian_key: Custodian public key override (defaults to declared key).
        tool_version: Tool version string for report metadata.

    Returns:
        MigrationOutcome with target path, lineage, head, report path, exceptions.

    Raises:
        MigrationRefused: On any source defect, resume mismatch, torn tail,
            preflight failure, or precondition violation.
        FileNotFoundError: If source or vertex file does not exist.
    """
    src_path = Path(source_path).resolve()
    v_path = Path(vertex_path).resolve()
    s_dir = Path(store_dir).resolve()

    if not src_path.exists():
        raise FileNotFoundError(f"Legacy source not found: {src_path}")
    if not v_path.exists():
        raise FileNotFoundError(f"Vertex file not found: {v_path}")

    # Stage 1: Inventory pass (refusals fire here, before any target creation)
    try:
        inv = inventory(src_path)
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        raise LegacyStorageRefused(
            f"Legacy storage read failed for source {src_path!r}: {exc}. "
            "Advisory: inspect legacy store database schema or file integrity.",
            source=str(src_path),
        ) from exc

    # Stage 2: Transform pass
    vertex_ast = coerce_vertex(v_path)
    t_rule = transform_rule if transform_rule is not None else identity()

    try:
        transform_result = transform(
            source=src_path,
            vertex=vertex_ast,
            rule=t_rule,
            signer=signer,
            custodian=custodian,
            custodian_key=custodian_key,
        )
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
        raise LegacyStorageRefused(
            f"Legacy storage read failed during transform for source {src_path!r}: {exc}. "
            "Advisory: inspect legacy store database schema or file integrity.",
            source=str(src_path),
        ) from exc

    drafts = transform_result.drafts
    exceptions = transform_result.exceptions
    genesis_req = transform_result.genesis

    # Stage 3: Journal pre-flight (§D.3)
    preflight_journal()

    # Stage 4 & 5: Target open & Append loop
    registry = BackendRegistry.with_builtin_backends()

    if resume_target is None:
        # Fresh migration run (§D.2: Lineage-named staging path)
        lineage = mint_lineage()
        target_path = s_dir / f"{lineage}.arrival"
        target_path.parent.mkdir(parents=True, exist_ok=True)

        descriptor = StoreDescriptor(
            backend="file", location=str(target_path), lineage=lineage
        )
        ledger, query = registry.open(descriptor)

        # First touch is mint() through the wrapper (§E)
        mint_options: dict[str, Any] = {
            "observer": genesis_req.custodian,
            "signer": signer,
            "key": genesis_req.key,
            "lineage": lineage,
            "at": 0.0,
        }
        current_head = ledger.mint(mint_options)

        # Append drafts in append loop via wrapper
        if drafts:
            current_head = _append_drafts_through_wrapper(
                ledger, lineage, current_head, drafts
            )

    else:
        # Resume run (§D.1: Resume point derived from target head)
        target_path = Path(resume_target).resolve()
        if not target_path.exists():
            raise FileNotFoundError(f"Resume target does not exist: {target_path}")

        descriptor = StoreDescriptor(backend="file", location=str(target_path))

        try:
            ledger, query = registry.open(descriptor)
            current_head = ledger.head()
        except Exception as exc:
            if _is_torn_tail_error(exc):
                raise TornTailRefused(
                    f"Resume target {target_path} ends mid-record: {exc}. "
                    "Advisory: out-of-band truncate the torn tail or start a fresh migration.",
                    target_path=str(target_path),
                ) from exc
            raise TargetMismatchOnResumeRefused(
                f"Resume target {target_path} cannot be opened: {exc}. "
                "Advisory: inspect target store or start a fresh migration.",
                target_path=str(target_path),
            ) from exc

        lineage = current_head.lineage

        # Scan existing records through current_head and diff prefix against expected drafts
        try:
            scanned_records = list(ledger.scan(through=current_head))
        except Exception as exc:
            if _is_torn_tail_error(exc):
                raise TornTailRefused(
                    f"Resume target {target_path} ends mid-record during scan: {exc}. "
                    "Advisory: out-of-band truncate the torn tail or start a fresh migration.",
                    target_path=str(target_path),
                ) from exc
            raise TargetMismatchOnResumeRefused(
                f"Resume target {target_path} failed scan at {current_head}: {exc}. "
                "Advisory: inspect target store or start a fresh migration.",
                target_path=str(target_path),
            ) from exc

        if len(scanned_records) != current_head.ordinal + 1:
            raise TargetMismatchOnResumeRefused(
                f"Target at {target_path} has {len(scanned_records)} scanned records, "
                f"expected {current_head.ordinal + 1}. "
                "Advisory: target store density or scan is inconsistent; start a fresh migration.",
                target_path=str(target_path),
            )

        # Check genesis at ordinal 0
        genesis_rec = scanned_records[0]
        if (
            genesis_rec.get("k") != GENESIS_KIND
            or genesis_rec.get("body", {}).get("lineage") != lineage
        ):
            raise TargetMismatchOnResumeRefused(
                f"Target at {target_path} genesis at ordinal 0 does not match lineage {lineage}. "
                "Advisory: start a fresh migration.",
                target_path=str(target_path),
                ordinal=0,
            )

        # Check ordinals 1..current_head.ordinal against expected drafts
        if current_head.ordinal > len(drafts):
            raise TargetMismatchOnResumeRefused(
                f"Target at {target_path} has advanced beyond expected drafts: "
                f"target ordinal={current_head.ordinal} > expected drafts={len(drafts)}. "
                "Advisory: start a fresh migration.",
                target_path=str(target_path),
                ordinal=current_head.ordinal,
            )

        for ord_idx in range(1, current_head.ordinal + 1):
            target_rec = scanned_records[ord_idx]
            exp_draft = drafts[ord_idx - 1]

            if (
                target_rec.get("k") != exp_draft.kind
                or target_rec.get("observer") != exp_draft.observer
                or target_rec.get("origin") != exp_draft.origin
                or target_rec.get("body") != exp_draft.body
            ):
                raise TargetMismatchOnResumeRefused(
                    f"Target record at ordinal {ord_idx} diverges from expected deterministic draft. "
                    "Advisory: target log content does not match source transform; start a fresh migration.",
                    target_path=str(target_path),
                    ordinal=ord_idx,
                )

        # Append remaining drafts beyond current_head
        if current_head.ordinal < len(drafts):
            remaining_drafts = drafts[current_head.ordinal :]
            current_head = _append_drafts_through_wrapper(
                ledger, lineage, current_head, remaining_drafts
            )

    # Stage 6: Verification (BOTH gates: Full verify + Equivalence re-run)
    verified_head = ledger.verify(Full(through=current_head))
    if verified_head != current_head:
        raise PublishPreconditionRefused(
            f"Target verification failed: verified head {verified_head} != current head {current_head}. "
            "Advisory: internal log consistency check failed.",
            condition="target_verify_full",
        )

    # Precondition: Source quiescence check (source content hash unchanged)
    post_inv = inventory(src_path)
    if post_inv.content_hash != inv.content_hash:
        raise SourceChangedRefused(
            f"Legacy source changed during staging at {src_path}: "
            f"content hash changed from {inv.content_hash} to {post_inv.content_hash} "
            "(two histories, not a migration). "
            "Advisory: ensure legacy store is quiesced before running migration.",
            source=str(src_path),
            expected_hash=inv.content_hash,
            actual_hash=post_inv.content_hash,
        )

    all_target_records = list(ledger.scan(through=current_head))
    equiv_res = _check_equivalence(
        src_path, all_target_records, t_rule, genesis_req.custodian
    )
    if not equiv_res.matched:
        raise PublishPreconditionRefused(
            f"Equivalence re-run failed: {'; '.join(equiv_res.mismatches)}. "
            "Advisory: re-derived expected rows do not match target records.",
            condition="equivalence_rerun",
        )

    # Precondition: Inventory equality (§I.3)
    _check_inventory_equality(inv, all_target_records, exceptions)

    # Precondition: Journal's FIRST entry for lineage is bootstrap/MINT (§E)
    j_read = read_journal(lineage)
    if (
        not j_read.entries
        or j_read.entries[0].kind != Kind.BOOTSTRAP
        or j_read.entries[0].level != Level.MINT
    ):
        first_entry = j_read.entries[0] if j_read.entries else None
        raise PublishPreconditionRefused(
            f"Journal first entry for lineage {lineage} is not bootstrap/MINT (found: {first_entry}). "
            "Advisory: target lineage was not minted through AttestedLedger.",
            condition="journal_first_entry_mint",
        )

    # Stage 7: Migration report (§I.1)
    report_path = target_path.parent / f"{lineage}.migration-report.json"
    report_body: dict[str, Any] = {
        "source_format": inv.source_format,
        "tool_version": tool_version,
        "source_content_sha256": inv.source_content_sha256,
        "source_file_sha256": inv.source_file_sha256,
        "source_inventory": {
            "total_rows": inv.total_rows,
            "total_lines": inv.total_lines,
            "per_kind_counts": inv.per_kind_counts,
            "tick_count": inv.tick_count,
            "batch_line_count": inv.batch_line_count,
            "observer_census": inv.observer_census,
            "id_era_census": inv.id_era_census,
        },
        "target_head": {
            "lineage": current_head.lineage,
            "ordinal": current_head.ordinal,
            "record_hash": current_head.record_hash,
        },
        "exceptions": {
            "keyless_declared_observers": list(
                exceptions.keyless_declared_observers
            ),
            "undeclared_row_observers": list(
                exceptions.undeclared_row_observers
            ),
            "dropped_units": [
                {"coordinate": u.coordinate, "kind": u.kind, "rule": u.rule}
                for u in exceptions.dropped_units
            ],
        },
        "transform_rule": t_rule.rule,
        "equivalence_diff": {
            "matched": equiv_res.matched,
            "source_rows": equiv_res.source_rows,
            "target_rows": equiv_res.target_rows,
            "mismatches": list(equiv_res.mismatches),
        },
        "custodian": genesis_req.custodian,
    }

    canonical_bytes = _canonical_bytes(report_body)
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    report_signature = signer(genesis_req.custodian, digest)
    if report_signature is None:
        raise PublishPreconditionRefused(
            f"Custodian {genesis_req.custodian!r} produced no signature for migration report. "
            "Advisory: check signer configuration.",
            condition="report_signature",
        )

    report_document = {
        "body": report_body,
        "signature": report_signature,
        "signer": genesis_req.custodian,
    }
    report_path.write_text(
        json.dumps(report_document, indent=2) + "\n", encoding="utf-8"
    )

    # Stage 9: Atomic descriptor publish (§H)
    try:
        rel_target = target_path.relative_to(v_path.parent)
        new_store_location = (
            f"./{rel_target}"
            if not str(rel_target).startswith(".")
            else str(rel_target)
        )
    except ValueError:
        new_store_location = str(target_path)

    edit_vertex_store_clause(
        vertex_path=v_path, target_location=new_store_location, backend="file"
    )

    return MigrationOutcome(
        target_path=target_path,
        lineage=lineage,
        head=current_head,
        report_path=report_path,
        exceptions=exceptions,
    )
