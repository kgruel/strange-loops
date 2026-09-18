#!/usr/bin/env python3
"""Exercise adoption crash recovery from an evidenced offline adoption checkpoint.

The command requires verified migration/adoption evidence from
``arrival_rehearsal.py``; a later write or export refusal does not invalidate
that checkpoint. It forks the exact migrated prefix into fresh sandbox
directories, so neither the copied source nor the adopted log is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

EXIT_DURABLE_STOP = 86


class RecoveryRehearsalRefused(Exception):
    """A supplied rehearsal artifact cannot safely support a recovery fork."""


def _sha256(path: Path, *, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with path.open("rb") as stream:
        while remaining is None or remaining > 0:
            chunk = stream.read(
                1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            )
            if not chunk:
                break
            digest.update(chunk)
            if remaining is not None:
                remaining -= len(chunk)
    if remaining not in (None, 0):
        raise RecoveryRehearsalRefused("migrated prefix was truncated")
    return digest.hexdigest()


def _inside(root: Path, value: Path, label: str, *, exists: bool) -> Path:
    try:
        resolved = value.expanduser().resolve(strict=exists)
    except OSError as exc:
        raise RecoveryRehearsalRefused(f"{label} is unavailable") from exc
    if resolved == root or root not in resolved.parents:
        raise RecoveryRehearsalRefused(f"{label} must be strictly inside the sandbox")
    return resolved


def _head(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RecoveryRehearsalRefused(f"evidence lacks {label}")
    lineage, ordinal, record_hash = (
        value.get("lineage"),
        value.get("ordinal"),
        value.get("record_hash"),
    )
    if (
        not isinstance(lineage, str)
        or not isinstance(ordinal, int)
        or not isinstance(record_hash, str)
    ):
        raise RecoveryRehearsalRefused(f"evidence has malformed {label}")
    return {"lineage": lineage, "ordinal": ordinal, "record_hash": record_hash}


def _load_evidence(
    root: Path, evidence_path: Path
) -> tuple[dict[str, Any], Path, Path, Path, dict[str, Any]]:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        not isinstance(evidence, dict)
        or evidence.get("schema") != "loops.rehearsal/arrival/v1"
    ):
        raise RecoveryRehearsalRefused("evidence is not an Arrival rehearsal artifact")
    if evidence.get("source_unchanged") is not True:
        raise RecoveryRehearsalRefused(
            "rehearsal did not retain an unchanged copied source"
        )
    if evidence.get("report_verified_at_S") is not True:
        raise RecoveryRehearsalRefused(
            "migration report was not verified at selected S"
        )
    migration = evidence.get("migration")
    reviewed = evidence.get("reviewed_snapshot")
    if (
        not isinstance(migration, dict)
        or not isinstance(reviewed, dict)
        or not isinstance(evidence.get("adoption"), dict)
    ):
        raise RecoveryRehearsalRefused(
            "evidence lacks migration, adoption, or reviewed-snapshot evidence"
        )
    selected = _head(migration.get("selected_head"), "migration.selected_head")
    target = _inside(
        root,
        Path(str(migration.get("target_path", ""))),
        "migrated target",
        exists=True,
    )
    vertex = _inside(
        root,
        Path(str(evidence.get("copied_vertex", ""))),
        "published vertex",
        exists=True,
    )
    reviewed_path = _inside(
        root, Path(str(reviewed.get("path", ""))), "reviewed vertex", exists=True
    )
    if not target.is_file() or not vertex.is_file() or not reviewed_path.is_file():
        raise RecoveryRehearsalRefused("target and vertex evidence must name files")
    prefix_size, prefix_hash = (
        migration.get("prefix_byte_count"),
        migration.get("prefix_sha256"),
    )
    if (
        not isinstance(prefix_size, int)
        or prefix_size <= 0
        or not isinstance(prefix_hash, str)
    ):
        raise RecoveryRehearsalRefused(
            "evidence has malformed migrated-prefix identity"
        )
    if _sha256(target, limit=prefix_size) != prefix_hash:
        raise RecoveryRehearsalRefused(
            "current rehearsal log no longer carries the evidenced S prefix"
        )
    reviewed_bytes = reviewed_path.read_bytes()
    if hashlib.sha256(reviewed_bytes).hexdigest() != reviewed.get("sha256"):
        raise RecoveryRehearsalRefused(
            "saved reviewed vertex differs from evidence hash"
        )
    return evidence, target, vertex, reviewed_path, selected


def _runtime_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name, leaf in (
        ("XDG_STATE_HOME", "state"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("LOOPS_HOME", "loops"),
    ):
        location = root / "runtime" / leaf
        location.mkdir(parents=True, exist_ok=True)
        env[name] = str(location)
    return env


def _fork_vertex_context(source_vertex: Path, fork: Path) -> Path:
    """Copy only the published locator; source dependencies are not imported."""
    context = fork / "vertex-context"
    context.mkdir()
    vertex = context / source_vertex.name
    shutil.copy2(source_vertex, vertex, follow_symlinks=False)
    return vertex


def _reject_symlinks(root: Path, label: str) -> None:
    """Keep copied provider material wholly inside its inspected fork root."""
    if root.is_symlink():
        raise RecoveryRehearsalRefused(f"{label} must not be a symlink")
    for parent, directories, files in os.walk(root, followlinks=False):
        base = Path(parent)
        if any((base / name).is_symlink() for name in (*directories, *files)):
            raise RecoveryRehearsalRefused(f"{label} contains a symlink")


def _fork_prefix(
    *,
    source_log: Path,
    prefix_size: int,
    prefix_hash: str,
    source_vertex: Path,
    reviewed_path: Path,
    selected: dict[str, Any],
    credentials: Path,
    fork: Path,
) -> tuple[Path, Path, Path]:
    from migrate.sidecar import edit_vertex_store_clause

    fork.mkdir(mode=0o700)
    log = fork / "store" / f"{selected['lineage']}.arrival"
    log.parent.mkdir()
    with source_log.open("rb") as source, log.open("xb") as destination:
        remaining = prefix_size
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise RecoveryRehearsalRefused(
                    "migrated target was truncated during fork"
                )
            destination.write(chunk)
            remaining -= len(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    if _sha256(log) != prefix_hash:
        raise RecoveryRehearsalRefused(
            "forked store bytes do not equal selected S prefix"
        )
    vertex = _fork_vertex_context(source_vertex, fork)
    original = vertex.read_bytes()
    edit_vertex_store_clause(
        vertex, str(log), lineage=selected["lineage"], expected_original=original
    )
    fork_reviewed = fork / "reviewed.vertex"
    shutil.copy2(reviewed_path, fork_reviewed)
    fork_credentials = fork / "credentials"
    _reject_symlinks(credentials, "mapped credentials")
    shutil.copytree(credentials, fork_credentials)
    return vertex, log, fork_credentials


def _child_adopt(
    vertex: Path,
    credentials: Path,
    namespace: str,
    reviewed: Path,
    selected: dict[str, Any],
    observer: str,
    phase: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    args = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child-adopt",
        str(vertex),
        str(credentials),
        namespace,
        str(reviewed),
        json.dumps(selected, separators=(",", ":")),
        observer,
        phase,
    ]
    return subprocess.run(
        args, text=True, capture_output=True, check=False, env=env, timeout=600
    )


def _child_recover(
    intent: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child-recover", str(intent)],
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=600,
    )


def _intent_path(vertex: Path) -> Path:
    return vertex.with_name(vertex.name + ".arrival-adopt.intent")


def _reserved_anchor(
    log: Path,
    selected: dict[str, Any],
    reserved: dict[str, Any],
    *,
    required: bool,
) -> None:
    records = [json.loads(line) for line in log.read_bytes().splitlines()]
    index = selected["ordinal"] + 1
    if len(records) <= index:
        if required:
            raise RecoveryRehearsalRefused(
                "recovery did not append the reserved anchor at S+1"
            )
        return
    matching = [
        record
        for record in records
        if record.get("body") == reserved["body"]
        and record.get("sig") == reserved["signature"]
    ]
    if len(matching) != 1 or records[index] != matching[0]:
        raise RecoveryRehearsalRefused(
            "fork does not carry exactly one reserved anchor at S+1"
        )


def _child_adopt_main(values: list[str]) -> int:
    import engine.arrival_adoption as adoption
    from engine.arrival_contract import Head
    from sdk import MappedCredentialProvider, adopt_arrival

    vertex, root, namespace, reviewed, selected_json, observer, phase = values
    selected = Head(**json.loads(selected_json))
    original_apply = adoption.apply_arrival_adoption

    def stop_at(current: str) -> None:
        if current == phase:
            os._exit(EXIT_DURABLE_STOP)

    def interrupted(registry: object, plan: object):
        return original_apply(registry, plan, failure_hook=stop_at)

    adoption.apply_arrival_adoption = interrupted
    text = Path(reviewed).read_text(encoding="utf-8")
    provider = MappedCredentialProvider(
        Path(root), namespace=namespace, receipt_observer=observer
    )
    adopt_arrival(
        vertex,
        selected_head=selected,
        reviewed_text=text,
        reviewed_sha256=hashlib.sha256(text.encode()).hexdigest(),
        declaration_text=Path(vertex).read_text(encoding="utf-8"),
        observer=observer,
        credentials=provider,
    )
    raise AssertionError("adoption did not reach the requested durable stop")


def _child_recover_main(intent_value: str) -> int:
    from sdk import (
        MappedCredentialProvider,
        SdkError,
        read_summary,
        recover_arrival_adoption,
    )

    def private_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("recovery accessed mapped signing credentials")

    MappedCredentialProvider.for_write = private_access
    MappedCredentialProvider.resolve = private_access
    MappedCredentialProvider.verify = private_access
    try:
        recovered = recover_arrival_adoption(intent_value)
        summary = read_summary(
            Path(intent_value).with_name(
                Path(intent_value).name.removesuffix(".arrival-adopt.intent")
            )
        )
    except SdkError as exc:
        print(json.dumps({"error": type(exc).__name__}, sort_keys=True))
        return 3
    if recovered.commit is None or summary.basis is None:
        raise AssertionError("recovery lacks commit or read basis")
    print(
        json.dumps(
            {
                "captured_head": _head_json(recovered.captured_head),
                "head": _head_json(recovered.head),
                "commit_before": _head_json(recovered.commit.before),
                "commit_after": _head_json(recovered.commit.after),
                "summary_head": _head_json(summary.basis.captured_head),
            },
            sort_keys=True,
        )
    )
    return 0


def _head_json(value: object) -> dict[str, object]:
    return {
        "lineage": value.lineage,
        "ordinal": value.ordinal,
        "record_hash": value.record_hash,
    }


def _head_value(value: dict[str, Any]):
    from engine.arrival_contract import Head

    return Head(**value)


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.sandbox).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise RecoveryRehearsalRefused("sandbox must be an existing directory")
    if any((parent / ".git").exists() for parent in (root, *root.parents)):
        raise RecoveryRehearsalRefused(
            "sandbox must be outside every repository checkout"
        )
    evidence_path = _inside(root, Path(args.evidence), "evidence", exists=True)
    output = _inside(root, Path(args.output), "recovery output", exists=False)
    if output.exists() or any(
        output in item.parents or item in output.parents for item in (evidence_path,)
    ):
        raise RecoveryRehearsalRefused(
            "recovery output must be a fresh sandbox directory"
        )
    evidence, source_log, source_vertex, reviewed_path, selected = _load_evidence(
        root, evidence_path
    )
    credentials = _inside(
        root,
        Path(str(evidence["output"])) / "credentials",
        "mapped credentials",
        exists=True,
    )
    adoption = evidence.get("adoption")
    if not isinstance(adoption, dict) or not isinstance(
        evidence.get("migration"), dict
    ):
        raise RecoveryRehearsalRefused("evidence lacks adoption metadata")
    observer = args.observer
    if not isinstance(observer, str) or not observer:
        raise RecoveryRehearsalRefused("observer must be explicit")
    namespace = args.namespace
    prefix_size = evidence["migration"]["prefix_byte_count"]
    prefix_hash = evidence["migration"]["prefix_sha256"]
    assert isinstance(prefix_size, int) and isinstance(prefix_hash, str)
    output.mkdir(mode=0o700)
    results: list[dict[str, Any]] = []
    for phase in ("after-intent", "after-append"):
        fork = output / phase
        vertex, log, fork_credentials = _fork_prefix(
            source_log=source_log,
            prefix_size=prefix_size,
            prefix_hash=prefix_hash,
            source_vertex=source_vertex,
            reviewed_path=reviewed_path,
            selected=selected,
            credentials=credentials,
            fork=fork,
        )
        print(
            f"[arrival-recovery] {phase}: synchronizing fork at S",
            file=sys.stderr,
            flush=True,
        )
        os.environ.update(_runtime_env(fork))
        from sdk import SdkError, read_summary, sync_target

        synced = sync_target(vertex)
        if synced.projected_after != _head_value(selected):
            raise RecoveryRehearsalRefused("fork projection did not synchronize at S")

        try:
            read_summary(vertex)
        except SdkError as exc:
            if type(exc) is not SdkError or "no adopted declaration" not in str(exc):
                raise RecoveryRehearsalRefused(
                    "pre-adoption read did not refuse for the missing declaration anchor"
                ) from exc
            preadoption_error = type(exc).__name__
        else:
            raise RecoveryRehearsalRefused(
                "read_summary unexpectedly accepted unadopted S"
            )
        before = log.read_bytes()
        print(
            f"[arrival-recovery] {phase}: stopping child at {phase}",
            file=sys.stderr,
            flush=True,
        )
        child = _child_adopt(
            vertex,
            fork_credentials,
            namespace,
            fork / "reviewed.vertex",
            selected,
            observer,
            phase,
            _runtime_env(fork),
        )
        if child.returncode != EXIT_DURABLE_STOP:
            raise RecoveryRehearsalRefused(
                f"{phase} child did not stop at durable boundary: {child.stderr}"
            )
        intent = _intent_path(vertex)
        if not intent.is_file() or _sha256(log, limit=prefix_size) != prefix_hash:
            raise RecoveryRehearsalRefused(
                "durable stop changed the selected S prefix or omitted intent"
            )
        reserved = json.loads(intent.read_text(encoding="utf-8"))["drafts"][0]
        _reserved_anchor(log, selected, reserved, required=phase == "after-append")
        offline = fork / "credentials-offline"
        fork_credentials.rename(offline)
        print(
            f"[arrival-recovery] {phase}: recovering without credentials",
            file=sys.stderr,
            flush=True,
        )
        recovered = _child_recover(intent, _runtime_env(fork))
        if recovered.returncode != 0:
            raise RecoveryRehearsalRefused(
                f"{phase} public recovery failed: {recovered.stderr}{recovered.stdout}"
            )
        result = json.loads(recovered.stdout)
        head = _head(result.get("head"), "recovery head")
        if (
            result.get("captured_head") != selected
            or result.get("commit_before") != selected
            or result.get("commit_after") != head
            or result.get("summary_head") != head
        ):
            raise RecoveryRehearsalRefused(
                "recovery did not report Commit(S,A) and a current summary"
            )
        final = log.read_bytes()
        if (
            not final.startswith(before)
            or _sha256(log, limit=prefix_size) != prefix_hash
        ):
            raise RecoveryRehearsalRefused("recovery changed pre-existing fork bytes")
        _reserved_anchor(log, selected, reserved, required=True)
        second = _child_recover(intent, _runtime_env(fork))
        if second.returncode != 3 or log.read_bytes() != final:
            raise RecoveryRehearsalRefused(
                "second recovery did not refuse without changing bytes"
            )
        results.append(
            {
                "phase": phase,
                "pre_adoption_error": preadoption_error,
                "selected_head": selected,
                "head": head,
                "prefix_sha256": prefix_hash,
                "second_recovery_error": json.loads(second.stdout)["error"],
            }
        )
    result = {
        "schema": "loops.rehearsal/arrival-recovery/v1",
        "status": "complete",
        "forks": results,
    }
    (output / "recovery-evidence.json").write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sandbox", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--observer")
    parser.add_argument("--namespace", default="arrival-rehearsal")
    parser.add_argument(
        "--child-adopt",
        nargs=7,
        metavar=(
            "VERTEX",
            "ROOT",
            "NAMESPACE",
            "REVIEWED",
            "HEAD",
            "OBSERVER",
            "PHASE",
        ),
    )
    parser.add_argument("--child-recover", metavar="INTENT")
    args = parser.parse_args(argv)
    if args.child_adopt is not None:
        return _child_adopt_main(args.child_adopt)
    if args.child_recover is not None:
        return _child_recover_main(args.child_recover)
    try:
        result = run(args)
    except (RecoveryRehearsalRefused, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"refused: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
