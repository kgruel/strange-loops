"""Operation-fresh signing credentials for engine write coordinators.

This module contains values only.  It has no store, projection, or custody
dependency, so supported Arrival coordinators can accept signer injection
without importing the legacy SQLite handle implementation.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from .arrival_contract import Head

__all__ = [
    "BindingResolver",
    "CredentialBindingEvidence",
    "CredentialBindingRefused",
    "CapturedSigningContext",
    "CredentialProvider",
    "CredentialPurpose",
    "CredentialRequest",
    "ResolvedCredential",
    "SignatureVerifier",
    "SigningDomain",
    "WriteCredentials",
]


class SigningDomain(StrEnum):
    """The protocol domain whose commitment is being signed."""

    FACT = "fact"
    ARRIVAL = "arrival"
    TICK = "tick"


class CredentialPurpose(StrEnum):
    """Why one operation needs a signing credential."""

    AUTHORSHIP = "authorship"
    KEY_INTRODUCTION = "key-introduction"
    RECEIPT = "receipt"
    INITIALIZATION = "initialization"


@dataclass(frozen=True)
class CredentialRequest:
    """An exact local namespace, protocol observer, domain and purpose."""

    namespace: str
    observer: str
    domain: SigningDomain
    purpose: CredentialPurpose

    def __post_init__(self) -> None:
        if not isinstance(self.namespace, str) or not self.namespace:
            raise ValueError("credential namespace must be an exact nonempty string")
        if not isinstance(self.observer, str) or not self.observer:
            raise ValueError("credential observer must be an exact nonempty string")
        if not isinstance(self.domain, SigningDomain):
            raise ValueError("credential domain must be a SigningDomain")
        if not isinstance(self.purpose, CredentialPurpose):
            raise ValueError("credential purpose must be a CredentialPurpose")


@dataclass(frozen=True)
class CredentialBindingEvidence:
    """Serializable public evidence for one resolved local binding."""

    request: CredentialRequest
    key_ref: str
    algorithm: str
    public_key: str
    provenance: str


@dataclass(frozen=True)
class ResolvedCredential:
    """Public binding evidence paired with its private signing operation."""

    evidence: CredentialBindingEvidence
    sign_digest: Callable[[str], str]


BindingResolver = Callable[[CredentialRequest], ResolvedCredential | None]
SignatureVerifier = Callable[[SigningDomain, str, str, str], bool]


class CredentialBindingRefused(ValueError):
    """A mapped binding could not safely authorize one planned signature."""

    def __init__(
        self,
        reason: str,
        *,
        request: CredentialRequest | None = None,
        captured_head: Head | None = None,
        use_position: int | None = None,
        evidence: CredentialBindingEvidence | None = None,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.request = request
        self.captured_head = captured_head
        self.use_position = use_position
        self.evidence = evidence


@dataclass(frozen=True)
class CapturedSigningContext:
    """Immutable authorization evidence derived from one verified prefix."""

    captured_head: Head
    author_keys: tuple[tuple[str, tuple[str, ...]], ...]
    receipt_keys: tuple[str, ...]

    @property
    def use_position(self) -> int:
        return self.captured_head.ordinal + 1

    def keys_for_author(self, observer: str) -> tuple[str, ...]:
        return next(
            (keys for name, keys in self.author_keys if name == observer),
            (),
        )


class CredentialResolutionSession:
    """Operation-local mapped resolution with cross-domain binding coherence."""

    __slots__ = ("_bindings", "_evidence")

    def __init__(self) -> None:
        self._bindings: dict[tuple[str, str], tuple[str, str]] = {}
        self._evidence: list[CredentialBindingEvidence] = []

    @property
    def evidence(self) -> tuple[CredentialBindingEvidence, ...]:
        return tuple(self._evidence)

    def sign(
        self,
        credentials: WriteCredentials,
        request: CredentialRequest,
        digest: str,
        *,
        context: CapturedSigningContext,
        authorized_keys: tuple[str, ...],
        required: bool,
    ) -> str | None:
        """Resolve, authorize and independently verify one mapped signature."""
        resolver = credentials.binding_resolver
        verifier = credentials.signature_verifier
        if not credentials.mapped or resolver is None or verifier is None:
            raise CredentialBindingRefused(
                "mapped signing requires a complete credential configuration",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
            )
        try:
            resolved = resolver(request)
        except CredentialBindingRefused as exc:
            raise CredentialBindingRefused(
                exc.reason,
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=exc.evidence,
            ) from exc
        except Exception as exc:
            raise CredentialBindingRefused(
                "credential resolver failed",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
            ) from exc
        if resolved is None:
            if not required:
                return None
            raise CredentialBindingRefused(
                "missing-required",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
            )
        if not isinstance(resolved, ResolvedCredential):
            raise CredentialBindingRefused(
                "resolver returned an invalid credential value",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
            )
        evidence = resolved.evidence
        if (
            not isinstance(evidence, CredentialBindingEvidence)
            or evidence.request != request
            or not all(
                isinstance(value, str) and bool(value)
                for value in (
                    evidence.key_ref,
                    evidence.algorithm,
                    evidence.public_key,
                    evidence.provenance,
                )
            )
            or not callable(resolved.sign_digest)
        ):
            raise CredentialBindingRefused(
                "resolver returned contradictory binding evidence",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence
                if isinstance(evidence, CredentialBindingEvidence)
                else None,
            )
        if evidence.public_key not in authorized_keys:
            raise CredentialBindingRefused(
                "resolved public key is not authorized at the captured position",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            )
        binding_key = (request.namespace, request.observer)
        binding_value = (evidence.key_ref, evidence.public_key)
        prior = self._bindings.get(binding_key)
        if prior is not None and prior != binding_value:
            raise CredentialBindingRefused(
                "one mapped observer resolved to different bindings across domains",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            )
        try:
            signature = resolved.sign_digest(digest)
        except CredentialBindingRefused as exc:
            raise CredentialBindingRefused(
                exc.reason,
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=exc.evidence or evidence,
            ) from exc
        except Exception as exc:
            raise CredentialBindingRefused(
                "credential signer failed",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            ) from exc
        if not isinstance(signature, str) or not signature:
            raise CredentialBindingRefused(
                "mapped signer returned no signature",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            )
        try:
            verified = verifier(
                request.domain, evidence.public_key, signature, digest
            )
        except CredentialBindingRefused as exc:
            raise CredentialBindingRefused(
                exc.reason,
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=exc.evidence or evidence,
            ) from exc
        except Exception as exc:
            raise CredentialBindingRefused(
                "credential signature verifier failed",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            ) from exc
        if not verified:
            raise CredentialBindingRefused(
                "mapped signature did not verify under its resolved public key",
                request=request,
                captured_head=context.captured_head,
                use_position=context.use_position,
                evidence=evidence,
            )
        self._bindings[binding_key] = binding_value
        self._evidence.append(evidence)
        return signature


@dataclass(frozen=True)
class WriteCredentials:
    """The distinct domain-separated signers supplied for one write.

    ``tick_signer`` signs tick commitments, ``fact_signer`` signs inner fact
    commitments, and ``arrival_signer`` signs outer Arrival envelopes.  A
    missing signer means that axis is unsigned; one signer is never used as a
    fallback for another.
    """

    tick_signer: Callable[[str], str] | None = None
    fact_signer: Callable[[str, str], str | None] | None = None
    arrival_signer: Callable[[str, str], str | None] | None = None
    binding_namespace: str | None = None
    receipt_observer: str | None = None
    binding_resolver: BindingResolver | None = None
    signature_verifier: SignatureVerifier | None = None

    def __post_init__(self) -> None:
        mapped_parts = (
            self.binding_namespace,
            self.binding_resolver,
            self.signature_verifier,
        )
        mapped = all(part is not None for part in mapped_parts)
        if any(part is not None for part in mapped_parts) and not mapped:
            raise ValueError(
                "mapped credentials require namespace, resolver, and verifier together"
            )
        if self.receipt_observer is not None and not mapped:
            raise ValueError("receipt observer requires mapped credentials")
        if mapped and any(
            signer is not None
            for signer in (self.tick_signer, self.fact_signer, self.arrival_signer)
        ):
            raise ValueError("mapped credentials cannot include legacy signer callbacks")
        if self.binding_resolver is not None and not callable(self.binding_resolver):
            raise ValueError("credential binding resolver must be callable")
        if self.signature_verifier is not None and not callable(self.signature_verifier):
            raise ValueError("credential signature verifier must be callable")
        if self.binding_namespace is not None and (
            not isinstance(self.binding_namespace, str) or not self.binding_namespace
        ):
            raise ValueError("credential namespace must be an exact nonempty string")
        if self.receipt_observer is not None and (
            not isinstance(self.receipt_observer, str) or not self.receipt_observer
        ):
            raise ValueError("receipt observer must be an exact nonempty string")

    @property
    def mapped(self) -> bool:
        """Whether signing must use explicit mapped binding resolution."""
        return self.binding_namespace is not None


class CredentialProvider(Protocol):
    """Supply credentials at the moment of each write operation."""

    def for_write(self, vertex: Path) -> WriteCredentials: ...
