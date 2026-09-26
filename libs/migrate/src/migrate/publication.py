"""Offline, one-shot publication of an already-reviewed Arrival descriptor.

This module is deliberately file-only.  It neither opens an Arrival store nor
consults SDK, credentials, signers, or witness state.  The caller supplies the
reviewed adoption/provenance/quiescence assertions; this primitive records them
without treating a byte hash as verification of any of those assertions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.arrival_contract import Head
from engine.arrival_registry import descriptor_for
from lang import effective_store_clause, parse_vertex

__all__ = [
    "PublicationError",
    "PublicationRefused",
    "PublicationRequest",
    "PublicationResult",
    "publish_candidate_descriptor",
]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGE_SUFFIX = ".arrival-cutover"
_RECEIPT_VERSION = 1


@dataclass(frozen=True)
class PublicationRequest:
    """Pinned, offline inputs for one descriptor replacement.

    All paths must be absolute ``Path`` instances.  ``reviewed_adoption_head``,
    provenance, and quiescence references are caller assertions: this module
    has intentionally no authority to verify report signatures, adoption, or
    the caller's writer-quiescence record.
    """

    live_vertex: Path
    candidate_vertex: Path
    legacy_live_source: Path
    arrival_store: Path
    backup_path: Path
    receipt_path: Path
    live_vertex_sha256: str
    candidate_vertex_sha256: str
    legacy_source_sha256: str
    arrival_store_sha256: str
    reviewed_adoption_head: Head
    provenance_reference: str
    quiescence_transcript_reference: str


@dataclass(frozen=True)
class PublicationResult:
    """Observed outcome after replacement, directory sync, and receipt sync."""

    live_vertex: Path
    backup_path: Path
    receipt_path: Path
    live_vertex_sha256: str
    candidate_vertex_sha256: str
    backup_sha256: str
    reviewed_adoption_head: Head
    live_vertex_mode: int


class PublicationError(Exception):
    """A publication failure with machine-readable phase and replacement effect.

    Effects describe replacement, not all filesystem writes. ``not_attempted``
    may leave backup/stage artifacts. ``replace_entered_unknown`` means replace
    raised; ``replace_returned_unverified`` means it returned but directory sync
    or final verification failed. ``known_published`` requires both directory
    sync and verified live bytes/mode, but does not promise receipt completion
    or that a different process cannot subsequently change the live descriptor.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        effect: str,
        paths: dict[str, str] | None = None,
        pins: dict[str, str] | None = None,
    ) -> None:
        self.phase = phase
        self.effect = effect
        self.paths = dict(paths or {})
        self.pins = dict(pins or {})
        super().__init__(message)

    def as_dict(self) -> dict[str, object]:
        """Return payload-free, JSON-serializable failure identity and context."""
        return {
            "phase": self.phase,
            "effect": self.effect,
            "effect_scope": "live-descriptor-replacement",
            "message": str(self),
            "paths": self.paths,
            "pins": self.pins,
        }


class PublicationRefused(PublicationError):
    """A pre-replacement refusal; no call to ``os.replace`` was made."""

    def __init__(
        self,
        message: str,
        *,
        phase: str = "preflight",
        paths: dict[str, str] | None = None,
        pins: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message, phase=phase, effect="not_attempted", paths=paths, pins=pins)


def publish_candidate_descriptor(request: PublicationRequest) -> PublicationResult:
    """Atomically replace a quiescent live descriptor with an adopted candidate.

    Replacement is same-directory atomic only under the caller-held quiescence
    asserted in ``request``; it is not compare-and-swap.  Exclusive artifacts
    are retained on every failure as evidence.  A matching pre-existing backup
    is the sole reusable artifact; an existing stage or receipt always refuses.
    """
    paths, pins = _validate_request(request)
    stage = paths["live_vertex"].parent / f".{paths['live_vertex'].name}{_STAGE_SUFFIX}"
    paths = {**paths, "stage_path": stage}

    # Everything through this call is non-mutating preflight.
    _preflight(request, paths, pins, stage=stage, require_outputs_absent=True)
    live_mode = _file_mode(paths["live_vertex"], paths, pins, phase="preflight")
    live_bytes = _pinned_descriptor_bytes(
        paths["live_vertex"], pins["live_vertex_sha256"], "live vertex", paths, pins
    )
    candidate_bytes = _pinned_descriptor_bytes(
        paths["candidate_vertex"],
        pins["candidate_vertex_sha256"],
        "candidate vertex",
        paths,
        pins,
    )

    backup = paths["backup_path"]
    if _lexists(backup):
        try:
            _verify_and_sync_backup(backup, paths, pins)
        except OSError as exc:
            raise _refused("backup", f"existing backup sync failed: {exc}", paths, pins) from exc
    else:
        try:
            _write_exclusive_and_sync(backup, live_bytes)
            _sync_directory(backup.parent)
        except OSError as exc:
            raise _refused(
                "backup", f"exclusive backup creation failed: {exc}", paths, pins
            ) from exc
        _require_hash(backup, pins["live_vertex_sha256"], "backup", paths, pins, phase="backup")

    try:
        _write_exclusive_and_sync(stage, candidate_bytes, mode=live_mode)
        _sync_directory(stage.parent)
    except OSError as exc:
        raise _refused("stage", f"exclusive stage creation failed: {exc}", paths, pins) from exc
    _require_hash(stage, pins["candidate_vertex_sha256"], "stage", paths, pins, phase="stage")

    # Re-check source/store pins and exact descriptor semantics immediately
    # before entering replace.  Do not delete this stage on refusal.
    _preflight(request, paths, pins, stage=stage, require_outputs_absent=False)
    _require_hash(
        stage, pins["candidate_vertex_sha256"], "final stage", paths, pins,
        phase="final_preflight",
    )
    for path in (paths["live_vertex"], stage):
        if _file_mode(path, paths, pins, phase="final_preflight") != live_mode:
            raise _refused("final_preflight", "live or stage file mode changed", paths, pins)

    try:
        os.replace(stage, paths["live_vertex"])  # noqa: PTH105 -- required syscall boundary
    except OSError as exc:
        raise PublicationError(
            f"descriptor replacement raised after entry: {exc}",
            phase="replace",
            effect="replace_entered_unknown",
            paths=_path_strings(paths),
            pins=pins,
        ) from exc

    try:
        _sync_directory(paths["live_vertex"].parent)
    except OSError as exc:
        raise PublicationError(
            f"replacement returned, but live directory fsync failed: {exc}",
            phase="live_directory_fsync",
            effect="replace_returned_unverified",
            paths=_path_strings(paths),
            pins=pins,
        ) from exc

    try:
        _require_hash(
            paths["live_vertex"],
            pins["candidate_vertex_sha256"],
            "published live vertex",
            paths,
            pins,
            phase="final_live_verify",
        )
        if _file_mode(paths["live_vertex"], paths, pins, phase="final_live_verify") != live_mode:
            raise _refused("final_live_verify", "published file mode changed", paths, pins)
    except PublicationRefused as exc:
        raise PublicationError(
            "replacement returned and directory was synced, but final live "
            f"verification failed: {exc}",
            phase="final_live_verify",
            effect="replace_returned_unverified",
            paths=_path_strings(paths),
            pins=pins,
        ) from exc

    receipt = _receipt(request, paths, pins, live_mode=live_mode)
    try:
        _write_exclusive_and_sync(
            paths["receipt_path"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n",
        )
        _sync_directory(paths["receipt_path"].parent)
    except OSError as exc:
        raise PublicationError(
            f"descriptor is published, but receipt serialization or sync failed: {exc}",
            phase="receipt",
            effect="known_published",
            paths=_path_strings(paths),
            pins=pins,
        ) from exc

    return PublicationResult(
        live_vertex=paths["live_vertex"],
        backup_path=paths["backup_path"],
        receipt_path=paths["receipt_path"],
        live_vertex_sha256=pins["live_vertex_sha256"],
        candidate_vertex_sha256=pins["candidate_vertex_sha256"],
        backup_sha256=pins["live_vertex_sha256"],
        reviewed_adoption_head=request.reviewed_adoption_head,
        live_vertex_mode=live_mode,
    )


def _validate_request(request: PublicationRequest) -> tuple[dict[str, Path], dict[str, str]]:
    if not isinstance(request, PublicationRequest):
        raise PublicationRefused("request must be a PublicationRequest", phase="request")
    fields = (
        "live_vertex",
        "candidate_vertex",
        "legacy_live_source",
        "arrival_store",
        "backup_path",
        "receipt_path",
    )
    paths: dict[str, Path] = {}
    for field in fields:
        value = getattr(request, field)
        if not isinstance(value, Path) or not value.is_absolute():
            raise PublicationRefused(f"{field} must be an absolute Path", phase="request")
        # Keep the supplied leaf spelling for lstat/O_NOFOLLOW checks; canonical
        # comparisons happen separately so a leaf symlink cannot disappear here.
        paths[field] = value

    pin_fields = (
        "live_vertex_sha256",
        "candidate_vertex_sha256",
        "legacy_source_sha256",
        "arrival_store_sha256",
    )
    pins: dict[str, str] = {}
    for field in pin_fields:
        value = getattr(request, field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            raise PublicationRefused(
                f"{field} must be a lowercase SHA-256 hex digest", phase="request"
            )
        pins[field] = value

    head = request.reviewed_adoption_head
    if not isinstance(head, Head) or not isinstance(head.lineage, str) or not head.lineage.strip():
        raise PublicationRefused(
            "reviewed_adoption_head must carry nonempty lineage", phase="request"
        )
    if isinstance(head.ordinal, bool) or not isinstance(head.ordinal, int) or head.ordinal < 0:
        raise PublicationRefused(
            "reviewed_adoption_head.ordinal must be a nonnegative integer", phase="request"
        )
    if not isinstance(head.record_hash, str) or _SHA256.fullmatch(head.record_hash) is None:
        raise PublicationRefused(
            "reviewed_adoption_head.record_hash must be SHA-256 hex", phase="request"
        )
    for field in ("provenance_reference", "quiescence_transcript_reference"):
        value = getattr(request, field)
        if not isinstance(value, str) or not value.strip():
            raise PublicationRefused(f"{field} must be a nonempty string", phase="request")

    return paths, pins


def _preflight(
    request: PublicationRequest,
    paths: dict[str, Path],
    pins: dict[str, str],
    *,
    stage: Path,
    require_outputs_absent: bool,
) -> None:
    for name in ("live_vertex", "candidate_vertex", "legacy_live_source", "arrival_store"):
        _require_regular(paths[name], name, paths, pins)
    for name in ("backup_path", "receipt_path"):
        _require_parent(paths[name], name, paths, pins)
    _require_parent(stage, "stage_path", paths, pins)

    if _lexists(paths["receipt_path"]):
        raise _refused("preflight", "receipt path already exists", paths, pins)
    if require_outputs_absent and _lexists(stage):
        raise _refused("preflight", "exclusive stage path already exists", paths, pins)
    if not require_outputs_absent:
        _require_regular(stage, "stage_path", paths, pins)

    backup = paths["backup_path"]
    if _lexists(backup):
        _require_regular(backup, "backup_path", paths, pins)
        _require_hash(backup, pins["live_vertex_sha256"], "existing backup", paths, pins)
    _check_aliases(paths, stage, pins)

    _require_hash(paths["live_vertex"], pins["live_vertex_sha256"], "live vertex", paths, pins)
    _require_hash(
        paths["candidate_vertex"], pins["candidate_vertex_sha256"], "candidate vertex", paths, pins
    )
    _require_hash(
        paths["legacy_live_source"], pins["legacy_source_sha256"], "legacy live source", paths, pins
    )
    _require_hash(
        paths["arrival_store"], pins["arrival_store_sha256"], "Arrival store", paths, pins
    )
    _validate_descriptors(request, paths, pins)


def _validate_descriptors(
    request: PublicationRequest, paths: dict[str, Path], pins: dict[str, str]
) -> None:
    try:
        original_bytes = _pinned_descriptor_bytes(
            paths["live_vertex"], pins["live_vertex_sha256"], "live vertex", paths, pins
        )
        candidate_bytes = _pinned_descriptor_bytes(
            paths["candidate_vertex"],
            pins["candidate_vertex_sha256"],
            "candidate vertex",
            paths,
            pins,
        )
        original = original_bytes.decode("utf-8")
        candidate = candidate_bytes.decode("utf-8")
        original_ast = parse_vertex(original, paths["live_vertex"])
        candidate_ast = parse_vertex(candidate, paths["candidate_vertex"])
        original_span = effective_store_clause(original, paths["live_vertex"])
        candidate_span = effective_store_clause(candidate, paths["candidate_vertex"])
    except PublicationRefused:
        raise
    except Exception as exc:
        # parse errors are intentionally normalized into payload-free refusal.
        raise _refused(
            "descriptor", f"pinned descriptor cannot be parsed ({type(exc).__name__})", paths, pins
        ) from exc
    if original_span.count != 1 or original_ast.store is None:
        raise _refused(
            "descriptor", "original descriptor lacks one unambiguous store clause", paths, pins
        )
    if original_ast.store_backend is not None:
        raise _refused(
            "descriptor", "original must be legacy, not an Arrival transfer", paths, pins
        )
    original_source = original_ast.store
    if not original_source.is_absolute():
        original_source = paths["live_vertex"].parent / original_source
    _require_regular(original_source, "original declared source", paths, pins)
    if original_source.resolve() != paths["legacy_live_source"].resolve():
        raise _refused(
            "descriptor",
            "original descriptor does not identify supplied legacy source",
            paths,
            pins,
        )
    if (
        candidate_span.count != 1
        or candidate_ast.store is None
        or candidate_ast.store_backend is None
    ):
        raise _refused(
            "descriptor", "candidate lacks one unambiguous explicit store descriptor", paths, pins
        )
    if not candidate_ast.store.is_absolute():
        raise _refused(
            "descriptor", "candidate store location is not textually absolute", paths, pins
        )
    backend = candidate_ast.store_backend
    if backend.name != "file" or backend.role != "authority":
        raise _refused(
            "descriptor", "candidate must declare file backend and authority role", paths, pins
        )
    if backend.lineage != request.reviewed_adoption_head.lineage:
        raise _refused(
            "descriptor", "candidate lineage does not equal reviewed adoption head", paths, pins
        )
    try:
        descriptor = descriptor_for(candidate_ast, paths["candidate_vertex"])
    except Exception as exc:
        raise _refused(
            "descriptor", f"candidate descriptor resolution failed: {exc}", paths, pins
        ) from exc
    _require_regular(candidate_ast.store, "candidate declared store", paths, pins)
    # Absolute File locations retain their spelling at the backend boundary.
    # An equivalent path through an alias is not the reviewed residence.
    if descriptor is None or Path(descriptor.location) != paths["arrival_store"]:
        raise _refused(
            "descriptor", "candidate must name the exact final Arrival path", paths, pins
        )


def _check_aliases(paths: dict[str, Path], stage: Path, pins: dict[str, str]) -> None:
    roles = {name: path.resolve() for name, path in paths.items() if name != "stage_path"}
    roles["stage_path"] = stage.resolve()
    names = list(roles)
    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            if roles[left] == roles[right]:
                raise _refused("preflight", f"path roles alias: {left} and {right}", paths, pins)
    existing: list[tuple[str, os.stat_result]] = []
    for name, path in roles.items():
        if _lexists(path):
            try:
                existing.append((name, path.stat(follow_symlinks=False)))
            except OSError as exc:
                raise _refused("preflight", f"cannot stat {name}: {exc}", paths, pins) from exc
    for index, (left, left_stat) in enumerate(existing):
        for right, right_stat in existing[index + 1 :]:
            if (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino):
                raise _refused("preflight", f"hard-link aliases: {left} and {right}", paths, pins)


def _require_parent(path: Path, name: str, paths: dict[str, Path], pins: dict[str, str]) -> None:
    try:
        parent_stat = path.parent.stat()
    except OSError as exc:
        raise _refused("preflight", f"{name} parent is unavailable: {exc}", paths, pins) from exc
    if not stat.S_ISDIR(parent_stat.st_mode):
        raise _refused("preflight", f"{name} parent is not a directory", paths, pins)


def _require_regular(path: Path, name: str, paths: dict[str, Path], pins: dict[str, str]) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise _refused("preflight", f"{name} is unavailable: {exc}", paths, pins) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise _refused("preflight", f"{name} must be a regular non-symlink file", paths, pins)


def _sha256_file(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("not a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(fd)


def _read_regular_bytes(path: Path, name: str) -> bytes:
    # Descriptors are intentionally small parse inputs; source/store pins use
    # _sha256_file's streaming path and are never loaded for hashing.
    try:
        _require_regular(path, name, {name: path}, {})
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("not a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)
    except PublicationRefused:
        raise
    except OSError as exc:
        raise PublicationRefused(f"cannot read {name}: {exc}", phase="preflight") from exc


def _pinned_descriptor_bytes(
    path: Path,
    expected: str,
    name: str,
    paths: dict[str, Path],
    pins: dict[str, str],
) -> bytes:
    data = _read_regular_bytes(path, name)
    if hashlib.sha256(data).hexdigest() != expected:
        raise _refused(
            "preflight", f"{name} SHA-256 does not match its independent pin", paths, pins
        )
    return data


def _require_hash(
    path: Path, expected: str, name: str, paths: dict[str, Path], pins: dict[str, str],
    *, phase: str = "preflight",
) -> None:
    try:
        actual = _sha256_file(path)
    except OSError as exc:
        raise _refused(phase, f"cannot hash {name}: {exc}", paths, pins) from exc
    if actual != expected:
        raise _refused(phase, f"{name} SHA-256 does not match its independent pin", paths, pins)


def _file_mode(
    path: Path, paths: dict[str, Path], pins: dict[str, str], *, phase: str
) -> int:
    try:
        info = path.lstat()
    except OSError as exc:
        raise _refused(phase, f"cannot inspect file mode: {exc}", paths, pins) from exc
    if not stat.S_ISREG(info.st_mode):
        raise _refused(phase, "file mode requires a regular non-symlink file", paths, pins)
    return stat.S_IMODE(info.st_mode)


def _write_exclusive_and_sync(path: Path, data: bytes, *, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written == 0:
                raise OSError("exclusive artifact write made no progress")
            offset += written
        # Keep incomplete content private; apply the publication mode only after
        # the full write. Backups and receipts retain the default private mode.
        os.fchmod(fd, mode)
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(directory, flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _verify_and_sync_backup(
    backup: Path, paths: dict[str, Path], pins: dict[str, str]
) -> None:
    _require_hash(
        backup, pins["live_vertex_sha256"], "existing backup", paths, pins, phase="backup"
    )
    fd = os.open(backup, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    _sync_directory(backup.parent)


def _receipt(
    request: PublicationRequest, paths: dict[str, Path], pins: dict[str, str], *, live_mode: int
) -> dict[str, Any]:
    head = request.reviewed_adoption_head
    return {
        "version": _RECEIPT_VERSION,
        "operation": "offline-candidate-descriptor-publication",
        "replacement": {
            "state": "returned-and-live-directory-synced",
            "atomicity": "same-directory replacement under caller-held quiescence; not CAS",
        },
        "observed": {
            "paths": {name: str(path) for name, path in paths.items() if name != "stage_path"},
            "file_modes": {"live_vertex_before": live_mode, "live_vertex_after": live_mode},
            "sha256": {
                "live_vertex_before": pins["live_vertex_sha256"],
                "candidate_vertex": pins["candidate_vertex_sha256"],
                "legacy_live_source": pins["legacy_source_sha256"],
                "arrival_store": pins["arrival_store_sha256"],
                "backup": pins["live_vertex_sha256"],
                "live_vertex_after": pins["candidate_vertex_sha256"],
            },
            "candidate_descriptor": {
                "backend": "file",
                "role": "authority",
                "lineage": head.lineage,
                "location": str(paths["arrival_store"]),
            },
        },
        "caller_assertions_not_verified_here": {
            "reviewed_adoption_head": {
                "lineage": head.lineage,
                "ordinal": head.ordinal,
                "record_hash": head.record_hash,
            },
            "provenance_reference": request.provenance_reference,
            "quiescence_transcript_reference": request.quiescence_transcript_reference,
            "note": (
                "store hashing does not verify adoption A, report signatures, "
                "provenance, or quiescence"
            ),
        },
    }


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _path_strings(paths: dict[str, Path]) -> dict[str, str]:
    return {name: str(path) for name, path in paths.items()}


def _refused(
    phase: str, message: str, paths: dict[str, Path], pins: dict[str, str]
) -> PublicationRefused:
    return PublicationRefused(message, phase=phase, paths=_path_strings(paths), pins=pins)
