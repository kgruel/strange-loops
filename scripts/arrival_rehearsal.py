"""Run a one-shot Arrival migration rehearsal on already-copied inputs.

All input, state, credentials, store, export and evidence paths must resolve
inside an explicit disposable sandbox. This script never opens the original
legacy store or its keys and never repairs rejected legacy rows.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any


class RehearsalRefused(Exception):
    """An input or sandbox boundary is not suitable for an offline rehearsal."""


def _progress(stage: str) -> None:
    print(f"[arrival-rehearsal] {stage}", file=sys.stderr, flush=True)


def _inside(root: Path, value: Path, label: str, *, must_exist: bool) -> Path:
    try:
        resolved = value.expanduser().resolve(strict=must_exist)
    except OSError as exc:
        raise RehearsalRefused(f"{label} is unavailable") from exc
    if resolved == root or root not in resolved.parents:
        raise RehearsalRefused(f"{label} must be strictly inside the sandbox")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_prefix(path: Path, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    with path.open("rb") as stream:
        while remaining:
            chunk = stream.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RehearsalRefused("migrated custody prefix was truncated")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def _close(handle: object) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _head(head: Any) -> dict[str, Any]:
    return {
        "lineage": head.lineage,
        "ordinal": head.ordinal,
        "record_hash": head.record_hash,
    }


def _refusal_evidence(exc: Exception) -> dict[str, Any]:
    """Retain SDK proof coordinates, never exception messages or row bodies."""
    result: dict[str, Any] = {"type": type(exc).__name__}
    source_type = getattr(exc, "source_type", None)
    if isinstance(source_type, str):
        result["source_type"] = source_type
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        head = details.get("captured_head")
        if isinstance(head, dict) and set(head) == {"lineage", "ordinal", "record_hash"}:
            result["captured_head"] = head
        proof = details.get("evidence")
        if isinstance(proof, dict):
            if isinstance(proof.get("phase"), str):
                result["phase"] = proof["phase"]
            effects = proof.get("effects")
            if isinstance(effects, dict):
                result["effects"] = {
                    resource: {"attempt": effect.get("attempt"), "state": effect.get("state")}
                    for resource, effect in effects.items()
                    if resource in {"custody", "witness", "derived", "cache", "artifact", "dispatch"}
                    and isinstance(effect, dict)
                    and effect.get("attempt") in {"not-entered", "entered"}
                    and effect.get("state") in {
                        "not-attempted", "known-none", "committed", "unknown", "completed", "incomplete"
                    }
                }
    current: BaseException | None = exc
    for _ in range(3):
        current = current.__cause__ if current is not None else None
        if current is None:
            break
        issue = getattr(current, "issue", None)
        reason = getattr(issue, "reason", None)
        if reason in {
            "prior-incarnation", "ambiguous-tick-role", "unproven-loop-role",
            "unproven-generated-incarnation", "invalid-projection-shape",
            "runtime-namespace-mismatch", "reserved-runtime-name",
        }:
            result["boundary_reason"] = reason
            tick_id = getattr(issue, "tick_id", None)
            if isinstance(tick_id, str):
                result["tick_id"] = tick_id
            tick_ordinal = getattr(issue, "tick_ordinal", None)
            if isinstance(tick_ordinal, int):
                result["tick_ordinal"] = tick_ordinal
            break
    return result


def _save(path: Path, evidence: dict[str, Any]) -> None:
    encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _check_paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, Path]:
    root = Path(args.sandbox).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise RehearsalRefused("sandbox must be an existing directory")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RehearsalRefused("sandbox must be outside every repository checkout")
    vertex = _inside(root, Path(args.vertex), "copied vertex", must_exist=True)
    source = _inside(root, Path(args.source), "copied source", must_exist=True)
    keys = _inside(root, Path(args.legacy_key_dir), "copied legacy key directory", must_exist=True)
    output = _inside(root, Path(args.output), "output directory", must_exist=False)
    if not vertex.is_file() or not source.is_file() or not keys.is_dir():
        raise RehearsalRefused("vertex/source must be files and legacy key path a directory")
    if keys != (vertex.parent / "keys").resolve():
        raise RehearsalRefused("copied legacy key directory must be beside the copied vertex")
    private_key = keys / "ed25519.key"
    if private_key.is_symlink():
        raise RehearsalRefused("copied legacy key file must not be a symlink")
    private_key = _inside(root, private_key, "copied legacy key", must_exist=True)
    if not private_key.is_file():
        raise RehearsalRefused("copied legacy key must be a file")
    if output.exists():
        raise RehearsalRefused("output directory already exists; each run needs a fresh output")
    if any(output in path.parents or path in output.parents for path in (vertex, source, keys)):
        raise RehearsalRefused("output directory must be separate from copied inputs")
    return root, vertex, source, keys, output


def _check_vertex(vertex: Path, source: Path, observer: str) -> None:
    from lang import parse_vertex_file

    ast = parse_vertex_file(vertex)
    if ast.name != observer:
        raise RehearsalRefused("observer must equal the copied vertex self name")
    if ast.store_backend is not None or ast.store is None:
        raise RehearsalRefused("copied vertex must still declare a legacy store")
    named_source = (vertex.parent / ast.store).resolve()
    if named_source != source:
        raise RehearsalRefused("copied vertex store path must name the copied source")


def _isolated_environment(output: Path) -> None:
    runtime = output / "runtime"
    for name, leaf in (
        ("XDG_STATE_HOME", "state"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("LOOPS_HOME", "loops"),
    ):
        path = runtime / leaf
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)


def _verify_signature(key: str, signature: str, digest: str, domain: str) -> bool:
    from sign import ed25519

    try:
        public = ed25519.public_key_from_b64(key)
    except ValueError:
        return False
    return ed25519.verify(public, signature, digest.encode(), domain=domain)


def _verify_rehearsal_emit(fact_id: str, commit: Any, public_key: str) -> None:
    from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
    from engine.admission import fact_commitment_hash
    from engine.arrival import content_commitment

    matching = [
        record
        for record in commit.records
        if record.get("k") == "fact"
        and isinstance(record.get("body"), dict)
        and record["body"].get("id") == fact_id
    ]
    if len(matching) != 1:
        raise RehearsalRefused("exact ordinary commit lacks one emitted fact")
    record = matching[0]
    body = record["body"]
    assert isinstance(body, dict)
    inner = body.get("signature")
    outer = record.get("sig")
    if not isinstance(inner, str) or not isinstance(outer, str):
        raise RehearsalRefused("rehearsal emit is missing a signature")
    fact_digest = fact_commitment_hash(
        body["kind"], body["ts"], body["observer"], body["origin"], body["payload"]
    )
    arrival_digest = content_commitment(
        record["k"], record["at"], record["observer"], record["origin"], body
    )
    if not _verify_signature(public_key, inner, fact_digest, FACT_DOMAIN):
        raise RehearsalRefused("rehearsal FACT signature did not verify")
    if not _verify_signature(public_key, outer, arrival_digest, ARRIVAL_DOMAIN):
        raise RehearsalRefused("rehearsal ARRIVAL signature did not verify")


def _exact_export(vertex: Path, output: Path, head: Any) -> dict[str, Any]:
    from engine.arrival_registry import BackendRegistry, descriptor_for
    from lang import parse_vertex_file
    from sdk import export_target

    published = export_target(vertex, output, through=head)
    descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
    if descriptor is None:
        raise RehearsalRefused("export target has no Arrival descriptor")
    ledger, query = BackendRegistry.with_builtin_backends().open(descriptor)
    try:
        exact = ledger.export(through=head, codec=published.codec)
        digest = hashlib.sha256()
        size = 0
        for chunk in exact.records:
            digest.update(chunk)
            size += len(chunk)
    finally:
        _close(query)
        _close(ledger)
    artifact_hash = _sha256(output)
    if exact.head != head or size != published.byte_count or digest.hexdigest() != artifact_hash:
        raise RehearsalRefused("published export differs from exact bounded ledger export")
    return {
        "head": _head(head), "byte_count": size,
        "sha256": artifact_hash, "exact_stream_match": True,
    }


def run_rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    root, vertex, source, keys, output = _check_paths(args)
    _check_vertex(vertex, source, args.observer)
    try:
        payload = json.loads(args.emit_payload_json)
    except ValueError as exc:
        raise RehearsalRefused("emit payload must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise RehearsalRefused("emit payload must be a JSON object")
    if not args.emit_kind or args.emit_kind.startswith("_decl."):
        raise RehearsalRefused("emit kind must be an explicit ordinary kind")

    output.mkdir(mode=0o700)
    _isolated_environment(output)
    evidence_path = output / "evidence.json"
    evidence: dict[str, Any] = {
        "schema": "loops.rehearsal/arrival/v1",
        "status": "running", "stage": "source-hash",
        "sandbox": str(root), "copied_source": str(source),
        "copied_vertex": str(vertex), "output": str(output),
        "rehearsal_only": True,
    }
    migration_target: Path | None = None
    emit_target_before_hash: str | None = None
    try:
        _progress("hashing copied source")
        before = _sha256(source)
        evidence["source_sha256_before"] = before
        _save(evidence_path, evidence)

        from custody.signing import ARRIVAL_DOMAIN
        from engine.arrival_contract import Full
        from engine.arrival_registry import BackendRegistry, descriptor_for
        from lang import parse_vertex_file
        from migrate.inventory import inventory
        from migrate.sidecar import run_migration, verify_migration_report
        from sdk import (
            MappedCredentialProvider,
            adopt_arrival,
            emit_fact,
            inspect_declaration,
            read_facts,
            read_state,
            read_summary,
            sync_target,
            verify_target,
        )
        from sign import ed25519

        evidence["stage"] = "inventory"
        _save(evidence_path, evidence)
        _progress("inventory of copied source")
        inv = inventory(source)
        evidence["inventory"] = {
            "format": inv.source_format, "total_rows": inv.total_rows,
            "total_lines": inv.total_lines, "tick_count": inv.tick_count,
            "batch_line_count": inv.batch_line_count,
            "per_kind_counts": inv.per_kind_counts,
            "observer_census": inv.observer_census,
            "id_era_census": inv.id_era_census,
            "content_sha256": inv.content_hash, "file_sha256": inv.file_hash,
        }
        if inv.file_hash != before:
            raise RehearsalRefused("copied source changed during inventory")

        pair = ed25519.load(keys)
        declared = parse_vertex_file(vertex)
        selected_key = None
        for document in declared.observers or ():
            if document.name == args.observer:
                selected_key = document.key
                break
        if selected_key != pair.public_b64:
            raise RehearsalRefused("copied self key differs from reviewed declaration")

        def signer(named: str, digest: str) -> str | None:
            if named != args.observer:
                return None
            return ed25519.sign(pair, digest.encode(), domain=ARRIVAL_DOMAIN)

        evidence["stage"] = "migration"
        _save(evidence_path, evidence)
        _progress("migrating copied source")
        reviewed_text = vertex.read_text(encoding="utf-8")
        reviewed_sha256 = hashlib.sha256(reviewed_text.encode()).hexdigest()
        reviewed_path = output / "reviewed.vertex"
        reviewed_path.write_text(reviewed_text, encoding="utf-8")
        reviewed_path.chmod(0o600)
        evidence["reviewed_snapshot"] = {
            "path": str(reviewed_path), "sha256": reviewed_sha256,
        }
        staging = output / "stores"
        staging.mkdir()
        migration = run_migration(source, vertex, store_dir=staging, signer=signer)
        migration_target = migration.target_path
        prefix_size = migration.target_path.stat().st_size
        prefix_hash = _sha256_prefix(migration.target_path, prefix_size)
        report_hash = _sha256(migration.report_path)
        evidence["migration"] = {
            "selected_head": _head(migration.head),
            "lineage": migration.lineage,
            "target_path": str(migration.target_path),
            "prefix_byte_count": prefix_size,
            "prefix_sha256": prefix_hash,
            "report_sha256": report_hash,
            "keyless_declared_observer_count": len(
                migration.exceptions.keyless_declared_observers
            ),
            "undeclared_row_observer_count": len(
                migration.exceptions.undeclared_row_observers
            ),
            "dropped_unit_count": len(migration.exceptions.dropped_units),
        }

        evidence["stage"] = "report-verify-at-S"
        _save(evidence_path, evidence)
        _progress("verifying migration report at selected S")
        verified_report = verify_migration_report(
            migration.report_path, pair.public_b64,
            verify=lambda key, signature, digest: _verify_signature(
                key, signature, digest, ARRIVAL_DOMAIN
            ),
            target_path=migration.target_path,
        )
        if not verified_report:
            raise RehearsalRefused("migration report did not verify at S")
        descriptor = descriptor_for(parse_vertex_file(vertex), vertex)
        if descriptor is None or descriptor.lineage != migration.lineage:
            raise RehearsalRefused("published descriptor does not name migrated lineage")
        ledger, query = BackendRegistry.with_builtin_backends().open(descriptor)
        try:
            if ledger.verify(Full(through=migration.head)) != migration.head:
                raise RehearsalRefused("migration S did not Full-verify")
        finally:
            _close(query)
            _close(ledger)
        evidence["report_verified_at_S"] = True

        evidence["stage"] = "mapped-import-and-adoption"
        _save(evidence_path, evidence)
        _progress("importing copied key and adopting reviewed declaration")
        provider = MappedCredentialProvider(
            output / "credentials", namespace="arrival-rehearsal",
        )
        imported = provider.import_legacy(
            vertex, args.observer, token=f"rehearsal-{before[:24]}"
        )
        if imported.public_key != pair.public_b64:
            raise RehearsalRefused("mapped imported key differs from copied self key")
        adopted = adopt_arrival(
            vertex, selected_head=migration.head,
            reviewed_text=reviewed_text, reviewed_sha256=reviewed_sha256,
            declaration_text=vertex.read_text(encoding="utf-8"),
            observer=args.observer, credentials=provider,
            runtime_epoch=args.runtime_epoch,
        )
        if adopted.commit is None or adopted.commit.before != migration.head:
            raise RehearsalRefused("adoption did not report Commit(S,A)")
        a = adopted.commit.after
        evidence["adoption"] = {
            "head": _head(a), "fact_id_equals_lineage": adopted.fact_id == migration.lineage,
            "phase": adopted.phase,
            "runtime_epoch": adopted.runtime_epoch,
            "projected_after": None if adopted.projection is None else adopted.projection.get(
                "projected_after"
            ),
        }

        evidence["stage"] = "ordinary-reads"
        _save(evidence_path, evidence)
        _progress("verifying adopted reads")
        verified_a = verify_target(vertex, through=a)
        inspected = inspect_declaration(vertex)
        summary = read_summary(vertex)
        page = read_facts(vertex, limit=1)
        state = read_state(vertex)
        state_epoch = state.generation.get("runtime_epoch")
        if not isinstance(state_epoch, dict):
            raise RehearsalRefused("adopted state lacks runtime-epoch evidence")
        if args.runtime_epoch == "fresh" and state_epoch != {
            "mode": "fresh",
            "anchor_ordinal": a.ordinal,
        }:
            raise RehearsalRefused("fresh state epoch does not begin at adoption head")
        state_sections = json.dumps(
            state.sections,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if (
            verified_a.verified_through != a
            or summary.basis is None
            or summary.basis.captured_head != a
            or summary.basis.projected_through != a
            or inspected.basis is None
            or inspected.basis.captured_head != a
        ):
            raise RehearsalRefused("adopted verification/read basis failed")
        evidence["reads_at_A"] = {
            "head": _head(a), "declaration_status": inspected.status,
            "fact_total": summary.fact_total, "tick_total": summary.tick_total,
            "sample_fact_count": len(page.items),
            "summary_basis": None if summary.basis is None else _head(
                summary.basis.captured_head
            ),
            "runtime_state": {
                "runtime_epoch": state_epoch,
                "sections_sha256": hashlib.sha256(state_sections).hexdigest(),
            },
        }

        evidence["stage"] = "rehearsal-only-emit"
        emit_target_before_hash = _sha256(migration.target_path)
        evidence["rehearsal_emit_precondition"] = {
            "head": _head(a), "target_sha256": emit_target_before_hash,
        }
        _save(evidence_path, evidence)
        _progress("writing one rehearsal-only signed fact")
        emitted = emit_fact(
            vertex, args.emit_kind, payload, observer=args.observer,
            origin="arrival-rehearsal-only", credentials=provider,
        )
        if not emitted.stored or not emitted.signed or emitted.commit is None:
            raise RehearsalRefused("rehearsal emit lacks a signed custody commit")
        _verify_rehearsal_emit(emitted.id, emitted.commit, pair.public_b64)
        synced = sync_target(vertex)
        final_head = emitted.commit.after
        if synced.projected_after != final_head:
            raise RehearsalRefused("projection did not reach rehearsal emit head")
        if verify_target(vertex, through=final_head).verified_through != final_head:
            raise RehearsalRefused("final rehearsal head did not Full-verify")
        evidence["rehearsal_emit"] = {
            "rehearsal_only": True, "origin": "arrival-rehearsal-only",
            "fact_id": emitted.id, "commit_before": _head(emitted.commit.before),
            "head": _head(final_head), "signed_fact_and_arrival": True,
            "projected_after": _head(synced.projected_after),
            "full_verified": True,
        }

        evidence["stage"] = "exact-export"
        _save(evidence_path, evidence)
        _progress("publishing and comparing exact export")
        evidence["export"] = _exact_export(
            vertex, output / "final.arrival-jsonl", final_head
        )
        evidence["migration"]["prefix_unchanged_after_emit"] = (
            _sha256_prefix(migration.target_path, prefix_size) == prefix_hash
        )
        evidence["migration"]["report_unchanged_after_emit"] = (
            _sha256(migration.report_path) == report_hash
        )
        if not all((
            evidence["migration"]["prefix_unchanged_after_emit"],
            evidence["migration"]["report_unchanged_after_emit"],
        )):
            raise RehearsalRefused("migration evidence changed after adoption or emit")
        evidence["source_sha256_after"] = _sha256(source)
        evidence["source_unchanged"] = evidence["source_sha256_after"] == before
        if not evidence["source_unchanged"]:
            raise RehearsalRefused("copied source changed during rehearsal")
        evidence["status"] = "complete"
        evidence["stage"] = "complete"
        _save(evidence_path, evidence)
        _progress("complete")
        return evidence
    except Exception as exc:
        evidence["status"] = "refused"
        evidence["refusal"] = _refusal_evidence(exc)
        evidence["error_type"] = type(exc).__name__
        if migration_target is not None and emit_target_before_hash is not None:
            try:
                after_hash = _sha256(migration_target)
                evidence["target_sha256_after_refusal"] = after_hash
                evidence["target_unchanged_after_refusal"] = (
                    after_hash == emit_target_before_hash
                )
            except OSError:
                evidence["target_unchanged_after_refusal"] = None
        if "source_sha256_before" in evidence:
            try:
                evidence["source_sha256_after"] = _sha256(source)
                evidence["source_unchanged"] = (
                    evidence["source_sha256_after"] == evidence["source_sha256_before"]
                )
            except OSError:
                evidence["source_unchanged"] = None
        _save(evidence_path, evidence)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", required=True, type=Path)
    parser.add_argument("--vertex", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--legacy-key-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--observer", required=True)
    parser.add_argument("--runtime-epoch", choices=("strict", "fresh"), default="strict")
    parser.add_argument("--emit-kind", required=True)
    parser.add_argument("--emit-payload-json", required=True)
    args = parser.parse_args(argv)
    try:
        run_rehearsal(args)
    except Exception as exc:  # noqa: BLE001 - show only type; private detail stays off stdout
        # The private evidence file retains a bounded stage/type. Never print
        # legacy row contents or key material from a third-party exception.
        _progress(f"refused: {type(exc).__name__}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
