"""Fresh Arrival initialization and recovery.

This module is intentionally a coordinator.  It knows the Arrival contracts
and the registry, but it never opens a concrete store or a projection itself.
The file adapter is therefore just one possible implementation of the
operation.
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ulid import ULID

from .admission import fact_commitment_hash
from .arrival import ArrivalError, content_commitment
from .arrival_body import body_of_fact_row
from .arrival_contract import AtomicLimitExceeded, Head, Profile, RecordDraft, StoreDescriptor
from .arrival_maintenance import sync_projection
from .arrival_registry import BackendRegistry

__all__ = [
    "ArrivalInitializationError",
    "InitializationConflict",
    "InitializationRecoveryRequired",
    "InitializationOutcomeUnknown",
    "InitializationUnwitnessed",
    "InitializationCommittedIncomplete",
    "ArrivalInitializationResult",
    "initialize_arrival",
    "recover_arrival_initialization",
    "arrival_intent_path",
    "new_lineage",
    "build_declaration_anchor_draft",
]

_INTENT_SCHEMA = "loops.engine/arrival-init-intent/v1"
_PHASES = ("reserved", "minted", "declared", "synced", "published")


def new_lineage() -> str:
    """Mint one stable lineage identifier for a reserved initialization."""
    return str(ULID())


class ArrivalInitializationError(ArrivalError):
    """A fresh Arrival initialization could not complete."""


class InitializationConflict(ArrivalInitializationError):
    """An existing artifact does not match the durable initialization plan."""


class InitializationRecoveryRequired(ArrivalInitializationError):
    """An unfinished initialization intent must be recovered explicitly."""


class InitializationOutcomeUnknown(ArrivalInitializationError):
    """An initialization append did not prove whether it committed."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        lineage: str,
        fact_id: str,
        captured_head: Head | None,
        intent_path: Path,
        cause: BaseException,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.lineage = lineage
        self.fact_id = fact_id
        self.captured_head = captured_head
        self.intent_path = str(intent_path)
        self.cause = cause


class InitializationUnwitnessed(ArrivalInitializationError):
    """Custody committed, but the initialization mutation was not witnessed."""

    def __init__(self, message: str, *, phase: str, lineage: str, fact_id: str,
                 head: Head, commit: Any, intent_path: Path,
                 cause: BaseException) -> None:
        super().__init__(message)
        self.phase = phase
        self.lineage = lineage
        self.fact_id = fact_id
        self.head = head
        self.commit = commit
        self.intent_path = str(intent_path)
        self.cause = cause


class InitializationCommittedIncomplete(ArrivalInitializationError):
    """A known commit exists, but a later initialization phase failed."""

    def __init__(self, message: str, *, phase: str, lineage: str, fact_id: str,
                 captured_head: Head | None, commit: Any, intent_path: Path,
                 cause: BaseException) -> None:
        super().__init__(message)
        self.phase = phase
        self.lineage = lineage
        self.fact_id = fact_id
        self.captured_head = captured_head
        self.commit = commit
        self.intent_path = str(intent_path)
        self.cause = cause


@dataclass(frozen=True)
class ArrivalInitializationResult:
    target_path: str
    location: str
    lineage: str
    head: Head
    phase: str
    file_written: bool


def arrival_intent_path(target: Path | str) -> Path:
    """The exclusive intent sidecar for one declaration target."""

    target_path = Path(target).resolve()
    return target_path.with_name(target_path.name + ".arrival-init.intent")


def _json_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Profile):
        return value.value
    if isinstance(value, Head):
        return {
            "lineage": value.lineage,
            "ordinal": value.ordinal,
            "record_hash": value.record_hash,
        }
    if isinstance(value, Mapping):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(v) for v in value]
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        tmp.replace(path)
        _fsync_parent(path)
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()


def _reserve(path: Path, plan: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(_json_value(plan), sort_keys=True, separators=(",", ":"))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, 0o600)
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


def _save_intent(path: Path, plan: Mapping[str, Any]) -> None:
    _atomic_write(path, json.dumps(_json_value(plan), sort_keys=True, separators=(",", ":")) + "\n")


def _publish_exclusive(path: Path, text: str) -> None:
    """Publish a complete declaration without replacing a concurrent writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        _fsync_parent(path)
    except BaseException:
        with suppress(FileNotFoundError):
            temporary.unlink()
        raise


def _fsync_parent(path: Path) -> None:
    directory_fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _reserved_genesis_signer(
    plan: Mapping[str, Any],
) -> Callable[[str, str], str | None]:
    """Return the exact signature reserved before the durable mint."""
    genesis = plan["genesis"]
    digest = content_commitment(
        genesis["kind"], genesis["at"], genesis["observer"],
        genesis["origin"], genesis["body"],
    )

    def sign(observer: str, offered_digest: str) -> str | None:
        if observer == genesis["observer"] and offered_digest == digest:
            return genesis["signature"]
        return None

    return sign


def _read_intent(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InitializationConflict(f"cannot read initialization intent {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != _INTENT_SCHEMA:
        raise InitializationConflict(f"unsupported or malformed initialization intent: {path}")
    if data.get("phase") not in _PHASES:
        raise InitializationConflict(f"initialization intent has an invalid phase: {path}")
    return data


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


def build_declaration_anchor_draft(
    *,
    lineage: str,
    authored_at: float,
    observer: str,
    documents: Sequence[Mapping[str, Any]],
    fact_signer: Callable[[str, str], str | None],
    arrival_signer: Callable[[str, str], str | None],
    public_key: str,
    fact_verify: Callable[[str, str, str], bool] | None = None,
    arrival_verify: Callable[[str, str, str], bool] | None = None,
) -> RecordDraft:
    payload = json.dumps(
        {"protocol": 1, "documents": [dict(document) for document in documents]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    inner_digest = fact_commitment_hash(
        "_decl.genesis", authored_at, observer, "", payload
    )
    inner_signature = fact_signer(observer, inner_digest)
    if not inner_signature:
        raise ArrivalInitializationError(
            f"founding observer {observer!r} has no fact signer"
        )
    if fact_verify is not None and not fact_verify(
        public_key, inner_signature, inner_digest
    ):
        raise ArrivalInitializationError("founding fact signer does not match the public key")
    body = body_of_fact_row(
        (lineage, "_decl.genesis", authored_at, observer, "", payload, inner_signature)
    )
    outer_digest = content_commitment("fact", authored_at, observer, "", body)
    outer_signature = arrival_signer(observer, outer_digest)
    if not outer_signature:
        raise ArrivalInitializationError(
            f"founding observer {observer!r} has no Arrival signer"
        )
    if arrival_verify is not None and not arrival_verify(
        public_key, outer_signature, outer_digest
    ):
        raise ArrivalInitializationError("founding Arrival signer does not match the public key")
    return RecordDraft(
        kind="fact",
        authored_at=authored_at,
        observer=observer,
        origin="",
        body=body,
        signature=outer_signature,
    )


def _same_record(record: Mapping[str, Any], draft: RecordDraft) -> bool:
    return (
        record.get("k") == draft.kind
        and record.get("at") == draft.authored_at
        and record.get("observer") == draft.observer
        and record.get("origin") == draft.origin
        and record.get("body") == dict(draft.body)
        and record.get("sig") == draft.signature
    )


def _declared_key_drafts(
    documents: Sequence[Mapping[str, Any]],
    *,
    observer: str,
    public_key: str,
    at: float,
    signer: Callable[[str, str], str | None],
    verify: Callable[[str, str, str], bool] | None,
) -> tuple[RecordDraft, ...]:
    """Introduce declared observer keys using the valid founding key."""
    keys: dict[str, str] = {}
    for document in documents:
        if document["kind"] != "_decl.observer-defined":
            continue
        key = document["payload"].get("key")
        if key is None:
            continue
        subject = document["subject"]
        try:
            if not isinstance(key, str) or len(base64.b64decode(key, validate=True)) != 32:
                raise ValueError
        except (ValueError, TypeError):
            raise InitializationConflict(
                f"observer {subject!r} has a malformed public key"
            ) from None
        if subject == observer:
            if key != public_key:
                raise InitializationConflict(
                    "declared founding key differs from genesis public key"
                )
            continue
        if subject in keys and keys[subject] != key:
            raise InitializationConflict(f"observer {subject!r} has conflicting declared keys")
        keys[subject] = key
    drafts: list[RecordDraft] = []
    for subject, key in keys.items():
        body = {"observer": subject, "key": key}
        digest = content_commitment("key", at, observer, "", body)
        signature = signer(observer, digest)
        if not signature or (
            verify is not None and not verify(public_key, signature, digest)
        ):
            raise InitializationConflict("founding signer cannot authenticate key introduction")
        drafts.append(RecordDraft("key", at, observer, "", body, signature))
    return tuple(drafts)


def _draft_dict(draft: RecordDraft) -> dict[str, Any]:
    return {
        "kind": draft.kind,
        "authored_at": draft.authored_at,
        "observer": draft.observer,
        "origin": draft.origin,
        "body": dict(draft.body),
        "signature": draft.signature,
    }


def _bootstrap_matches(ledger: Any, current: Head, drafts: Sequence[RecordDraft]) -> bool:
    return current.ordinal >= len(drafts) and all(
        _same_record(ledger.read(ordinal), draft)
        for ordinal, draft in enumerate(drafts, start=1)
    )


def _phase(plan: dict[str, Any], value: str) -> None:
    plan["phase"] = value


def _check_preconditions(
    target: Path,
    descriptor: StoreDescriptor,
    documents: Sequence[Mapping[str, Any]],
    declaration_text: str,
    observer: str,
    public_key: str,
    signer: Callable[[str, str], str | None],
    fact_signer: Callable[[str, str], str | None],
    arrival_signer: Callable[[str, str], str | None],
) -> None:
    if descriptor.role is not Profile.AUTHORITY:
        raise InitializationConflict("fresh initialization requires an Authority descriptor")
    if not observer or not isinstance(observer, str):
        raise InitializationConflict("fresh initialization requires a non-empty observer")
    if not isinstance(public_key, str) or not public_key:
        raise InitializationConflict("fresh initialization requires a founding public key")
    try:
        if len(base64.b64decode(public_key, validate=True)) != 32:
            raise ValueError
    except (ValueError, TypeError):
        raise InitializationConflict(
            "founding public key must be raw-32-byte base64"
        ) from None
    if not isinstance(declaration_text, str) or not declaration_text.strip():
        raise InitializationConflict("declaration text must be non-empty UTF-8 text")
    if not callable(signer) or not callable(fact_signer) or not callable(arrival_signer):
        raise InitializationConflict("fresh initialization requires signer callables")
    if not isinstance(documents, Sequence) or isinstance(documents, (str, bytes)):
        raise InitializationConflict("declaration documents must be a sequence")
    try:
        json.dumps([dict(document) for document in documents], ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise InitializationConflict(f"declaration documents are not JSON-safe: {exc}") from exc
    if target.exists():
        raise InitializationConflict(f"vertex file already exists: {target}")


def _validate_declaration(
    target: Path,
    descriptor: StoreDescriptor,
    documents: Sequence[Mapping[str, Any]],
    declaration_text: str,
    lineage: str,
) -> None:
    """Check the signed declaration inputs before reserving or minting.

    The declaration text is the human ingress form and the document sequence
    is what gets committed into ``_decl.genesis``.  They must describe the
    same residence and identity, otherwise recovery could faithfully preserve
    a plan that never represented the requested target.
    """
    try:
        from lang import parse_vertex, validate_vertex, vertex_to_documents

        ast = parse_vertex(declaration_text, path=target)
        validate_vertex(ast)
    except Exception as exc:
        raise InitializationConflict(
            f"declaration text is not valid Vertex grammar: {exc}"
        ) from exc
    from .declaration import validate_arrival_runtime_identity

    validate_arrival_runtime_identity(
        ast.name,
        ast.loops,
        refusal=InitializationConflict,
    )
    parsed_documents = [document.as_json() for document in vertex_to_documents(ast)]
    if [dict(document) for document in documents] != parsed_documents:
        raise InitializationConflict(
            "declaration text and declaration documents disagree"
        )
    backend = ast.store_backend
    if (
        backend is None
        or backend.name != descriptor.backend
        or backend.lineage != lineage
        or backend.role != Profile.AUTHORITY.value
    ):
        raise InitializationConflict(
            "declaration residence must match the requested backend, lineage and authority role"
        )
    location = ast.store_location
    if descriptor.backend == "file" and ast.store is not None:
        location = str(ast.store)
    if location is None:
        raise InitializationConflict("declaration residence must include a store location")
    if descriptor.backend == "file":
        parsed_location = (target.parent / location).resolve()
        requested_location = Path(descriptor.location).resolve()
        locations_match = parsed_location == requested_location
    else:
        # DSNs are adapter-owned and must survive the engine untouched.
        locations_match = location == descriptor.location
    if not locations_match:
        raise InitializationConflict(
            "declaration residence location does not match the requested descriptor"
        )


def initialize_arrival(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *,
    target: Path | str,
    documents: Sequence[Mapping[str, Any]],
    declaration_text: str,
    observer: str,
    public_key: str,
    signer: Callable[[str, str], str | None],
    fact_signer: Callable[[str, str], str | None],
    arrival_signer: Callable[[str, str], str | None],
    fact_verify: Callable[[str, str, str], bool] | None = None,
    arrival_verify: Callable[[str, str, str], bool] | None = None,
    lineage: str | None = None,
    authored_at: float | None = None,
    failure_hook: Callable[[str], None] | None = None,
) -> ArrivalInitializationResult:
    """Mint and publish a fresh Arrival declaration with recoverable intent."""
    target_path = Path(target).resolve()
    intent = arrival_intent_path(target_path)
    _check_preconditions(
        target_path, descriptor, documents, declaration_text, observer, public_key,
        signer, fact_signer, arrival_signer,
    )
    if intent.exists():
        raise InitializationRecoveryRequired(
            f"unfinished initialization intent exists: {intent}; recover explicitly"
        )
    chosen_lineage = lineage or descriptor.lineage or new_lineage()
    if descriptor.lineage is not None and descriptor.lineage != chosen_lineage:
        raise InitializationConflict("descriptor lineage does not match reserved lineage")
    _validate_declaration(
        target_path, descriptor, documents, declaration_text, chosen_lineage
    )
    at = time.time() if authored_at is None else authored_at
    genesis_body = {
        "protocol": 1,
        "lineage": chosen_lineage,
        "key": public_key,
    }
    genesis_digest = content_commitment(
        "genesis", at, observer, "", genesis_body
    )
    genesis_signature = signer(observer, genesis_digest)
    if not genesis_signature:
        raise InitializationConflict("founding signer produced no genesis signature")
    if arrival_verify is not None and not arrival_verify(
        public_key, genesis_signature, genesis_digest
    ):
        raise InitializationConflict("founding genesis signer does not match the public key")
    draft = build_declaration_anchor_draft(
        lineage=chosen_lineage,
        authored_at=at,
        observer=observer,
        documents=documents,
        fact_signer=fact_signer,
        arrival_signer=arrival_signer,
        public_key=public_key,
        fact_verify=fact_verify,
        arrival_verify=arrival_verify,
    )
    key_drafts = _declared_key_drafts(
        documents, observer=observer, public_key=public_key, at=at,
        signer=arrival_signer, verify=arrival_verify,
    )
    if key_drafts:
        # The minimum backend contract supports one record. Additional keys
        # and declaration genesis form one larger atomic unit; refuse its
        # unsupported size before reserving an intent or minting a lineage.
        ledger, query = registry.open(descriptor)
        try:
            limit = ledger.capabilities().max_atomic_records
            if limit is not None and len(key_drafts) + 1 > limit:
                raise AtomicLimitExceeded(
                    f"initialization needs {len(key_drafts) + 1} records; atomic limit is {limit}"
                )
        finally:
            for resource in (query, ledger):
                close = getattr(resource, "close", None)
                if callable(close):
                    close()
    planned = {
        "schema": _INTENT_SCHEMA,
        "phase": "reserved",
        "target": str(target_path),
        "descriptor": _descriptor_dict(
            StoreDescriptor(
                descriptor.backend, descriptor.location, chosen_lineage,
                descriptor.role, descriptor.query, descriptor.witness,
            )
        ),
        "lineage": chosen_lineage,
        "observer": observer,
        "public_key": public_key,
        "at": at,
        "genesis": {
            "kind": "genesis",
            "at": at,
            "observer": observer,
            "origin": "",
            "body": genesis_body,
            "signature": genesis_signature,
        },
        "documents": [dict(document) for document in documents],
        "declaration_text": declaration_text,
        "draft": _draft_dict(draft),
        "key_drafts": [_draft_dict(key_draft) for key_draft in key_drafts],
    }
    _reserve(intent, planned)
    try:
        return _continue(
            registry, intent, planned, failure_hook=failure_hook,
        )
    except BaseException:
        # The sidecar is the recovery record.  It is removed only once the
        # declaration bytes have been atomically published.
        raise


def _continue(
    registry: BackendRegistry,
    intent: Path,
    plan: dict[str, Any],
    *,
    failure_hook: Callable[[str], None] | None,
) -> ArrivalInitializationResult:
    descriptor = _descriptor_from(plan["descriptor"])
    target = Path(plan["target"])
    draft_data = plan["draft"]
    draft = RecordDraft(
        kind=draft_data["kind"], authored_at=draft_data["authored_at"],
        observer=draft_data["observer"], origin=draft_data["origin"],
        body=draft_data["body"], signature=draft_data["signature"],
    )
    drafts = tuple(RecordDraft(**data) for data in plan.get("key_drafts", ())) + (draft,)
    ledger = query = None
    head: Head | None = None
    commit = None
    try:
        if plan["phase"] == "reserved":
            ledger, query = registry.open(descriptor)
            # PreGenesis carries no absence claim.  The adapter's exclusive
            # mint is the authority for an absent, existing, or corrupt
            # location and refuses safely in the latter two cases.
            try:
                head = ledger.mint({
                    "observer": plan["observer"],
                    "signer": _reserved_genesis_signer(plan),
                    "key": plan["public_key"], "lineage": plan["lineage"],
                    "origin": "", "at": plan["at"],
                })
            except Exception as mint_error:
                from .arrival import GenesisRefused
                from .arrival_contract import ContractRefusal
                from .arrival_head_seam import NotWitnessed

                if isinstance(mint_error, NotWitnessed):
                    raise InitializationUnwitnessed(
                        "genesis committed but its witness is unknown; recover "
                        "the initialization intent before retrying",
                        phase="reserved", lineage=plan["lineage"],
                        fact_id=plan["lineage"], head=mint_error.head,
                        commit=mint_error.commit, intent_path=intent,
                        cause=mint_error,
                    ) from mint_error
                # A prior mint may have committed while its witness was
                # unknown.  The failed exclusive mint is the proof that this
                # is not a fresh location; only an exact custody comparison
                # can turn that case into recoverable progress.
                try:
                    head = _head_and_check_genesis(registry, descriptor, plan)
                except Exception:
                    if isinstance(mint_error, (ContractRefusal, GenesisRefused)):
                        raise mint_error from None
                    raise InitializationOutcomeUnknown(
                        "genesis mint outcome is unknown; recover the durable "
                        "initialization intent before retrying",
                        phase="reserved", lineage=plan["lineage"],
                        fact_id=plan["lineage"], captured_head=None,
                        intent_path=intent, cause=mint_error,
                    ) from mint_error
                if head.ordinal != 0:
                    raise mint_error from None
            _phase(plan, "minted")
            _save_intent(intent, plan)
            if failure_hook:
                failure_hook("after-mint")
        else:
            head = _head_and_check_genesis(registry, descriptor, plan)
        if plan["phase"] == "minted":
            if ledger is None:
                ledger, query = registry.open(descriptor)
            current = ledger.head()
            if current.ordinal == 0:
                try:
                    commit = ledger.append(current, drafts)
                except Exception as exc:
                    # Contract/grammar refusals are precommit diagnostics;
                    # an adapter exception outside those public families did
                    # not establish whether its append landed.
                    from .arrival_contract import ContractRefusal

                    if isinstance(exc, ContractRefusal):
                        raise
                    from .arrival import GenesisRefused

                    if isinstance(exc, GenesisRefused):
                        raise
                    from .arrival_head_seam import NotWitnessed

                    if isinstance(exc, NotWitnessed):
                        raise InitializationUnwitnessed(
                            "declaration committed but its witness is unknown; "
                            "recover the initialization intent before retrying",
                            phase="minted", lineage=plan["lineage"],
                            fact_id=str(draft.body["id"]), head=exc.head,
                            commit=exc.commit, intent_path=intent, cause=exc,
                        ) from exc
                    raise InitializationOutcomeUnknown(
                        "declaration append outcome is unknown; recover the "
                        "initialization intent before retrying",
                        phase="minted", lineage=plan["lineage"],
                        fact_id=str(draft.body["id"]), captured_head=current,
                        intent_path=intent, cause=exc,
                    ) from exc
                head = commit.after
            elif _bootstrap_matches(ledger, current, drafts):
                head = current
            else:
                raise InitializationConflict("ledger contains a conflicting post-genesis record")
            _phase(plan, "declared")
            _save_intent(intent, plan)
            if failure_hook:
                failure_hook("after-declaration")
        if plan["phase"] == "declared":
            if ledger is None:
                ledger, query = registry.open(descriptor)
            current = ledger.head()
            # The declaration append is already durable at this point.  Keep
            # its observed head while projection sync runs so a sync failure
            # is reported as committed-incomplete with concrete identity.
            head = current
            if not _bootstrap_matches(ledger, current, drafts):
                raise InitializationConflict(
                    "ledger no longer contains the planned declaration genesis"
                )
            result = sync_projection(registry, descriptor)
            head = result.captured_head
            _phase(plan, "synced")
            _save_intent(intent, plan)
            if failure_hook:
                failure_hook("after-sync")
        elif plan["phase"] in {"synced", "published"}:
            if ledger is None:
                ledger, query = registry.open(descriptor)
            current = ledger.head()
            # Recovery has an observed committed head before attempting
            # publication or intent cleanup.
            head = current
            if not _bootstrap_matches(ledger, current, drafts):
                raise InitializationConflict(
                    "ledger no longer contains the planned declaration genesis"
                )
        else:
            head = ledger.head() if ledger is not None else _head_and_check_genesis(
                registry, descriptor, plan
            )
        if plan["phase"] == "synced":
            if target.exists():
                existing = target.read_text(encoding="utf-8")
                if existing != plan["declaration_text"]:
                    raise InitializationConflict(
                        "existing declaration differs from initialization intent"
                    )
            else:
                try:
                    _publish_exclusive(target, plan["declaration_text"])
                except FileExistsError:
                    existing = target.read_text(encoding="utf-8")
                    if existing != plan["declaration_text"]:
                        raise InitializationConflict(
                            "a concurrent declaration differs from initialization intent"
                        ) from None
            _phase(plan, "published")
            _save_intent(intent, plan)
            if failure_hook:
                failure_hook("after-publication")
        if plan["phase"] == "published":
            with suppress(FileNotFoundError):
                intent.unlink()
                _fsync_parent(intent)
        return ArrivalInitializationResult(
            target_path=str(target), location=descriptor.location,
            lineage=plan["lineage"], head=head,
            phase=plan["phase"], file_written=target.exists(),
        )
    except Exception as exc:
        if isinstance(
            exc,
            (
                InitializationOutcomeUnknown,
                InitializationUnwitnessed,
                InitializationCommittedIncomplete,
            ),
        ):
            raise
        if head is not None and plan["phase"] in {"minted", "declared", "synced", "published"}:
            raise InitializationCommittedIncomplete(
                "initialization committed but a later phase failed; recover "
                "the durable intent",
                phase=plan["phase"], lineage=plan["lineage"],
                fact_id=str(draft.body["id"]), captured_head=head,
                commit=commit, intent_path=intent, cause=exc,
            ) from exc
        raise
    finally:
        close = getattr(query, "close", None)
        if callable(close):
            close()
        close = getattr(ledger, "close", None)
        if callable(close):
            close()


def _head_and_check_genesis(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    plan: Mapping[str, Any],
) -> Head:
    ledger, query = registry.open(descriptor)
    try:
        head = ledger.head()
        record = ledger.read(0)
        body = record.get("body")
        genesis = plan["genesis"]
        if (
            record.get("k") != genesis["kind"]
            or record.get("at") != genesis["at"]
            or record.get("observer") != genesis["observer"]
            or record.get("origin") != genesis["origin"]
            or body != genesis["body"]
            or record.get("sig") != genesis["signature"]
        ):
            raise InitializationConflict("existing genesis differs from initialization intent")
        if head.lineage != plan["lineage"]:
            raise InitializationConflict(
                "existing ledger lineage differs from initialization intent"
            )
        return head
    finally:
        getattr(query, "close", lambda: None)()
        getattr(ledger, "close", lambda: None)()


def recover_arrival_initialization(
    registry: BackendRegistry,
    intent: Path | str,
    *,
    # Retained as ignored compatibility parameters for callers of the first
    # recovery prototype. Recovery signs nothing: it uses the exact reserved
    # genesis signature from the durable intent.
    signer: Callable[[str, str], str | None] | None = None,
    fact_signer: Callable[[str, str], str | None] | None = None,
    arrival_signer: Callable[[str, str], str | None] | None = None,
    failure_hook: Callable[[str], None] | None = None,
) -> ArrivalInitializationResult:
    """Resume an intent by comparing exact custody content at every phase."""
    intent_path = Path(intent).resolve()
    if not intent_path.exists():
        raise InitializationConflict(f"initialization intent does not exist: {intent_path}")
    plan = _read_intent(intent_path)
    return _continue(
        registry, intent_path, plan, failure_hook=failure_hook,
    )
