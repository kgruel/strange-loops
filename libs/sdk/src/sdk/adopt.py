"""Explicit adoption of a reviewed declaration into an Arrival history.

This is deliberately a narrow wrapper around the engine ceremony.  It does
not read migration sidecar inputs, mint keys, import legacy material, or infer
a reviewed declaration from the locator cache.  Callers bring the reviewed
snapshot, the published authority cache, and the selected, already-verified
Arrival head.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.arrival_contract import Head, Profile
from engine.arrival_registry import BackendRegistry
from engine.credentials import CredentialProvider, WriteCredentials

from .types import (
    ArrivalAdoptionResult,
    SdkValueError,
    StoreDescriptorInfo,
    TargetUnsupported,
)

if TYPE_CHECKING:
    from engine.arrival_adoption import ArrivalAdoptionResult as EngineArrivalAdoptionResult
    from engine.arrival_maintenance import ProjectionSyncResult
    from engine.credentials import CredentialBindingEvidence

__all__ = ["adopt_arrival", "recover_arrival_adoption"]


def _mapped_adoption_credentials(
    vertex_path: Path,
    credentials: CredentialProvider | WriteCredentials | None,
) -> WriteCredentials:
    """Resolve only an already-created mapped binding for the adoption author."""
    if credentials is None:
        raise SdkValueError("Arrival adoption requires a pre-created mapped credential binding")
    if isinstance(credentials, WriteCredentials):
        supplied = credentials
    else:
        provider = getattr(credentials, "for_write", None)
        if not callable(provider):
            raise SdkValueError("Arrival adoption requires a mapped credential provider")
        try:
            supplied = provider(vertex_path)
        except SdkValueError:
            raise
        except Exception as exc:
            raise SdkValueError(
                "Arrival adoption could not resolve its mapped credential binding"
            ) from exc
    if not isinstance(supplied, WriteCredentials):
        raise SdkValueError("credential provider did not return WriteCredentials")
    if not supplied.mapped:
        raise SdkValueError("Arrival adoption requires a pre-created mapped credential binding")
    return supplied


def _domain_verifier(domain: str):
    """Verify a public signature in one explicit protocol domain."""
    from sign import ed25519

    def verify(key: str, signature: str, digest: str) -> bool:
        try:
            public = ed25519.public_key_from_b64(key)
        except ValueError:
            return False
        return ed25519.verify(public, signature, digest.encode(), domain=domain)

    return verify


def _head_dict(head: Head | None) -> dict[str, Any] | None:
    if head is None:
        return None
    return {
        "lineage": head.lineage,
        "ordinal": head.ordinal,
        "record_hash": head.record_hash,
    }


def _projection_dict(projection: ProjectionSyncResult | None) -> dict[str, Any] | None:
    if projection is None:
        return None
    return {
        "captured_head": _head_dict(projection.captured_head),
        "target": _head_dict(projection.target),
        "projected_before": _head_dict(projection.projected_before),
        "projected_after": _head_dict(projection.projected_after),
        "view_generation": projection.view_generation,
        "changed": projection.changed,
        "rebuilt": projection.rebuilt,
    }


def _binding_dicts(bindings: Sequence[CredentialBindingEvidence]) -> list[dict[str, Any]]:
    """Copy public mapped evidence without retaining provider-private state."""
    result: list[dict[str, Any]] = []
    for evidence in bindings:
        request = evidence.request
        result.append(
            {
                "request": {
                    "namespace": request.namespace,
                    "observer": request.observer,
                    "domain": request.domain.value,
                    "purpose": request.purpose.value,
                },
                "key_ref": evidence.key_ref,
                "algorithm": evidence.algorithm,
                "public_key": evidence.public_key,
                "provenance": evidence.provenance,
            }
        )
    return result


def _result(
    raw: EngineArrivalAdoptionResult,
    *,
    reviewed_sha256: str | None = None,
    declaration_sha256: str | None = None,
) -> ArrivalAdoptionResult:
    """Project the engine outcome into the stable SDK result shape."""
    descriptor = raw.descriptor
    lineage = raw.lineage
    fact_id = getattr(raw, "fact_id", lineage)
    intent_path = raw.intent_path
    return ArrivalAdoptionResult(
        status=raw.status,
        target_path=str(raw.target_path),
        store=StoreDescriptorInfo.from_descriptor(descriptor),
        basis=raw.basis,
        lineage=lineage,
        captured_head=raw.captured_head,
        head=raw.head,
        commit=raw.commit,
        fact_id=fact_id,
        intent_path=None if intent_path is None else str(intent_path),
        phase=raw.phase,
        file_written=raw.file_written,
        reviewed_sha256=reviewed_sha256,
        declaration_sha256=declaration_sha256,
        projection=_projection_dict(raw.projection),
        credential_bindings=_binding_dicts(raw.credential_bindings),
        observed_head=raw.observed_head,
    )


def adopt_arrival(
    target: Path | str,
    *,
    selected_head: Head,
    reviewed_text: str,
    reviewed_sha256: str,
    declaration_text: str,
    observer: str,
    credentials: CredentialProvider | WriteCredentials,
    registry: BackendRegistry | None = None,
) -> ArrivalAdoptionResult:
    """Append one reviewed declaration anchor at an explicit migration head.

    ``reviewed_text`` and ``reviewed_sha256`` name the pre-migration snapshot
    the caller approved. ``declaration_text`` is the separately captured,
    currently published authority cache that will be anchored only after the
    engine proves their declaration meanings agree. The target must resolve to
    an authority descriptor and the mapped binding must already exist.
    """
    from .errors import normalize_exception
    from .target import _arrival_descriptor

    try:
        vertex_path = Path(target).resolve()
        resolved = _arrival_descriptor(vertex_path)
        if resolved is None:
            raise TargetUnsupported(
                f"adopt_arrival requires an explicit Arrival .vertex target: {vertex_path}"
            )
        _path, _ast, descriptor = resolved
        if descriptor.role is not Profile.AUTHORITY:
            raise SdkValueError("Arrival adoption requires an authority descriptor")
        write_credentials = _mapped_adoption_credentials(vertex_path, credentials)
        active_registry = (
            registry if registry is not None else BackendRegistry.with_builtin_backends()
        )
        from engine.arrival_adoption import apply_arrival_adoption, prepare_arrival_adoption

        plan = prepare_arrival_adoption(
            active_registry,
            descriptor,
            target=vertex_path,
            selected_head=selected_head,
            reviewed_text=reviewed_text,
            reviewed_sha256=reviewed_sha256,
            declaration_text=declaration_text,
            observer=observer,
            credentials=write_credentials,
            fact_verify=_domain_verifier(FACT_DOMAIN),
            arrival_verify=_domain_verifier(ARRIVAL_DOMAIN),
        )
        raw = apply_arrival_adoption(active_registry, plan)
    except Exception as exc:
        normalized = normalize_exception(exc, context={"captured_head": selected_head})
        if normalized is exc:
            raise
        raise normalized from exc
    return _result(
        raw,
        reviewed_sha256=reviewed_sha256,
        declaration_sha256=hashlib.sha256(declaration_text.encode("utf-8")).hexdigest(),
    )


def recover_arrival_adoption(
    intent: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> ArrivalAdoptionResult:
    """Recover a retained adoption intent without resolving or re-signing keys."""
    from engine.arrival_adoption import recover_arrival_adoption as recover

    from .errors import normalize_exception

    active_registry = registry if registry is not None else BackendRegistry.with_builtin_backends()
    try:
        raw = recover(
            active_registry,
            intent,
            fact_verify=_domain_verifier(FACT_DOMAIN),
            arrival_verify=_domain_verifier(ARRIVAL_DOMAIN),
        )
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    return _result(raw)
