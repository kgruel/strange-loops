"""Explicit append-forward adoption of a reviewed migrated Arrival declaration."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lang import parse_vertex, validate_vertex, vertex_to_documents
from lang.document import DECL_OBSERVER_DEFINED

from .admission import fact_commitment_hash
from .arrival import ArrivalError, content_commitment, key_registry_from_records
from .arrival_body import body_of_fact_row, rows_of_body
from .arrival_contract import (
    Commit,
    DurabilityReceipt,
    Full,
    Head,
    Profile,
    ReadBasis,
    RecordDraft,
    StoreDescriptor,
    Watermark,
)
from .arrival_declarations import (
    _declaration_lock,
    _descriptor_dict,
    _descriptor_from,
    _drafts_from_exact,
    _exact_drafts,
    _head_dict,
    _record_matches_draft,
    _remove_intent,
    _replace_json,
    _write_exclusive_json,
)
from .arrival_initialization import build_declaration_anchor_draft
from .arrival_maintenance import (
    ProjectionSyncResult,
    preflight_projection_maintenance,
    sync_projection,
)
from .arrival_registry import BackendRegistry
from .credentials import (
    CapturedSigningContext,
    CredentialBindingEvidence,
    CredentialBindingRefused,
    CredentialPurpose,
    CredentialRequest,
    CredentialResolutionSession,
    SigningDomain,
    WriteCredentials,
)
from .declaration import validate_arrival_runtime_identity
from .residence import canonical_store_path

__all__ = [
    "AdoptionPreparationRefused", "AdoptionApplyError", "AdoptionStale",
    "AdoptionRecoveryRequired", "AdoptionOutcomeUnknown", "AdoptionUnwitnessed",
    "AdoptionCommittedIncomplete", "ArrivalAdoptionPlan", "ArrivalAdoptionResult",
    "arrival_adoption_intent_path", "prepare_arrival_adoption",
    "apply_arrival_adoption", "recover_arrival_adoption",
]

_SCHEMA = "loops.engine/arrival-adoption-intent/v1"


class AdoptionPreparationRefused(ArrivalError):
    """The reviewed snapshot or selected prefix cannot be adopted."""


class AdoptionApplyError(ArrivalError):
    """An adoption intent cannot be applied or reconciled."""


class AdoptionStale(AdoptionApplyError):
    """The selected head or reviewed cache changed."""

    def __init__(self, message: str, *, intent_path: Path | None = None) -> None:
        super().__init__(message)
        self.intent_path = intent_path


class AdoptionRecoveryRequired(AdoptionApplyError):
    """A durable preappend intent needs explicit recovery."""

    def __init__(self, message: str, *, intent_path: Path, cause: BaseException) -> None:
        super().__init__(message)
        self.intent_path = intent_path
        self.cause = cause


class AdoptionOutcomeUnknown(AdoptionApplyError):
    """An append was entered, but its outcome is not established."""

    def __init__(self, message: str, *, head: Head, intent_path: Path,
                 cause: BaseException) -> None:
        super().__init__(message)
        self.head = head
        self.intent_path = intent_path
        self.cause = cause


class AdoptionUnwitnessed(AdoptionApplyError):
    """The append committed without a complete witness."""

    def __init__(self, message: str, *, head: Head, commit: Commit | None,
                 intent_path: Path, cause: BaseException) -> None:
        super().__init__(message)
        self.head = head
        self.commit = commit
        self.intent_path = intent_path
        self.cause = cause


class AdoptionCommittedIncomplete(AdoptionApplyError):
    """Known custody commit still needs projection or cache reconciliation."""

    def __init__(self, message: str, *, phase: str, head: Head,
                 commit: Commit | None, intent_path: Path,
                 cause: BaseException) -> None:
        super().__init__(message)
        self.phase = phase
        self.head = head
        self.commit = commit
        self.intent_path = intent_path
        self.cause = cause


@dataclass(frozen=True)
class ArrivalAdoptionPlan:
    target_path: Path
    descriptor: StoreDescriptor
    lineage: str
    basis: ReadBasis
    captured_head: Head
    observer: str
    reviewed_text: str
    reviewed_sha256: str
    declaration_text: str
    declaration_sha256: str
    documents: tuple[Mapping[str, Any], ...]
    draft: RecordDraft
    exact_drafts: str
    credential_bindings: tuple[CredentialBindingEvidence, ...]

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return (self.lineage,)


@dataclass(frozen=True)
class ArrivalAdoptionResult:
    status: str
    target_path: Path
    descriptor: StoreDescriptor
    lineage: str
    basis: ReadBasis
    captured_head: Head
    head: Head
    commit: Commit | None
    fact_ids: tuple[str, ...]
    intent_path: Path | None
    phase: str
    file_written: bool
    projection: ProjectionSyncResult | None
    credential_bindings: tuple[CredentialBindingEvidence, ...]
    observed_head: Head | None = None


def arrival_adoption_intent_path(target: Path | str) -> Path:
    path = Path(target).resolve()
    return path.with_name(path.name + ".arrival-adopt.intent")


def _close(handle: object | None) -> None:
    close = getattr(handle, "close", None)
    if callable(close):
        with suppress(Exception):
            close()


def _cache_bytes(plan: ArrivalAdoptionPlan) -> bytes:
    return plan.declaration_text.encode("utf-8")


def _require_cache(plan: ArrivalAdoptionPlan) -> None:
    try:
        actual = plan.target_path.read_bytes()
    except OSError as exc:
        raise AdoptionStale(f"reviewed declaration cache is unavailable: {exc}") from exc
    if (
        actual != _cache_bytes(plan)
        or hashlib.sha256(actual).hexdigest() != plan.declaration_sha256
    ):
        raise AdoptionStale("reviewed declaration bytes changed")


def _selected_documents(
    text: str, target: Path, descriptor: StoreDescriptor
) -> tuple[dict[str, Any], ...]:
    try:
        ast = parse_vertex(text, path=target)
        validate_vertex(ast)
        validate_arrival_runtime_identity(ast.name, ast.loops, refusal=AdoptionPreparationRefused)
        backend = ast.store_backend
        if (
            backend is None or backend.name != descriptor.backend
            or backend.lineage != descriptor.lineage
            or backend.role != Profile.AUTHORITY.value
        ):
            raise AdoptionPreparationRefused(
                "reviewed declaration residence differs from authority descriptor"
            )
        location = (
            str(canonical_store_path(ast.store, target))
            if descriptor.backend == "file" and ast.store is not None
            else ast.store_location
        )
        if location != descriptor.location:
            raise AdoptionPreparationRefused(
                "reviewed declaration store location differs from authority descriptor"
            )
        documents = tuple(document.as_json() for document in vertex_to_documents(ast))
        seen: set[tuple[str, str]] = set()
        for document in documents:
            identity = (document["kind"], document["subject"])
            if identity in seen:
                raise AdoptionPreparationRefused(f"duplicate declaration document {identity!r}")
            seen.add(identity)
        return documents
    except AdoptionPreparationRefused:
        raise
    except Exception as exc:
        raise AdoptionPreparationRefused(f"reviewed declaration is invalid: {exc}") from exc


def _scan_identity(records: tuple[Mapping[str, Any], ...], lineage: str) -> None:
    for record in records:
        if record["k"] not in {"fact", "batch"}:
            continue
        for kind, row in rows_of_body(record["k"], record["body"]):
            if kind != "fact":
                continue
            fact_id, fact_kind, _at, _observer, _origin, payload, _signature = row
            if fact_id == lineage:
                raise AdoptionPreparationRefused(
                    "physical-lineage fact ID already occurs in captured prefix"
                )
            if not fact_kind.startswith("_decl."):
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            if isinstance(data, dict) and data.get("lineage") == lineage:
                raise AdoptionPreparationRefused(
                    "historical declaration overlay claims physical lineage"
                )


def prepare_arrival_adoption(
    registry: BackendRegistry,
    descriptor: StoreDescriptor,
    *, target: Path | str, selected_head: Head,
    reviewed_text: str, reviewed_sha256: str, declaration_text: str,
    observer: str, credentials: WriteCredentials,
    fact_verify: Callable[[str, str, str], bool],
    arrival_verify: Callable[[str, str, str], bool],
    authored_at: float | None = None,
) -> ArrivalAdoptionPlan:
    """Capture Full(S), verify the migration registry and sign one exact anchor."""
    target_path = Path(target).resolve()
    if descriptor.role is not Profile.AUTHORITY or not descriptor.lineage:
        raise AdoptionPreparationRefused("adoption requires a lineage-pinned Authority descriptor")
    if not isinstance(selected_head, Head) or selected_head.lineage != descriptor.lineage:
        raise AdoptionPreparationRefused("selected head must name the descriptor lineage")
    if not observer or not isinstance(observer, str):
        raise AdoptionPreparationRefused("adopting observer must be explicit")
    if not credentials.mapped or credentials.signature_verifier is None:
        raise AdoptionPreparationRefused("adoption requires pre-created mapped credentials")
    if not callable(fact_verify) or not callable(arrival_verify):
        raise AdoptionPreparationRefused("adoption requires public FACT and ARRIVAL verifiers")
    if not all(
        isinstance(value, str)
        for value in (reviewed_text, reviewed_sha256, declaration_text)
    ):
        raise AdoptionPreparationRefused("reviewed and published declaration text are required")
    reviewed = reviewed_text.encode("utf-8")
    if hashlib.sha256(reviewed).hexdigest() != reviewed_sha256:
        raise AdoptionPreparationRefused("reviewed snapshot SHA-256 differs from selected text")
    published = declaration_text.encode("utf-8")
    try:
        if target_path.read_bytes() != published:
            raise AdoptionPreparationRefused(
                "published declaration bytes differ from supplied authority text"
            )
    except OSError as exc:
        raise AdoptionPreparationRefused(f"copied declaration is unavailable: {exc}") from exc
    documents = _selected_documents(declaration_text, target_path, descriptor)
    try:
        reviewed_ast = parse_vertex(reviewed_text, path=target_path)
        validate_vertex(reviewed_ast)
        reviewed_documents = tuple(
            document.as_json() for document in vertex_to_documents(reviewed_ast)
        )
    except Exception as exc:
        raise AdoptionPreparationRefused(f"reviewed source snapshot is invalid: {exc}") from exc
    if reviewed_documents != documents:
        raise AdoptionPreparationRefused(
            "published authority declaration differs from reviewed source documents"
        )
    ledger = query = None
    try:
        ledger, query = registry.open(descriptor)
        captured = ledger.head()
        if captured != selected_head or ledger.verify(Full(through=selected_head)) != selected_head:
            raise AdoptionPreparationRefused(
                "selected migration head is stale or not Full-verified"
            )
        records = tuple(ledger.scan(through=selected_head))
        _scan_identity(records, captured.lineage)
        keys, _evidence = key_registry_from_records(records, arrival_verify)
        valid = tuple(key for key, _ordinal in keys.keys_valid_at(observer, captured.ordinal + 1))
        if not valid:
            raise AdoptionPreparationRefused("adopting observer has no key valid at selected head")
        for document in documents:
            if document["kind"] != DECL_OBSERVER_DEFINED:
                continue
            key = document["payload"].get("key")
            if key is not None:
                named = document["subject"]
                named_valid = {
                    item for item, _ordinal in keys.keys_valid_at(named, captured.ordinal + 1)
                }
                if key not in named_valid:
                    raise AdoptionPreparationRefused(
                        f"declared observer {named!r} key is not valid at selected head"
                    )
        if ledger.capabilities().max_atomic_records == 0:
            raise AdoptionPreparationRefused("backend cannot append an adoption anchor")
    except AdoptionPreparationRefused:
        raise
    except Exception as exc:
        raise AdoptionPreparationRefused(f"cannot establish adoption prefix: {exc}") from exc
    finally:
        _close(query)
        _close(ledger)

    try:
        preflight_projection_maintenance(registry, descriptor, through=captured)
    except Exception as exc:
        raise AdoptionPreparationRefused(
            f"required projection maintenance is unavailable at S: {exc}"
        ) from exc

    session = CredentialResolutionSession()
    context = CapturedSigningContext(captured, ((observer, valid),), ())
    namespace = credentials.binding_namespace
    assert namespace is not None
    def _sign(domain: SigningDomain) -> Callable[[str, str], str | None]:
        def sign(named: str, digest: str) -> str | None:
            request = CredentialRequest(namespace, named, domain, CredentialPurpose.AUTHORSHIP)
            return session.sign(
                credentials, request, digest, context=context,
                authorized_keys=context.keys_for_author(named), required=True,
            )
        return sign
    at = time.time() if authored_at is None else authored_at
    try:
        draft = build_declaration_anchor_draft(
            lineage=captured.lineage, authored_at=at, observer=observer,
            documents=documents, fact_signer=_sign(SigningDomain.FACT),
            arrival_signer=_sign(SigningDomain.ARRIVAL),
        )
    except CredentialBindingRefused as exc:
        raise AdoptionPreparationRefused(f"mapped adoption binding refused: {exc}") from exc
    except Exception as exc:
        raise AdoptionPreparationRefused(f"cannot sign adoption anchor: {exc}") from exc
    bindings = session.evidence
    if (
        len(bindings) != 2
        or bindings[0].request.domain is not SigningDomain.FACT
        or bindings[1].request.domain is not SigningDomain.ARRIVAL
        or bindings[0].public_key != bindings[1].public_key
        or bindings[0].public_key not in valid
    ):
        raise AdoptionPreparationRefused("mapped adoption bindings disagree")
    bound_key = bindings[0].public_key
    if not isinstance(draft.signature, str) or not isinstance(
        draft.body.get("signature"), str
    ):
        raise AdoptionPreparationRefused("draft signatures are missing")
    inner_digest = fact_commitment_hash(
        "_decl.genesis", at, observer, "", draft.body["payload"]
    )
    outer_digest = content_commitment("fact", at, observer, "", dict(draft.body))
    try:
        fact_ok = fact_verify(bound_key, draft.body["signature"], inner_digest)
        arrival_ok = arrival_verify(bound_key, draft.signature, outer_digest)
    except Exception as exc:
        raise AdoptionPreparationRefused(
            f"independent adoption signature verification failed: {exc}"
        ) from exc
    if not fact_ok or not arrival_ok:
        raise AdoptionPreparationRefused(
            "draft signatures do not verify under the selected mapped public key"
        )
    return ArrivalAdoptionPlan(
        target_path, descriptor, captured.lineage,
        ReadBasis(captured.lineage, captured, None, None), captured, observer,
        reviewed_text, reviewed_sha256, declaration_text,
        hashlib.sha256(published).hexdigest(), documents, draft,
        _exact_drafts((draft,)), bindings,
    )


def _intent_data(plan: ArrivalAdoptionPlan, phase: str) -> dict[str, Any]:
    return {
        "schema": _SCHEMA, "phase": phase, "target": str(plan.target_path),
        "descriptor": _descriptor_dict(plan.descriptor),
        "captured_head": _head_dict(plan.captured_head),
        "observer": plan.observer, "reviewed_text": plan.reviewed_text,
        "reviewed_sha256": plan.reviewed_sha256,
        "declaration_text": plan.declaration_text,
        "declaration_sha256": plan.declaration_sha256,
        "drafts": json.loads(plan.exact_drafts), "exact_drafts": plan.exact_drafts,
        "bindings": [
            {"request": {"namespace": evidence.request.namespace,
                         "observer": evidence.request.observer,
                         "domain": evidence.request.domain.value,
                         "purpose": evidence.request.purpose.value},
             "key_ref": evidence.key_ref, "algorithm": evidence.algorithm,
             "public_key": evidence.public_key, "provenance": evidence.provenance}
            for evidence in plan.credential_bindings
        ],
    }


def _result(plan: ArrivalAdoptionPlan, status: str, head: Head,
            commit: Commit | None, projection: ProjectionSyncResult | None,
            phase: str, file_written: bool,
            observed_head: Head | None = None) -> ArrivalAdoptionResult:
    return ArrivalAdoptionResult(
        status, plan.target_path, plan.descriptor, plan.lineage, plan.basis,
        plan.captured_head, head, commit, plan.fact_ids, None, phase,
        file_written, projection, plan.credential_bindings, observed_head,
    )


def _finish(registry: BackendRegistry, plan: ArrivalAdoptionPlan,
            intent: Path, data: dict[str, Any], head: Head,
            commit: Commit | None, status: str,
            failure_hook: Callable[[str], None] | None,
            observed_head: Head | None = None) -> ArrivalAdoptionResult:
    projection = None
    try:
        projection = sync_projection(registry, plan.descriptor, through=head)
        if projection.projected_after.ordinal < head.ordinal:
            raise AdoptionApplyError("projection did not reach adoption head")
        data["phase"] = "synced"
        _replace_json(intent, data)
        if failure_hook:
            failure_hook("after-sync")
        _require_cache(plan)
        data["phase"] = "published"
        _replace_json(intent, data)
        if failure_hook:
            failure_hook("after-publication")
        _remove_intent(intent)
    except Exception as exc:
        raise AdoptionCommittedIncomplete(
            "adoption committed but projection or cache reconciliation remains",
            phase=data["phase"], head=head, commit=commit,
            intent_path=intent, cause=exc,
        ) from exc
    return _result(
        plan, status, head, commit, projection, "published", False, observed_head
    )


def apply_arrival_adoption(
    registry: BackendRegistry, plan: ArrivalAdoptionPlan,
    *, failure_hook: Callable[[str], None] | None = None,
) -> ArrivalAdoptionResult:
    """Reserve the signed draft, CAS against S, then sync and reconcile cache."""
    with _declaration_lock(plan.target_path):
        if _exact_drafts((plan.draft,)) != plan.exact_drafts:
            raise AdoptionApplyError("prepared adoption draft changed")
        _require_cache(plan)
        intent = arrival_adoption_intent_path(plan.target_path)
        data = _intent_data(plan, "prepared")
        try:
            _write_exclusive_json(intent, data)
        except FileExistsError as exc:
            raise AdoptionApplyError(f"unfinished adoption intent exists: {intent}") from exc
        if failure_hook:
            try:
                failure_hook("after-intent")
            except Exception as exc:
                raise AdoptionRecoveryRequired(
                    "adoption intent is durable before append; recover explicitly",
                    intent_path=intent, cause=exc,
                ) from exc
        ledger = query = None
        try:
            try:
                ledger, query = registry.open(plan.descriptor)
                current = ledger.head()
            except Exception as exc:
                raise AdoptionRecoveryRequired(
                    "adoption intent is durable but custody could not be opened",
                    intent_path=intent, cause=exc,
                ) from exc
            if current != plan.captured_head:
                raise AdoptionStale(
                    "migration head changed before adoption append; recover intent "
                    "to prove whether it is superseded",
                    intent_path=intent,
                )
            try:
                preflight_projection_maintenance(
                    registry, plan.descriptor, through=plan.captured_head
                )
            except Exception as exc:
                raise AdoptionRecoveryRequired(
                    "adoption intent is durable but required projection maintenance "
                    "is unavailable before append",
                    intent_path=intent, cause=exc,
                ) from exc
            try:
                commit = ledger.append(plan.captured_head, (plan.draft,))
            except Exception as exc:
                from .arrival_contract import ContractRefusal
                from .arrival_head_seam import NotWitnessed
                if isinstance(exc, ContractRefusal):
                    raise AdoptionStale(
                        f"adoption append refused: {exc}; recover intent to "
                        "establish its disposition",
                        intent_path=intent,
                    ) from exc
                if isinstance(exc, NotWitnessed):
                    data["phase"] = "append-unwitnessed"
                    with suppress(Exception):
                        _replace_json(intent, data)
                    raise AdoptionUnwitnessed(
                        "adoption committed without a complete witness",
                        head=exc.head, commit=exc.commit, intent_path=intent, cause=exc,
                    ) from exc
                data["phase"] = "append-unknown"
                with suppress(Exception):
                    _replace_json(intent, data)
                raise AdoptionOutcomeUnknown(
                    "adoption append outcome is unknown", head=plan.captured_head,
                    intent_path=intent, cause=exc,
                ) from exc
            data["phase"] = "appended"
            try:
                _replace_json(intent, data)
                if failure_hook:
                    failure_hook("after-append")
            except Exception as exc:
                raise AdoptionCommittedIncomplete(
                    "adoption committed but append phase recording failed",
                    phase="appended", head=commit.after, commit=commit,
                    intent_path=intent, cause=exc,
                ) from exc
        finally:
            _close(query)
            _close(ledger)
        return _finish(registry, plan, intent, data, commit.after, commit,
                       "applied", failure_hook)


def _intent_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AdoptionApplyError(f"adoption intent {label} must be an object")
    return value


def _intent_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise AdoptionApplyError(f"adoption intent {label} must be a nonempty string")
    return value


def _plan_from_intent(data: Any) -> ArrivalAdoptionPlan:
    root = _intent_object(data, "root")
    if root.get("schema") != _SCHEMA:
        raise AdoptionApplyError("unsupported adoption intent")
    if root.get("phase") not in {
        "prepared", "append-unknown", "append-unwitnessed", "appended",
        "synced", "published",
    }:
        raise AdoptionApplyError("adoption intent phase is invalid")
    try:
        captured_data = _intent_object(root["captured_head"], "captured head")
        ordinal = captured_data["ordinal"]
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
            raise AdoptionApplyError("adoption intent captured ordinal is invalid")
        captured = Head(
            _intent_string(captured_data["lineage"], "captured lineage"),
            ordinal,
            _intent_string(captured_data["record_hash"], "captured hash"),
        )
        descriptor_data = _intent_object(root["descriptor"], "descriptor")
        for field in ("backend", "location", "lineage", "role"):
            _intent_string(descriptor_data[field], f"descriptor {field}")
        descriptor = _descriptor_from(descriptor_data)
        target = Path(_intent_string(root["target"], "target")).resolve()
        text = _intent_string(root["declaration_text"], "authority text")
        digest = _intent_string(root["declaration_sha256"], "authority hash")
        reviewed_text = _intent_string(root["reviewed_text"], "reviewed text")
        reviewed_sha256 = _intent_string(root["reviewed_sha256"], "reviewed hash")
        observer = _intent_string(root["observer"], "observer")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise AdoptionApplyError("adoption intent declaration bytes do not verify")
        if hashlib.sha256(reviewed_text.encode("utf-8")).hexdigest() != reviewed_sha256:
            raise AdoptionApplyError("adoption intent reviewed snapshot bytes do not verify")
        raw_drafts = root["drafts"]
        if not isinstance(raw_drafts, list):
            raise AdoptionApplyError("adoption intent drafts must be a list")
        exact_drafts = _intent_string(root["exact_drafts"], "exact drafts")
        drafts = _drafts_from_exact(raw_drafts, exact_drafts)
        if len(drafts) != 1 or drafts[0].body.get("id") != captured.lineage:
            raise AdoptionApplyError("adoption intent has no exact lineage anchor")
        raw_bindings = root["bindings"]
        if not isinstance(raw_bindings, list):
            raise AdoptionApplyError("adoption intent bindings must be a list")
        evidence = []
        for index, raw in enumerate(raw_bindings):
            item = _intent_object(raw, f"binding {index}")
            request = _intent_object(item["request"], f"binding {index} request")
            evidence.append(CredentialBindingEvidence(
                CredentialRequest(
                    _intent_string(request["namespace"], "binding namespace"),
                    _intent_string(request["observer"], "binding observer"),
                    SigningDomain(_intent_string(request["domain"], "binding domain")),
                    CredentialPurpose(_intent_string(request["purpose"], "binding purpose")),
                ),
                _intent_string(item["key_ref"], "binding key ref"),
                _intent_string(item["algorithm"], "binding algorithm"),
                _intent_string(item["public_key"], "binding public key"),
                _intent_string(item["provenance"], "binding provenance"),
            ))
        if descriptor.lineage != captured.lineage:
            raise AdoptionApplyError("adoption intent descriptor and captured lineage disagree")
        return ArrivalAdoptionPlan(
            target, descriptor, captured.lineage,
            ReadBasis(captured.lineage, captured, None, None), captured,
            observer, reviewed_text, reviewed_sha256,
            text, digest, (), drafts[0], exact_drafts, tuple(evidence),
        )
    except AdoptionApplyError:
        raise
    except Exception as exc:
        raise AdoptionApplyError(f"malformed adoption intent: {exc}") from exc


def _revalidate_reserved(
    ledger: Any,
    plan: ArrivalAdoptionPlan,
    *,
    fact_verify: Callable[[str, str, str], bool],
    arrival_verify: Callable[[str, str, str], bool],
) -> None:
    """Prove a public recovery intent is the same authorized adoption proposal."""
    try:
        if plan.descriptor.role is not Profile.AUTHORITY or plan.descriptor.lineage != plan.lineage:
            raise AdoptionApplyError("reserved descriptor is not this lineage's Authority")
        if ledger.verify(Full(through=plan.captured_head)) != plan.captured_head:
            raise AdoptionApplyError("reserved predecessor is not Full-verified")
        records = tuple(ledger.scan(through=plan.captured_head))
        _scan_identity(records, plan.lineage)
        registry, _evidence = key_registry_from_records(records, arrival_verify)
        valid = {
            key for key, _ordinal in registry.keys_valid_at(
                plan.observer, plan.captured_head.ordinal + 1
            )
        }
        if not valid:
            raise AdoptionApplyError("reserved author has no key valid at S")
        documents = _selected_documents(
            plan.declaration_text, plan.target_path, plan.descriptor
        )
        reviewed_ast = parse_vertex(plan.reviewed_text, path=plan.target_path)
        validate_vertex(reviewed_ast)
        reviewed_documents = tuple(
            document.as_json() for document in vertex_to_documents(reviewed_ast)
        )
        if reviewed_documents != documents:
            raise AdoptionApplyError("reserved reviewed documents differ from authority form")
        for document in documents:
            if document["kind"] != DECL_OBSERVER_DEFINED:
                continue
            key = document["payload"].get("key")
            if key is not None and key not in {
                item for item, _ordinal in registry.keys_valid_at(
                    document["subject"], plan.captured_head.ordinal + 1
                )
            }:
                raise AdoptionApplyError("reserved observer key was not valid at S")

        bindings = plan.credential_bindings
        if len(bindings) != 2:
            raise AdoptionApplyError("reserved FACT and ARRIVAL binding evidence is incomplete")
        by_domain = {item.request.domain: item for item in bindings}
        if set(by_domain) != {SigningDomain.FACT, SigningDomain.ARRIVAL}:
            raise AdoptionApplyError("reserved binding domains are invalid or duplicated")
        fact_binding = by_domain[SigningDomain.FACT]
        arrival_binding = by_domain[SigningDomain.ARRIVAL]
        for item in bindings:
            if (
                item.request.observer != plan.observer
                or item.request.purpose is not CredentialPurpose.AUTHORSHIP
                or not all((item.key_ref, item.algorithm, item.public_key, item.provenance))
                or item.public_key not in valid
            ):
                raise AdoptionApplyError("reserved binding is not authorized at S")
        if (
            fact_binding.request.namespace != arrival_binding.request.namespace
            or fact_binding.key_ref != arrival_binding.key_ref
            or fact_binding.public_key != arrival_binding.public_key
        ):
            raise AdoptionApplyError("reserved FACT and ARRIVAL bindings disagree")

        draft = plan.draft
        payload = json.dumps(
            {"protocol": 1, "documents": [dict(document) for document in documents]},
            ensure_ascii=False, separators=(",", ":"),
        )
        body = draft.body
        if (
            draft.kind != "fact" or draft.observer != plan.observer
            or draft.origin != "" or body.get("id") != plan.lineage
            or body.get("kind") != "_decl.genesis"
            or body.get("ts") != draft.authored_at
            or body.get("observer") != plan.observer
            or body.get("origin") != "" or body.get("payload") != payload
            or not isinstance(body.get("signature"), str)
            or not isinstance(draft.signature, str)
        ):
            raise AdoptionApplyError("reserved declaration anchor differs from reviewed documents")
        expected_body = body_of_fact_row((
            plan.lineage, "_decl.genesis", draft.authored_at,
            plan.observer, "", payload, body["signature"],
        ))
        if dict(body) != expected_body:
            raise AdoptionApplyError("reserved declaration anchor has unexpected fields")
        fact_digest = fact_commitment_hash(
            "_decl.genesis", draft.authored_at, plan.observer, "", payload
        )
        arrival_digest = content_commitment(
            "fact", draft.authored_at, plan.observer, "", dict(body)
        )
        key = fact_binding.public_key
        if not fact_verify(key, body["signature"], fact_digest):
            raise AdoptionApplyError("reserved FACT signature does not verify")
        if not arrival_verify(key, draft.signature, arrival_digest):
            raise AdoptionApplyError("reserved ARRIVAL signature does not verify")
    except AdoptionApplyError:
        raise
    except Exception as exc:
        raise AdoptionApplyError(f"cannot revalidate reserved adoption: {exc}") from exc


def recover_arrival_adoption(
    registry: BackendRegistry, intent: Path | str,
    *, fact_verify: Callable[[str, str, str], bool],
    arrival_verify: Callable[[str, str, str], bool],
    failure_hook: Callable[[str], None] | None = None,
) -> ArrivalAdoptionResult:
    """Reconcile the exact reserved row; never re-sign or append a duplicate."""
    intent_path = Path(intent).resolve()
    suffix = ".arrival-adopt.intent"
    if (
        not intent_path.name.endswith(suffix)
        or len(intent_path.name) <= len(suffix)
    ):
        raise AdoptionApplyError("adoption intent path has an invalid suffix")
    target_path = intent_path.with_name(intent_path.name[:-len(suffix)])
    if not callable(fact_verify) or not callable(arrival_verify):
        raise AdoptionApplyError("recovery requires public FACT and ARRIVAL verifiers")
    with _declaration_lock(target_path):
        try:
            data = json.loads(intent_path.read_text(encoding="utf-8"))
            plan = _plan_from_intent(data)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise AdoptionApplyError(f"cannot read adoption intent: {exc}") from exc
        if plan.target_path != target_path:
            raise AdoptionApplyError("adoption intent path does not match its target")
        ledger = query = None
        try:
            try:
                ledger, query = registry.open(plan.descriptor)
            except Exception as exc:
                raise AdoptionRecoveryRequired(
                    "reserved adoption intent is durable but custody could not be opened",
                    intent_path=intent_path, cause=exc,
                ) from exc
            predecessor = ledger.head_at(Watermark(plan.lineage, plan.captured_head.ordinal))
            if predecessor != plan.captured_head:
                raise AdoptionStale("adoption predecessor hash changed")
            _revalidate_reserved(
                ledger, plan, fact_verify=fact_verify,
                arrival_verify=arrival_verify,
            )
            current = ledger.head()
            observed_head = current
            if current == predecessor:
                _require_cache(plan)
                try:
                    preflight_projection_maintenance(
                        registry, plan.descriptor, through=predecessor
                    )
                except Exception as exc:
                    raise AdoptionRecoveryRequired(
                        "reserved adoption cannot append without required projection "
                        "maintenance",
                        intent_path=intent_path, cause=exc,
                    ) from exc
                try:
                    commit = ledger.append(predecessor, (plan.draft,))
                except Exception as exc:
                    from .arrival_contract import ContractRefusal
                    from .arrival_head_seam import NotWitnessed
                    if isinstance(exc, ContractRefusal):
                        raise AdoptionStale(
                            f"reserved adoption CAS refused: {exc}",
                            intent_path=intent_path,
                        ) from exc
                    if isinstance(exc, NotWitnessed):
                        raise AdoptionUnwitnessed(
                            "reserved adoption committed without a complete witness",
                            head=exc.head, commit=exc.commit, intent_path=intent_path,
                            cause=exc,
                        ) from exc
                    raise AdoptionOutcomeUnknown(
                        "reserved adoption append outcome is unknown", head=predecessor,
                        intent_path=intent_path, cause=exc,
                    ) from exc
                current = commit.after
                observed_head = current
                data["phase"] = "appended"
                try:
                    _replace_json(intent_path, data)
                    if failure_hook:
                        failure_hook("after-append")
                except Exception as exc:
                    raise AdoptionCommittedIncomplete(
                        "reserved adoption committed but phase recording failed",
                        phase="appended", head=current, commit=commit,
                        intent_path=intent_path, cause=exc,
                    ) from exc
            else:
                if current.ordinal < predecessor.ordinal + 1:
                    raise AdoptionStale("reserved adoption has no successor at S+1")
                adoption_head = ledger.head_at(
                    Watermark(plan.lineage, predecessor.ordinal + 1)
                )
                if ledger.verify(Full(through=adoption_head)) != adoption_head:
                    raise AdoptionStale("reserved adoption suffix is not Full-verified")
                successor = ledger.read(predecessor.ordinal + 1)
                if not _record_matches_draft(successor, plan.draft):
                    _remove_intent(intent_path)
                    raise AdoptionStale(
                        "a different Full-verified record occupies S+1; "
                        "superseded adoption intent retired"
                    )
                commit = Commit(
                    before=predecessor,
                    records=(successor,),
                    after=adoption_head,
                    durability=DurabilityReceipt(
                        ledger.capabilities().durability,
                        "reconciled from Full-verified custody; original witness unavailable",
                    ),
                )
                current = adoption_head
                data["phase"] = "appended"
                try:
                    _replace_json(intent_path, data)
                except Exception as exc:
                    raise AdoptionCommittedIncomplete(
                        "adoption row is committed but appended phase recording failed",
                        phase="appended", head=current, commit=commit,
                        intent_path=intent_path, cause=exc,
                    ) from exc
        finally:
            _close(query)
            _close(ledger)
        return _finish(registry, plan, intent_path, data, current, commit,
                       "recovered", failure_hook, observed_head)
