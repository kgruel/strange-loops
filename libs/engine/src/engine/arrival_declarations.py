"""Prepare, apply, and recover signed declaration edits on Arrival.

Preparation captures one attested read basis and exact signed records. Apply
uses a durable intent and full-head CAS; recovery reconciles a known suffix and
finishes projection/cache work without resigning or overwriting competing data.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from lang import diff_documents, parse_vertex, validate_vertex, vertex_to_documents
from lang.document import DECL_OBSERVER_DEFINED, Change
from ulid import ULID

from .admission import fact_commitment_hash
from .arrival import (
    ArrivalError,
    content_commitment,
    key_registry_from_records,
)
from .arrival_body import body_of_batch, body_of_fact_row
from .arrival_boundary_continuity import (
    BoundaryContinuityConflict,
    analyze_boundary_continuity,
    collect_verified_parameter_rows,
)
from .arrival_contract import (
    ArrivalLedger,
    ArrivalQuery,
    AtomicLimitExceeded,
    FactRequest,
    Head,
    Profile,
    ProjectionBehind,
    ProjectionRequirement,
    ReadBasis,
    RecordDraft,
    StoreDescriptor,
    TickRequest,
    Watermark,
)
from .arrival_head_seam import (
    Compared,
    Indeterminate,
    PreGenesis,
    complete_projection_custody,
)
from .arrival_registry import BackendRegistry
from .credentials import WriteCredentials
from .declaration import (
    Unhistorized,
    resolve_declaration_documents_from_snapshot,
    validate_arrival_declaration_anchor,
    validate_arrival_runtime_identity,
)

__all__ = [
    "DeclarationPreparationError",
    "DeclarationPreparationRefused",
    "DeclarationEditPlan",
    "DeclarationEditResult",
    "DeclarationApplyError",
    "DeclarationStale",
    "DeclarationNotApplied",
    "DeclarationOutcomeUnknown",
    "DeclarationUnwitnessed",
    "DeclarationCommittedIncomplete",
    "declaration_intent_path",
    "prepare_declaration_edit",
    "apply_declaration_edit",
    "recover_declaration_edit",
]


class DeclarationPreparationError(ArrivalError):
    """The declaration edit could not be prepared without mutation."""


class DeclarationPreparationRefused(DeclarationPreparationError):
    """A declaration edit input or signed draft failed a preparation gate."""

    def __init__(
        self,
        *args: object,
        coordinator_phase: str | None = None,
        effects: Mapping[str, Mapping[str, str]] | None = None,
        captured_head: Head | None = None,
        projected_head: Head | None = None,
    ) -> None:
        super().__init__(*args)
        self.coordinator_phase = coordinator_phase
        self.effects = effects
        if captured_head is not None:
            self.captured_head = captured_head
        if projected_head is not None:
            self.projected_head = projected_head


def _preparation_refused(
    message: str,
    *,
    captured_head: Head | None = None,
    projected_head: Head | None = None,
) -> DeclarationPreparationRefused:
    return DeclarationPreparationRefused(
        message,
        coordinator_phase="prepare",
        effects={
            "custody": {"attempt": "not-entered", "state": "not-attempted"}
        },
        captured_head=captured_head,
        projected_head=projected_head,
    )


class DeclarationApplyError(ArrivalError):
    """A declaration apply or recovery operation could not complete."""


class DeclarationStale(DeclarationApplyError):
    """The captured full head or declaration cache moved before append."""


class DeclarationNotApplied(DeclarationApplyError):
    """A durable prepared intent is proven to have reached no append."""


class DeclarationOutcomeUnknown(DeclarationApplyError):
    """Append transport failed without proving whether the records landed."""

    def __init__(self, message: str, *, head: Head | None, intent_path: Path,
                 fact_ids: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(message)
        self.head = head
        self.intent_path = intent_path
        self.fact_ids = fact_ids
        self.cause = cause


class DeclarationUnwitnessed(DeclarationApplyError):
    """Append committed, but its custody journal witness was unavailable."""

    def __init__(self, message: str, *, head: Head, commit: Any,
                 intent_path: Path, fact_ids: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(message)
        self.head = head
        self.commit = commit
        self.intent_path = intent_path
        self.fact_ids = fact_ids
        self.cause = cause


class DeclarationCommittedIncomplete(DeclarationApplyError):
    """Append is known durable, but sync/publication/cleanup remains pending."""

    def __init__(self, message: str, *, phase: str, head: Head,
                 commit: Any, intent_path: Path, fact_ids: tuple[str, ...],
                 cause: BaseException) -> None:
        super().__init__(message)
        self.phase = phase
        self.head = head
        self.commit = commit
        self.intent_path = intent_path
        self.fact_ids = fact_ids
        self.cause = cause


@dataclass(frozen=True)
class DeclarationEditPlan:
    """Exact, signed declaration transition prepared against one Arrival head."""

    status: Literal["planned", "noop"]
    target_path: Path
    descriptor: StoreDescriptor
    lineage: str
    basis: ReadBasis
    captured_head: Head
    before_documents: tuple[Mapping[str, Any], ...]
    proposed_documents: tuple[Mapping[str, Any], ...]
    changes: tuple[Change, ...]
    authored_at: float | None
    observer: str
    drafts: tuple[RecordDraft, ...]
    fact_ids: tuple[str, ...]
    key_introductions: tuple[str, ...]
    old_cache_bytes: bytes
    old_cache_sha256: str
    proposed_text: str
    atomic_limit: int | None
    exact_drafts: str


@dataclass(frozen=True)
class DeclarationEditResult:
    """Apply/recovery outcome with exact identity and reconciliation evidence.

    ``file_written`` reports publication by this invocation. ``phase`` reports
    the reconciled operation state, including an already-published cache.
    """

    status: Literal[
        "noop", "applied", "stale", "refused", "unknown", "unwitnessed",
        "committed-incomplete", "recovered", "not-applied", "conflict",
    ]
    target_path: Path
    descriptor: StoreDescriptor
    lineage: str
    basis: ReadBasis
    captured_head: Head
    head: Head | None
    commit: Any | None
    fact_ids: tuple[str, ...]
    intent_path: Path | None
    phase: str
    file_written: bool
    changes: tuple[Change, ...] | None


def _close_quietly(handle: object | None) -> None:
    if handle is None:
        return
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _draft_to_dict(draft: RecordDraft) -> dict[str, Any]:
    return {
        "kind": draft.kind,
        "authored_at": draft.authored_at,
        "observer": draft.observer,
        "origin": draft.origin,
        "body": dict(draft.body),
        "signature": draft.signature,
    }


def _exact_drafts(drafts: Sequence[RecordDraft]) -> str:
    """Canonical preparation snapshot used to detect nested plan mutation."""
    return json.dumps(
        [_draft_to_dict(draft) for draft in drafts],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def declaration_intent_path(target: Path | str) -> Path:
    """The exclusive durable sidecar for one declaration edit."""
    target_path = Path(target).resolve()
    return target_path.with_name(target_path.name + ".arrival-decl.intent")


def _declaration_lock_path(target: Path) -> Path:
    return target.with_name(target.name + ".arrival-decl.lock")


@contextmanager
def _declaration_lock(target: Path):
    """Serialize apply/recovery while releasing the lock on process death."""
    lock_path = _declaration_lock_path(target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)


def _head_dict(head: Head | None) -> dict[str, Any] | None:
    if head is None:
        return None
    return {
        "lineage": head.lineage,
        "ordinal": head.ordinal,
        "record_hash": head.record_hash,
    }


def _descriptor_dict(descriptor: StoreDescriptor) -> dict[str, Any]:
    return {
        "backend": descriptor.backend,
        "location": descriptor.location,
        "lineage": descriptor.lineage,
        "role": None if descriptor.role is None else descriptor.role.value,
        "query": descriptor.query,
        "witness": descriptor.witness,
    }


def _descriptor_from(data: Mapping[str, Any]) -> StoreDescriptor:
    role = data.get("role")
    return StoreDescriptor(
        backend=str(data["backend"]),
        location=str(data["location"]),
        lineage=data.get("lineage"),
        role=None if role is None else Profile(str(role)),
        query=data.get("query"),
        witness=data.get("witness"),
    )


def _intent_data(plan: DeclarationEditPlan, *, phase: str) -> dict[str, Any]:
    return {
        "schema": "loops.engine/arrival-declaration-intent/v1",
        "phase": phase,
        "target": str(plan.target_path),
        "descriptor": _descriptor_dict(plan.descriptor),
        "lineage": plan.lineage,
        "captured_head": _head_dict(plan.captured_head),
        "basis": {
            "lineage": plan.basis.lineage,
            "captured_head": _head_dict(plan.basis.captured_head),
            "projected_through": _head_dict(plan.basis.projected_through),
            "view_generation": plan.basis.view_generation,
        },
        "observer": plan.observer,
        "fact_ids": list(plan.fact_ids),
        "drafts": json.loads(plan.exact_drafts),
        "exact_drafts": plan.exact_drafts,
        "old_cache_b64": base64.b64encode(plan.old_cache_bytes).decode("ascii"),
        "old_cache_sha256": plan.old_cache_sha256,
        "proposed_text": plan.proposed_text,
        "key_introductions": list(plan.key_introductions),
    }


def _fsync_parent(path: Path) -> None:
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        raise
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_exclusive_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_parent(path)
    except BaseException:
        with suppress(FileNotFoundError):
            path.unlink()
        raise


def _replace_json(path: Path, data: Mapping[str, Any]) -> None:
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(path)
        _fsync_parent(path)
    finally:
        with suppress(FileNotFoundError):
            temp.unlink()


def _read_intent(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DeclarationApplyError(f"cannot read declaration intent {path}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("schema") != "loops.engine/arrival-declaration-intent/v1"
    ):
        raise DeclarationApplyError(f"malformed declaration intent: {path}")
    return data


def _drafts_from_intent(data: Mapping[str, Any]) -> tuple[RecordDraft, ...]:
    return _drafts_from_exact(
        data["drafts"],
        str(data.get("exact_drafts", "")),
    )


def _drafts_from_exact(raw: Any, expected_exact: str) -> tuple[RecordDraft, ...]:
    if not isinstance(raw, list):
        raise DeclarationApplyError("declaration intent drafts are not a list")
    drafts = tuple(
        RecordDraft(
            kind=str(item["kind"]),
            authored_at=float(item["authored_at"]),
            observer=str(item["observer"]),
            origin=str(item["origin"]),
            body=dict(item["body"]),
            signature=item.get("signature"),
        )
        for item in raw
    )
    actual_exact = _exact_drafts(drafts)
    if actual_exact != expected_exact:
        raise DeclarationApplyError("declaration intent draft bytes do not verify")
    return drafts


def _record_matches_draft(record: Mapping[str, Any], draft: RecordDraft) -> bool:
    return (
        record.get("k") == draft.kind
        and record.get("at") == draft.authored_at
        and record.get("observer") == draft.observer
        and record.get("origin") == draft.origin
        and record.get("body") == dict(draft.body)
        and record.get("sig") == draft.signature
    )


def _unique_sibling(path: Path, label: str) -> Path:
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.{label}.", dir=path.parent)
    os.close(fd)
    candidate = Path(raw)
    candidate.unlink()
    return candidate


def _create_cache_temp(path: Path, content: bytes) -> None:
    """Create and fsync a complete proposal without replacing an existing path."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_parent(path)
    except BaseException:
        with suppress(FileNotFoundError):
            path.unlink()
        raise


def _verify_cache_temp(path: Path, expected: bytes) -> None:
    """Validate bytes and re-fsync a temp that survived a crash boundary."""
    with path.open("rb") as stream:
        if stream.read() != expected:
            raise DeclarationStale(
                "prepared declaration cache temp bytes differ from the proposal"
            )
        os.fsync(stream.fileno())
    _fsync_parent(path)


def _publish_cache(
    plan: DeclarationEditPlan,
    *,
    intent: Path,
    intent_data: dict[str, Any],
    failure_hook: Callable[[str], None] | None,
) -> None:
    """Detach the verified old cache, then exclusively link a full new file."""
    target = plan.target_path
    temp = (
        Path(intent_data["cache_temp"])
        if intent_data.get("cache_temp")
        else _unique_sibling(target, "cache")
    )
    backup = (
        Path(intent_data["cache_backup"])
        if intent_data.get("cache_backup")
        else _unique_sibling(target, "backup")
    )
    intent_data["cache_temp"] = str(temp)
    intent_data["cache_backup"] = str(backup)
    _replace_json(intent, intent_data)
    try:
        proposed = plan.proposed_text.encode("utf-8")
        if temp.exists():
            _verify_cache_temp(temp, proposed)
        else:
            _create_cache_temp(temp, proposed)
            if failure_hook:
                failure_hook("after-cache-temp")
        if target.exists():
            current = target.read_bytes()
            if current != plan.old_cache_bytes:
                raise DeclarationStale(
                    "declaration cache changed after preparation; refusing publication"
                )
            if backup.exists():
                raise DeclarationApplyError(
                    "a prior cache publication left a backup beside the live declaration"
                )
            target.rename(backup)
            _fsync_parent(target)
        elif not backup.exists():
            raise DeclarationApplyError(
                "declaration cache is absent without the verified detached backup"
            )
        if failure_hook:
            failure_hook("after-cache-detach")
        if backup.read_bytes() != plan.old_cache_bytes:
            raise DeclarationApplyError(
                "detached declaration cache bytes differ from prepared evidence"
            )
        os.link(temp, target)
        temp.unlink()
        _fsync_parent(target)
        if failure_hook:
            failure_hook("after-cache-link")
        with suppress(FileNotFoundError):
            backup.unlink()
        _fsync_parent(backup)
    except BaseException:
        raise


def _cleanup_cache_artifacts(
    plan: DeclarationEditPlan, intent_data: Mapping[str, Any]
) -> None:
    """Remove only verified publication leftovers after the new cache is live."""
    proposed = plan.proposed_text.encode("utf-8")
    for field, expected in (
        ("cache_temp", proposed),
        ("cache_backup", plan.old_cache_bytes),
    ):
        raw = intent_data.get(field)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.exists():
            continue
        if path.read_bytes() != expected:
            raise DeclarationStale(
                f"declaration publication artifact {path} does not match its intent"
            )
        path.unlink()
        _fsync_parent(path)


def _plan_from_intent(
    data: Mapping[str, Any], drafts: tuple[RecordDraft, ...]
) -> DeclarationEditPlan:
    captured_data = data["captured_head"]
    captured = Head(
        lineage=str(captured_data["lineage"]),
        ordinal=int(captured_data["ordinal"]),
        record_hash=str(captured_data["record_hash"]),
    )
    old_bytes = base64.b64decode(data["old_cache_b64"], validate=True)
    if hashlib.sha256(old_bytes).hexdigest() != data["old_cache_sha256"]:
        raise DeclarationApplyError("declaration intent cache bytes do not verify")
    basis_data = data.get("basis")
    if basis_data is None:
        basis = ReadBasis(
            lineage=captured.lineage,
            captured_head=captured,
            projected_through=None,
            view_generation=None,
        )
    else:
        if not isinstance(basis_data, Mapping):
            raise DeclarationApplyError("declaration intent basis is malformed")
        basis_captured_data = basis_data.get("captured_head")
        if not isinstance(basis_captured_data, Mapping):
            raise DeclarationApplyError("declaration intent captured basis is malformed")
        basis_captured = Head(
            lineage=str(basis_captured_data["lineage"]),
            ordinal=int(basis_captured_data["ordinal"]),
            record_hash=str(basis_captured_data["record_hash"]),
        )
        projected_data = basis_data.get("projected_through")
        projected = None
        if projected_data is not None:
            if not isinstance(projected_data, Mapping):
                raise DeclarationApplyError(
                    "declaration intent projected basis is malformed"
                )
            projected = Head(
                lineage=str(projected_data["lineage"]),
                ordinal=int(projected_data["ordinal"]),
                record_hash=str(projected_data["record_hash"]),
            )
        view_generation = basis_data.get("view_generation")
        if view_generation is not None and not isinstance(view_generation, str):
            raise DeclarationApplyError(
                "declaration intent basis view generation is malformed"
            )
        basis = ReadBasis(
            lineage=str(basis_data["lineage"]),
            captured_head=basis_captured,
            projected_through=projected,
            view_generation=view_generation,
        )
        if (
            basis.lineage != captured.lineage
            or basis.captured_head != captured
            or basis.projected_through != captured
        ):
            raise DeclarationStale(
                "declaration intent basis disagrees with its CURRENT predecessor head"
            )
    return DeclarationEditPlan(
        status="planned",
        target_path=Path(data["target"]).resolve(),
        descriptor=_descriptor_from(data["descriptor"]),
        lineage=str(data["lineage"]),
        basis=basis,
        captured_head=captured,
        before_documents=(),
        proposed_documents=(),
        changes=(),
        authored_at=drafts[0].authored_at if drafts else None,
        observer=str(data["observer"]),
        drafts=drafts,
        fact_ids=tuple(str(value) for value in data["fact_ids"]),
        key_introductions=tuple(str(value) for value in data.get("key_introductions", ())),
        old_cache_bytes=old_bytes,
        old_cache_sha256=str(data["old_cache_sha256"]),
        proposed_text=str(data["proposed_text"]),
        atomic_limit=None,
        exact_drafts=str(data["exact_drafts"]),
    )


def _descriptor_location(target: Path, ast: Any, descriptor: StoreDescriptor) -> str:
    backend = ast.store_backend
    if backend is None:
        raise _preparation_refused(
            "proposed declaration has no explicit store backend"
        )
    if descriptor.backend == "file":
        if ast.store is None:
            raise _preparation_refused(
                "proposed file declaration has no store location"
            )
        return str((target.parent / str(ast.store)).resolve())
    if ast.store_location is None:
        raise _preparation_refused(
            "proposed non-file declaration has no opaque store location"
        )
    return str(ast.store_location)


def _validate_residence(target: Path, ast: Any, descriptor: StoreDescriptor) -> None:
    if descriptor.role is not Profile.AUTHORITY:
        raise _preparation_refused(
            "declaration edits require an Authority descriptor"
        )
    if descriptor.lineage is None:
        raise _preparation_refused(
            "declaration edit descriptor must pin a lineage"
        )
    backend = ast.store_backend
    if (
        backend is None
        or backend.name != descriptor.backend
        or backend.lineage != descriptor.lineage
        or backend.role != Profile.AUTHORITY.value
    ):
        raise _preparation_refused(
            "proposed declaration residence must preserve backend, lineage and authority role"
        )
    if _descriptor_location(target, ast, descriptor) != descriptor.location:
        raise _preparation_refused(
            "proposed declaration residence must preserve the descriptor location"
        )


def _key_is_well_formed(key: object) -> bool:
    if not isinstance(key, str) or not key:
        return False
    try:
        return len(base64.b64decode(key, validate=True)) == 32
    except (ValueError, TypeError):
        return False


def _valid_author_keys(registry: Any, observer: str, head: Head) -> tuple[str, ...]:
    return tuple(
        key for key, _introduced in registry.keys_valid_at(observer, head.ordinal + 1)
    )


def _signed_with_existing_key(
    *,
    signer: Callable[[str, str], str | None] | None,
    verifier: Callable[[str, str, str], bool],
    registry: Any,
    author: str,
    head: Head,
    digest: str,
    label: str,
) -> str:
    if not callable(signer):
        raise _preparation_refused(f"missing {label} signer")
    keys = _valid_author_keys(registry, author, head)
    if not keys:
        raise _preparation_refused(
            f"edit author {author!r} has no key valid at the captured Arrival head"
        )
    signature = signer(author, digest)
    if not signature:
        raise _preparation_refused(f"missing {label} signature")
    if not any(verifier(key, signature, digest) for key in keys):
        raise _preparation_refused(
            f"{label} signature does not verify under a key valid for edit author "
            f"{author!r} at the captured Arrival head"
        )
    return signature


def _declaration_row(
    change: Change,
    *,
    lineage: str,
    authored_at: float,
    observer: str,
    credentials: WriteCredentials,
    registry: Any,
    captured_head: Head,
    fact_verify: Callable[[str, str, str], bool],
) -> tuple[str, tuple[Any, ...]]:
    row_payload: dict[str, Any] = {
        "lineage": lineage,
        "subject": change.subject,
        "change": change.annotation,
    }
    if change.payload is not None:
        row_payload["payload"] = dict(change.payload)
    payload_text = json.dumps(row_payload, ensure_ascii=False, separators=(",", ":"))
    fact_id = str(ULID())
    fact_digest = fact_commitment_hash(
        change.kind, authored_at, observer, "", payload_text
    )
    inner_signature = _signed_with_existing_key(
        signer=credentials.fact_signer,
        verifier=fact_verify,
        registry=registry,
        author=observer,
        head=captured_head,
        digest=fact_digest,
        label="FACT",
    )
    row = (
        fact_id,
        change.kind,
        authored_at,
        observer,
        "",
        payload_text,
        inner_signature,
    )
    return fact_id, row


def _key_draft(
    author: str,
    observer: str,
    key: str,
    *,
    authored_at: float,
    credentials: WriteCredentials,
    registry: Any,
    captured_head: Head,
    arrival_verify: Callable[[str, str, str], bool],
) -> RecordDraft:
    body = {"observer": observer, "key": key}
    digest = content_commitment("key", authored_at, author, "", body)
    signature = _signed_with_existing_key(
        signer=credentials.arrival_signer,
        verifier=arrival_verify,
        registry=registry,
        author=author,
        head=captured_head,
        digest=digest,
        label="Arrival key-introduction",
    )
    return RecordDraft(
        kind="key",
        authored_at=authored_at,
        observer=author,
        origin="",
        body=body,
        signature=signature,
    )


def prepare_declaration_edit(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *,
    target: Path | str,
    proposed_text: str,
    observer: str,
    credentials: WriteCredentials | None,
    fact_verify: Callable[[str, str, str], bool],
    arrival_verify: Callable[[str, str, str], bool],
    source_cache_bytes: bytes | None = None,
    require_cache_basis: bool = False,
) -> DeclarationEditPlan:
    """Prepare one exact declaration transition against an attested CURRENT head.

    This function only reads and signs in memory. It creates no intent, does
    not append, and does not touch the declaration cache. The registry opener
    is expected to return an attested custody handle; its ``scan`` is the
    structurally verified genesis-through-head sequence required by the
    iterable authorship seam.
    """
    target_path = Path(target).resolve()
    if not isinstance(proposed_text, str) or not proposed_text:
        raise _preparation_refused("proposed declaration text is empty")
    try:
        old_cache_bytes = target_path.read_bytes()
    except OSError as exc:
        raise _preparation_refused(
            f"cannot read declaration cache {target_path}: {exc}"
        ) from exc
    if source_cache_bytes is not None and old_cache_bytes != source_cache_bytes:
        raise _preparation_refused(
            "declaration cache changed while preparing the requested splice"
        )
    try:
        ast = parse_vertex(proposed_text, path=target_path)
        validate_vertex(ast)
    except Exception as exc:
        raise _preparation_refused(
            f"proposed declaration is not valid Vertex grammar/semantics: {exc}"
        ) from exc
    validate_arrival_runtime_identity(
        ast.name,
        ast.loops,
        refusal=_preparation_refused,
    )
    _validate_residence(target_path, ast, descriptor)
    proposed_documents = tuple(
        document.as_json() for document in vertex_to_documents(ast)
    )

    ledger: ArrivalLedger | None = None
    query: ArrivalQuery | None = None
    snapshot: Any | None = None
    atomic_limit: int | None = None
    captured_head: Head | None = None
    try:
        ledger, query = registry.open(descriptor)
        report = getattr(ledger, "opened", None)
        comparison = getattr(report, "comparison", None)
        if isinstance(comparison, PreGenesis):
            if comparison.ledger_refusal is not None:
                raise _preparation_refused(
                    f"Arrival ledger is not opened: {comparison.ledger_refusal}"
                )
            raise _preparation_refused(
                "Arrival ledger has no captured head for declaration editing"
            )
        if isinstance(comparison, Indeterminate):
            raise _preparation_refused(
                f"Arrival head attestation is indeterminate: {comparison.refusal}"
            )
        if not isinstance(comparison, Compared):
            raise _preparation_refused(
                "registry opener did not provide a compared Arrival head"
            )
        captured_head = comparison.presented
        snapshot = query.open_snapshot(
            captured_head=captured_head,
            requirement=ProjectionRequirement.CURRENT,
            continuation=None,
        )
        validate_arrival_declaration_anchor(
            snapshot.declaration_anchor, captured_head
        )
        facts = snapshot.facts(
            FactRequest(
                limit=None,
                kind="_decl",
                include_internal=True,
                order="oldest",
            )
        ).items
        documents = resolve_declaration_documents_from_snapshot(
            snapshot.declaration_anchor, facts
        )
        if documents is None or isinstance(documents, Unhistorized):
            raise _preparation_refused(
                "the CURRENT Arrival snapshot has no historized declaration"
            )
        represented = snapshot.represented
        if represented is None:
            raise _preparation_refused(
                "the CURRENT declaration snapshot has no matching lineage basis"
            )
        projected = complete_projection_custody(
            ledger,
            captured=captured_head,
            represented=represented,
            lineage_refusal=lambda message: _preparation_refused(message),
            conflict_refusal=lambda message: _preparation_refused(message),
        )
        if projected.ordinal < captured_head.ordinal:
            behind = ProjectionBehind(
                "the CURRENT declaration snapshot is behind the captured Arrival head"
            )
            behind.captured_head = captured_head
            behind.projected_head = projected
            raise behind
        basis = ReadBasis(
            lineage=captured_head.lineage,
            captured_head=captured_head,
            projected_through=projected,
            view_generation=getattr(snapshot, "view_generation", None),
        )
        before_documents = tuple(dict(document) for document in documents)
        if require_cache_basis:
            try:
                local_ast = parse_vertex(
                    old_cache_bytes.decode("utf-8"), path=target_path
                )
                local_documents = tuple(
                    document.as_json() for document in vertex_to_documents(local_ast)
                )
            except Exception as exc:
                raise _preparation_refused(
                    f"current declaration cache is not valid for this splice: {exc}"
                ) from exc
            if local_documents != before_documents:
                raise _preparation_refused(
                    "declaration cache differs from CURRENT Arrival history; "
                    "convenience mutation refused"
                )
        changes = tuple(diff_documents(before_documents, proposed_documents))
        continuity_ticks = tuple(
            snapshot.ticks(TickRequest(since=float("-inf")))
        )
        verified_params = collect_verified_parameter_rows(
            snapshot.declaration_anchor,
            facts,
            target_documents=proposed_documents,
            base_dir=target_path.parent,
        )
        analyze_boundary_continuity(
            snapshot.declaration_anchor,
            facts,
            continuity_ticks,
            target_documents=proposed_documents,
            verified_params=verified_params,
        )
        key_registry, _key_evidence = key_registry_from_records(
            ledger.scan(through=captured_head), arrival_verify
        )
        atomic_limit = ledger.capabilities().max_atomic_records
    except DeclarationPreparationError:
        raise
    except BoundaryContinuityConflict as exc:
        raise _preparation_refused(
            f"boundary continuity refuses declaration preparation: {exc}",
            captured_head=captured_head,
        ) from exc
    except Exception as exc:
        raise _preparation_refused(
            f"cannot establish declaration preparation basis: {exc}",
            captured_head=captured_head,
            projected_head=getattr(exc, "projected_head", None),
        ) from exc
    finally:
        _close_quietly(snapshot)
        _close_quietly(query)
        _close_quietly(ledger)

    if not changes:
        return DeclarationEditPlan(
            status="noop",
            target_path=target_path,
            descriptor=descriptor,
            lineage=captured_head.lineage,
            basis=basis,
            captured_head=captured_head,
            before_documents=before_documents,
            proposed_documents=proposed_documents,
            changes=(),
            authored_at=None,
            observer=observer,
            drafts=(),
            fact_ids=(),
            key_introductions=(),
            old_cache_bytes=old_cache_bytes,
            old_cache_sha256=hashlib.sha256(old_cache_bytes).hexdigest(),
            proposed_text=proposed_text,
            atomic_limit=atomic_limit,
            exact_drafts=_exact_drafts(()),
        )

    if credentials is None:
        raise _preparation_refused(
            "declaration edits require fact and Arrival signers"
        )
    authored_at = time.time()
    rows: list[tuple[Any, ...]] = []
    fact_ids: list[str] = []
    for change in changes:
        fact_id, row = _declaration_row(
            change,
            lineage=captured_head.lineage,
            authored_at=authored_at,
            observer=observer,
            credentials=credentials,
            registry=key_registry,
            captured_head=captured_head,
            fact_verify=fact_verify,
        )
        fact_ids.append(fact_id)
        rows.append(row)
    body = body_of_fact_row(rows[0]) if len(rows) == 1 else body_of_batch(rows)
    envelope_kind = "fact" if len(rows) == 1 else "batch"
    envelope_digest = content_commitment(
        envelope_kind, authored_at, observer, "", body
    )
    outer_signature = _signed_with_existing_key(
        signer=credentials.arrival_signer,
        verifier=arrival_verify,
        registry=key_registry,
        author=observer,
        head=captured_head,
        digest=envelope_digest,
        label="Arrival declaration envelope",
    )
    declaration_draft = RecordDraft(
        kind=envelope_kind,
        authored_at=authored_at,
        observer=observer,
        origin="",
        body=body,
        signature=outer_signature,
    )

    proposed_keys: dict[str, str] = {}
    for document in proposed_documents:
        if document["kind"] != DECL_OBSERVER_DEFINED:
            continue
        key = document["payload"].get("key")
        if key is None:
            continue
        if not _key_is_well_formed(key):
            raise _preparation_refused(
                f"observer {document['subject']!r} carries a malformed public key"
            )
        proposed_keys[str(document["subject"])] = str(key)
    existing_keys = {
        named_observer: {key for key, _ordinal in keys}
        for named_observer, keys in key_registry.introductions.items()
    }
    key_drafts: list[RecordDraft] = []
    for named_observer, key in proposed_keys.items():
        if key in existing_keys.get(named_observer, set()):
            continue
        key_drafts.append(
            _key_draft(
                observer,
                named_observer,
                key,
                authored_at=authored_at,
                credentials=credentials,
                registry=key_registry,
                captured_head=captured_head,
                arrival_verify=arrival_verify,
            )
        )

    drafts = tuple((*key_drafts, declaration_draft))
    if atomic_limit is not None and len(drafts) > atomic_limit:
        raise AtomicLimitExceeded(
            f"declaration edit needs {len(drafts)} Arrival records, but the "
            f"backend atomic limit is {atomic_limit}; refused before append"
        )
    return DeclarationEditPlan(
        status="planned",
        target_path=target_path,
        descriptor=descriptor,
        lineage=captured_head.lineage,
        basis=basis,
        captured_head=captured_head,
        before_documents=before_documents,
        proposed_documents=proposed_documents,
        changes=changes,
        authored_at=authored_at,
        observer=observer,
        drafts=drafts,
        fact_ids=tuple(fact_ids),
        key_introductions=tuple(draft.body["observer"] for draft in key_drafts),
        old_cache_bytes=old_cache_bytes,
        old_cache_sha256=hashlib.sha256(old_cache_bytes).hexdigest(),
        proposed_text=proposed_text,
        atomic_limit=atomic_limit,
        exact_drafts=_exact_drafts(drafts),
    )


def _result(
    plan: DeclarationEditPlan,
    *,
    status: str,
    head: Head | None,
    commit: Any | None,
    intent: Path | None,
    phase: str,
    file_written: bool,
    changes: tuple[Change, ...] | None,
) -> DeclarationEditResult:
    return DeclarationEditResult(
        status=status, target_path=plan.target_path, descriptor=plan.descriptor,
        lineage=plan.lineage, basis=plan.basis,
        captured_head=plan.captured_head, head=head,
        commit=commit, fact_ids=plan.fact_ids, intent_path=intent,
        phase=phase, file_written=file_written, changes=changes,
    )


def _validate_plan(plan: DeclarationEditPlan) -> None:
    if plan.status not in {"planned", "noop"}:
        raise DeclarationApplyError("only a planned declaration edit can be applied")
    if _exact_drafts(plan.drafts) != plan.exact_drafts:
        raise DeclarationApplyError(
            "declaration plan drafts changed after preparation; refusing append"
        )
    if hashlib.sha256(plan.old_cache_bytes).hexdigest() != plan.old_cache_sha256:
        raise DeclarationApplyError(
            "declaration plan cache evidence changed after preparation"
        )


def _remove_intent(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _fsync_parent(path)


def apply_declaration_edit(
    registry: BackendRegistry,
    plan: DeclarationEditPlan,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> DeclarationEditResult:
    """Apply an edit under the target's process-safe operation lock."""
    with _declaration_lock(plan.target_path):
        return _apply_declaration_edit(
            registry, plan, failure_hook=failure_hook
        )


def _apply_declaration_edit(
    registry: BackendRegistry,
    plan: DeclarationEditPlan,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> DeclarationEditResult:
    """Append one prepared declaration transition and publish its cache.

    The prepared drafts are submitted exactly once under the captured full
    head. Contract refusals are zero-prefix stale refusals; transport and
    witness failures retain the intent and their identity for recovery.
    """
    _validate_plan(plan)
    if plan.status == "noop":
        return _result(
            plan, status="noop", head=plan.captured_head, commit=None, intent=None,
            phase="noop", file_written=False, changes=plan.changes,
        )
    intent = declaration_intent_path(plan.target_path)
    try:
        if plan.target_path.read_bytes() != plan.old_cache_bytes:
            raise DeclarationStale(
                "declaration cache changed after preparation; refusing append"
            )
    except OSError as exc:
        raise DeclarationApplyError(
            f"cannot recheck declaration cache before append: {exc}"
        ) from exc
    data = _intent_data(plan, phase="prepared")
    append_drafts = _drafts_from_exact(
        json.loads(plan.exact_drafts), plan.exact_drafts
    )
    try:
        _write_exclusive_json(intent, data)
    except FileExistsError as exc:
        raise DeclarationApplyError(
            f"unfinished declaration intent already exists: {intent}"
        ) from exc
    if failure_hook:
        try:
            failure_hook("after-intent")
        except Exception as exc:
            raise DeclarationApplyError(
                "declaration intent was durable but append did not start"
            ) from exc

    ledger: Any | None = None
    query: Any | None = None
    commit: Any | None = None
    head: Head | None = None
    append_entered = False
    try:
        ledger, query = registry.open(plan.descriptor)
        try:
            append_entered = True
            commit = ledger.append(plan.captured_head, append_drafts)
        except Exception as exc:
            from .arrival_contract import ContractRefusal
            from .arrival_head_seam import NotWitnessed

            if isinstance(exc, ContractRefusal):
                _remove_intent(intent)
                raise DeclarationStale(
                    f"declaration append refused before mutation: {exc}"
                ) from exc
            if isinstance(exc, NotWitnessed):
                head = exc.head
                data["phase"] = "append-unwitnessed"
                with suppress(Exception):
                    _replace_json(intent, data)
                raise DeclarationUnwitnessed(
                    "declaration records committed but their witness is unknown",
                    head=exc.head, commit=exc.commit, intent_path=intent,
                    fact_ids=plan.fact_ids, cause=exc,
                ) from exc
            data["phase"] = "append-unknown"
            with suppress(Exception):
                _replace_json(intent, data)
            raise DeclarationOutcomeUnknown(
                "declaration append outcome is unknown; recover the intent",
                head=None, intent_path=intent, fact_ids=plan.fact_ids, cause=exc,
            ) from exc
        head = commit.after
        try:
            data["phase"] = "appended"
            _replace_json(intent, data)
            if failure_hook:
                failure_hook("after-append")
        except Exception as exc:
            raise DeclarationCommittedIncomplete(
                "declaration append committed but append phase recording failed",
                phase="appended", head=head, commit=commit, intent_path=intent,
                fact_ids=plan.fact_ids, cause=exc,
            ) from exc
    except (DeclarationStale, DeclarationUnwitnessed, DeclarationOutcomeUnknown,
            DeclarationCommittedIncomplete):
        raise
    except Exception as exc:
        if not append_entered:
            raise DeclarationApplyError(
                "declaration append was refused before entering the append call; "
                "prepared intent retained for inspection",
            ) from exc
        raise DeclarationOutcomeUnknown(
            "declaration append path failed; recover the intent",
            head=head, intent_path=intent, fact_ids=plan.fact_ids, cause=exc,
        ) from exc
    finally:
        _close_quietly(query)
        _close_quietly(ledger)

    try:
        from .arrival_maintenance import sync_projection

        sync_projection(registry, plan.descriptor, through=head)
        data["phase"] = "synced"
        _replace_json(intent, data)
        if failure_hook:
            failure_hook("after-sync")
        data["phase"] = "publishing"
        _publish_cache(
            plan, intent=intent, intent_data=data, failure_hook=failure_hook
        )
        data["phase"] = "published"
        _replace_json(intent, data)
        if failure_hook:
            failure_hook("before-intent-remove")
        _remove_intent(intent)
    except Exception as exc:
        raise DeclarationCommittedIncomplete(
            "declaration append committed but a later phase failed; recover the intent",
            phase=str(data.get("phase", "appended")), head=head,
            commit=commit, intent_path=intent, fact_ids=plan.fact_ids, cause=exc,
        ) from exc
    return _result(
        plan, status="applied", head=head, commit=commit, intent=None,
        phase="published", file_written=True, changes=plan.changes,
    )


def recover_declaration_edit(
    registry: BackendRegistry,
    intent: Path | str,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> DeclarationEditResult:
    """Recover an edit under the target's process-safe operation lock."""
    intent_path = Path(intent).resolve()
    with _declaration_lock(Path(_read_intent(intent_path)["target"])):
        return _recover_declaration_edit(
            registry, intent_path, failure_hook=failure_hook
        )


def _recover_declaration_edit(
    registry: BackendRegistry,
    intent: Path | str,
    *,
    failure_hook: Callable[[str], None] | None = None,
) -> DeclarationEditResult:
    """Reconcile an edit intent by exact suffix membership, then finish cache."""
    intent_path = Path(intent).resolve()
    data = _read_intent(intent_path)
    drafts = _drafts_from_intent(data)
    plan = _plan_from_intent(data, drafts)
    captured = plan.captured_head
    ledger: Any | None = None
    query: Any | None = None
    try:
        ledger, query = registry.open(plan.descriptor)
        captured_at_ledger = ledger.head_at(
            Watermark(lineage=captured.lineage, ordinal=captured.ordinal)
        )
        if captured_at_ledger != captured:
            raise DeclarationStale(
                "declaration intent predecessor head hash no longer matches"
            )
        actual = ledger.head()
        if actual == captured:
            if data.get("cache_temp") or data.get("cache_backup"):
                raise DeclarationApplyError(
                    "unapplied declaration intent has cache publication artifacts"
                )
            if plan.target_path.read_bytes() != plan.old_cache_bytes:
                raise DeclarationStale(
                    "unapplied declaration intent has competing cache bytes"
                )
            _remove_intent(intent_path)
            return _result(
                plan, status="not-applied", head=actual, commit=None, intent=None,
                phase="not-applied", file_written=False, changes=None,
            )
        first = captured.ordinal + 1
        for index, draft in enumerate(drafts):
            ordinal = first + index
            if actual.ordinal < ordinal or not _record_matches_draft(
                ledger.read(ordinal), draft
            ):
                raise DeclarationStale(
                    "declaration intent does not occupy its exact expected suffix"
                )
    except DeclarationStale:
        raise
    except Exception as exc:
        raise DeclarationApplyError(
            f"cannot reconcile declaration intent against Arrival custody: {exc}"
        ) from exc
    finally:
        _close_quietly(query)
        _close_quietly(ledger)

    file_written = False
    try:
        from .arrival_maintenance import sync_projection

        sync_projection(registry, plan.descriptor, through=actual)
        data["phase"] = "synced"
        _replace_json(intent_path, data)
        if failure_hook:
            failure_hook("after-sync")
        if plan.target_path.exists():
            current = plan.target_path.read_bytes()
            if current == plan.proposed_text.encode("utf-8"):
                _cleanup_cache_artifacts(plan, data)
                data["phase"] = "published"
                _replace_json(intent_path, data)
            elif current == plan.old_cache_bytes:
                data["phase"] = "publishing"
                _publish_cache(
                    plan, intent=intent_path, intent_data=data,
                    failure_hook=failure_hook,
                )
                file_written = True
                data["phase"] = "published"
                _replace_json(intent_path, data)
            else:
                raise DeclarationStale(
                    "competing declaration cache bytes are present; refusing overwrite"
                )
        elif data.get("cache_backup"):
            data["phase"] = "publishing"
            _publish_cache(
                plan, intent=intent_path, intent_data=data,
                failure_hook=failure_hook,
            )
            file_written = True
            data["phase"] = "published"
            _replace_json(intent_path, data)
        else:
            raise DeclarationApplyError(
                "declaration cache is missing and has no detached recovery backup"
            )
        _remove_intent(intent_path)
    except Exception as exc:
        raise DeclarationCommittedIncomplete(
            "declaration custody is committed but cache recovery remains incomplete",
            phase=str(data.get("phase", "synced")), head=actual, commit=None,
            intent_path=intent_path, fact_ids=plan.fact_ids, cause=exc,
        ) from exc
    return _result(
        plan, status="recovered", head=actual, commit=None, intent=None,
        phase="published", file_written=file_written, changes=None,
    )
