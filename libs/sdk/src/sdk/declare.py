"""Declaration inspection and vertex scaffolding operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
from engine.arrival_contract import Commit
from engine.arrival_registry import BackendRegistry
from engine.credentials import CredentialProvider, WriteCredentials
from engine.declaration import load_declaration_status
from engine.probe import probe_target
from lang.loader import parse_vertex_file

from .types import (
    DeclarationInspectionResult,
    DeclarationPlanResult,
    InitVertexResult,
    KindMutationResult,
    SdkValueError,
    StoreDescriptorInfo,
    TargetError,
    TargetNotFound,
    TargetUnsupported,
    _commit_dict,
)

__all__ = [
    "init_vertex", "inspect_declaration", "edit_declaration",
    "recover_declaration", "DeclarationEditResult",
    "DeclarationPreviewResult",
]


@dataclass(frozen=True)
class DeclarationEditResult(KindMutationResult):
    """Serializable public outcome for descriptor-backed declaration edits.

    ``file_written`` means this call published the cache. ``phase`` describes
    the reconciled state, which can already be published when recovery starts.
    """

    schema: str = "loops.sdk/declaration-edit/v2"
    read_path: str = "arrival"
    target_path: str = ""
    store: StoreDescriptorInfo | None = None
    basis: dict[str, Any] | None = None
    lineage: str | None = None
    captured_head: dict[str, Any] | None = None
    head: dict[str, Any] | None = None
    commit: Commit | None = None
    fact_ids: tuple[str, ...] = ()
    intent_path: str | None = None
    phase: str = ""
    file_written: bool = False
    changes: list[dict[str, Any]] | None = None

    def as_dict(self) -> dict[str, Any]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["store"] = None if self.store is None else asdict(self.store)
        result["fact_ids"] = list(self.fact_ids)
        result["commit"] = _commit_dict(self.commit)
        return result


@dataclass(frozen=True)
class DeclarationPreviewResult(DeclarationPlanResult):
    """v2 semantic preview carrying the explicit Arrival read basis."""

    schema: str = "loops.sdk/declaration-preview/v2"
    read_path: str = "arrival"
    store: StoreDescriptorInfo | None = None
    basis: dict[str, Any] | None = None
    lineage: str | None = None
    captured_head: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _head_dict(head: Any) -> dict[str, Any] | None:
    if head is None:
        return None
    return {
        "lineage": head.lineage,
        "ordinal": head.ordinal,
        "record_hash": head.record_hash,
    }


def _change_dict(change: Any) -> dict[str, Any] | str:
    if hasattr(change, "as_dict"):
        return change.as_dict()
    if hasattr(change, "_asdict"):
        return dict(change._asdict())
    return str(change)


def _arrival_result(result: Any) -> DeclarationEditResult:
    commit = result.commit
    changes = (
        None
        if result.changes is None
        else [_change_dict(change) for change in result.changes]
    )
    return DeclarationEditResult(
        status=result.status,
        mode="arrival-edit",
        vertex_path=str(result.target_path),
        target_path=str(result.target_path),
        store=StoreDescriptorInfo.from_descriptor(result.descriptor),
        basis=asdict(result.basis),
        lineage=result.lineage,
        captured_head=_head_dict(result.captured_head),
        head=_head_dict(result.head),
        commit=commit,
        fact_ids=tuple(result.fact_ids),
        intent_path=None if result.intent_path is None else str(result.intent_path),
        phase=result.phase,
        file_written=result.file_written,
        changes=changes,
    )


def _arrival_credentials(
    vertex_path: Path, credentials: CredentialProvider | WriteCredentials | None
) -> WriteCredentials:
    if credentials is None:
        from .emit import CustodyCredentialProvider

        credentials = CustodyCredentialProvider()
    if isinstance(credentials, WriteCredentials):
        return credentials
    provider = getattr(credentials, "for_write", None)
    if not callable(provider):
        raise SdkValueError("Arrival declaration edits require a write credential provider")
    supplied = provider(vertex_path)
    if not isinstance(supplied, WriteCredentials):
        raise SdkValueError("credential provider did not return WriteCredentials")
    return supplied


def _arrival_verifiers():
    from sign import ed25519

    def verify(domain: str, key: str, signature: str, digest: str) -> bool:
        try:
            public = ed25519.public_key_from_b64(key)
        except ValueError:
            return False
        return ed25519.verify(public, signature, digest.encode(), domain=domain)

    return (
        lambda key, signature, digest: verify(FACT_DOMAIN, key, signature, digest),
        lambda key, signature, digest: verify(ARRIVAL_DOMAIN, key, signature, digest),
    )


def edit_declaration(
    target: Path | str,
    proposed_text: str,
    *,
    observer: str,
    credentials: CredentialProvider | WriteCredentials | None = None,
    registry: BackendRegistry | None = None,
) -> DeclarationEditResult:
    """Prepare and apply one signed edit against an explicit Arrival descriptor.

    The descriptor is parsed before any legacy target probe. The engine owns
    the attested CURRENT basis, signed draft construction, full-head append,
    durable intent, projection sync, and cache recovery protocol.
    """
    return _edit_arrival_declaration(
        target,
        proposed_text,
        observer=observer,
        credentials=credentials,
        registry=registry,
    )


def _edit_arrival_declaration(
    target: Path | str,
    proposed_text: str,
    *,
    observer: str,
    credentials: CredentialProvider | WriteCredentials | None,
    registry: BackendRegistry | None,
    source_cache_bytes: bytes | None = None,
    require_cache_basis: bool = False,
) -> DeclarationEditResult:
    from engine.arrival_declarations import (
        apply_declaration_edit,
        prepare_declaration_edit,
    )

    from .errors import normalize_exception
    from .target import _arrival_descriptor

    vertex_path = Path(target).resolve()
    resolved = _arrival_descriptor(vertex_path)
    if resolved is None:
        raise TargetUnsupported(
            f"edit_declaration requires an explicit Arrival .vertex target: {vertex_path}"
        )
    _path, _ast, descriptor = resolved
    active_registry = (
        registry if registry is not None else BackendRegistry.with_builtin_backends()
    )
    write_credentials = _arrival_credentials(vertex_path, credentials)
    fact_verify, arrival_verify = _arrival_verifiers()
    try:
        plan = prepare_declaration_edit(
            active_registry,
            descriptor,
            target=vertex_path,
            proposed_text=proposed_text,
            observer=observer,
            credentials=write_credentials,
            fact_verify=fact_verify,
            arrival_verify=arrival_verify,
            source_cache_bytes=source_cache_bytes,
            require_cache_basis=require_cache_basis,
        )
        result = apply_declaration_edit(active_registry, plan)
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    return _arrival_result(result)


def recover_declaration(
    intent: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> DeclarationEditResult:
    """Recover one interrupted explicit Arrival declaration edit."""
    from engine.arrival_declarations import recover_declaration_edit

    from .errors import normalize_exception

    active_registry = (
        registry if registry is not None else BackendRegistry.with_builtin_backends()
    )
    try:
        result = recover_declaration_edit(active_registry, intent)
    except Exception as exc:
        normalized = normalize_exception(exc)
        if normalized is exc:
            raise
        raise normalized from exc
    return _arrival_result(result)


def _kdl_quote(value: str, *, field: str) -> str:
    """Encode one generated single-line KDL string value safely."""
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise SdkValueError(f"{field} contains KDL control characters")
    return json.dumps(value, ensure_ascii=False)


def init_vertex(
    target: Path | str,
    *,
    name: str | None = None,
    store_type: str = "sqlite",
    store_path: str | Path | None = None,
    is_root: bool = False,
    observer: str | None = None,
    strict: bool = False,
    overwrite: bool = False,
    backend: str | None = None,
    location: str | Path | None = None,
    documents: list[dict] | None = None,
    signer=None,
    fact_signer=None,
    public_key: str | None = None,
    credentials: CredentialProvider | None = None,
    recover: bool = False,
    registry: BackendRegistry | None = None,
) -> InitVertexResult:
    """Scaffold a new Loops .vertex declaration file.

    Parameters:
        target: Target .vertex file path to create.
        name: Name of the vertex (defaults to target file stem).
        store_type: Backing store format ('sqlite' or 'jsonl').
        store_path: Custom store path (defaults to .loops/data/<name>.db or .jsonl).
        is_root: If True, scaffolds an aggregate root discovery vertex.
        observer: Initial observer identity to register.
        strict: If True, declares 'strict true'.
        overwrite: If True, overwrites existing file.

    Returns:
        InitVertexResult detailing the created vertex file and storage paths.
    """
    vertex_path = Path(target).resolve()

    # Arrival initialization is an explicit extension of this existing SDK
    # operation.  Keeping the legacy arm below preserves callers that ask for
    # SQLite/JSONL scaffolding while the clean Arrival cut is adopted; no
    # legacy opener is reached by the descriptor arm.
    arrival_requested = (
        store_type.lower() == "arrival"
        or backend is not None
        or location is not None
        or documents is not None
        or recover
    )
    if arrival_requested and not is_root:
        return _init_arrival(
            vertex_path,
            name=name,
            strict=strict,
            observer=observer,
            backend=backend,
            location=location,
            store_path=store_path,
            documents=documents,
            signer=signer,
            fact_signer=fact_signer,
            public_key=public_key,
            credentials=credentials,
            recover=recover,
            overwrite=overwrite,
            registry=registry,
        )
    if credentials is not None:
        raise TargetUnsupported(
            "initialization credentials require an explicit Arrival descriptor target"
        )
    if vertex_path.exists() and not overwrite:
        raise TargetError(f"vertex file already exists: {vertex_path}")

    v_name = name or vertex_path.stem

    if is_root:
        content = (
            f'name "{v_name}"\n'
            "// Root vertex — discovers all .vertex files under this directory\n"
            'discover "./**/*.vertex"\n'
        )
        resolved_store = None
    else:
        ext = ".jsonl" if store_type.lower() == "jsonl" else ".db"
        default_store = f".loops/data/{v_name}{ext}"
        resolved_store = str(store_path) if store_path is not None else default_store

        lines = [f'name "{v_name}"', f'store "{resolved_store}"']
        if strict:
            lines.append("strict true")
        lines.append("")

        if observer:
            # Ensure keypair exists for initial observer
            from custody import ensure_signing_key

            keypair = ensure_signing_key(vertex_path, observer=observer)
            lines.append("observers {")
            lines.append(f"  {observer} {{")
            lines.append(f'    key "{keypair.public_b64}"')
            lines.append("  }")
            lines.append("}")
            lines.append("")

        lines.append("loops {")
        lines.append("  item {")
        lines.append("    fold {")
        lines.append('      items "collect" 100')
        lines.append("    }")
        lines.append("  }")
        lines.append("}")
        lines.append("")
        content = "\n".join(lines)

    # Ensure parent directory exists
    vertex_path.parent.mkdir(parents=True, exist_ok=True)
    vertex_path.write_text(content, encoding="utf-8")

    return InitVertexResult(
        target_path=str(vertex_path),
        name=v_name,
        store_path=resolved_store,
        store_type=store_type,
        is_root=is_root,
        file_written=True,
    )


def _init_arrival(
    vertex_path: Path,
    *,
    name: str | None,
    strict: bool,
    observer: str | None,
    backend: str | None,
    location: str | Path | None,
    store_path: str | Path | None,
    documents: list[dict] | None,
    signer,
    fact_signer,
    public_key: str | None,
    credentials: CredentialProvider | None,
    recover: bool,
    overwrite: bool,
    registry: BackendRegistry | None,
) -> InitVertexResult:
    """Compose custody and language inputs for the engine initializer."""
    from engine.arrival_contract import Profile, StoreDescriptor
    from engine.arrival_initialization import (
        arrival_intent_path,
        initialize_arrival,
        new_lineage,
        recover_arrival_initialization,
    )
    from engine.declaration import validate_arrival_runtime_identity
    from lang import parse_vertex, vertex_to_documents

    from .errors import normalize_exception

    if overwrite:
        raise TargetError("Arrival initialization never overwrites an existing artifact")
    intent_data = None
    if recover:
        try:
            intent_data = json.loads(arrival_intent_path(vertex_path).read_text())
            reserved = intent_data["descriptor"]
            reserved_observer = str(intent_data["observer"])
            if observer is None:
                observer = reserved_observer
            elif observer != reserved_observer:
                raise SdkValueError(
                    "recovery observer disagrees with the reserved initialization intent"
                )
            if backend is not None and backend != reserved["backend"]:
                raise SdkValueError(
                    "recovery backend disagrees with the reserved initialization intent"
                )
            if public_key is not None and public_key != str(intent_data["public_key"]):
                raise SdkValueError(
                    "recovery public key disagrees with the reserved initialization intent"
                )
            requested_location = location if location is not None else store_path
            if reserved["backend"] == "file" and requested_location is not None:
                requested_location = str(
                    (vertex_path.parent / str(requested_location)).resolve()
                    if not Path(str(requested_location)).is_absolute()
                    else Path(str(requested_location)).resolve()
                )
            if (
                requested_location is not None
                and str(requested_location) != str(reserved["location"])
            ):
                raise SdkValueError(
                    "recovery location disagrees with the reserved initialization intent"
                )
        except SdkValueError:
            raise
        except (OSError, ValueError, KeyError) as exc:
            raise TargetError(f"cannot load Arrival initialization intent: {exc}") from exc
    if not observer:
        raise SdkValueError("Arrival initialization requires observer")
    if location is not None and store_path is not None and str(location) != str(store_path):
        raise SdkValueError(
            "Arrival initialization received conflicting location and store_path"
        )
    if location is None:
        location = store_path
    v_name = name or vertex_path.stem
    if not recover:
        # The SDK scaffold declares item, and the runtime also adds cite.
        # Refuse these collisions before the default custody path creates keys.
        validate_arrival_runtime_identity(v_name, ("item",), refusal=SdkValueError)
    chosen_backend = backend or "file"
    if location is None:
        relative_location = f".loops/data/{v_name}.arrival"
        descriptor_location = str((vertex_path.parent / relative_location).resolve())
    elif chosen_backend == "file":
        relative_location = str(location)
        descriptor_location = str((vertex_path.parent / relative_location).resolve())
    else:
        # A DSN is opaque to the SDK as well as to the engine registry.
        relative_location = str(location)
        descriptor_location = relative_location

    # Verification is independent of where signing callables came from.  A
    # caller-supplied pair still has to prove both protocol domains against
    # the supplied public key before an intent or mint is attempted.
    from custody.signing import ARRIVAL_DOMAIN, FACT_DOMAIN
    from sign import ed25519

    def _verify(domain: str, key: str, signature: str, digest: str) -> bool:
        try:
            public = ed25519.public_key_from_b64(key)
        except ValueError:
            return False
        return ed25519.verify(public, signature, digest.encode(), domain=domain)

    def _fact_verify(key: str, signature: str, digest: str) -> bool:
        return _verify(FACT_DOMAIN, key, signature, digest)

    def _arrival_verify(key: str, signature: str, digest: str) -> bool:
        return _verify(ARRIVAL_DOMAIN, key, signature, digest)

    fact_verify = _fact_verify
    arrival_verify = _arrival_verify
    if not recover:
        # The SDK is the custody owner. An injected signer/key pair is useful
        # to headless deployments; absent one, key creation/loading is the
        # same explicit custody operation used by the existing init command.
        from custody import arrival_signer_for, ensure_signing_key, fact_signer_for
        from engine.credentials import (
            CredentialBindingEvidence,
            CredentialPurpose,
            CredentialRequest,
            ResolvedCredential,
            SigningDomain,
        )

        if credentials is not None:
            if signer is not None or fact_signer is not None:
                raise SdkValueError(
                    "mapped Arrival initialization does not accept separate signer inputs"
                )
            write_credentials = _arrival_credentials(vertex_path, credentials)
            if not write_credentials.mapped or write_credentials.binding_resolver is None:
                raise SdkValueError(
                    "Arrival initialization requires a mapped provider or explicit signers"
                )
            fact_request = CredentialRequest(
                write_credentials.binding_namespace or "",
                observer,
                SigningDomain.FACT,
                CredentialPurpose.INITIALIZATION,
            )
            arrival_request = CredentialRequest(
                write_credentials.binding_namespace or "",
                observer,
                SigningDomain.ARRIVAL,
                CredentialPurpose.INITIALIZATION,
            )
            try:
                fact_credential = write_credentials.binding_resolver(fact_request)
                arrival_credential = write_credentials.binding_resolver(arrival_request)
            except Exception as exc:
                normalized = normalize_exception(exc)
                if normalized is not exc:
                    raise normalized from exc
                raise SdkValueError(
                    "Arrival initialization could not resolve its pre-created mapped binding"
                ) from exc
            if fact_credential is None or arrival_credential is None:
                raise SdkValueError(
                    "mapped Arrival initialization requires a pre-created founding binding"
                )
            def valid_bootstrap_credential(value: object, request: CredentialRequest) -> bool:
                if not isinstance(value, ResolvedCredential):
                    return False
                evidence = value.evidence
                return (
                    isinstance(evidence, CredentialBindingEvidence)
                    and evidence.request == request
                    and all(
                        isinstance(item, str) and bool(item)
                        for item in (
                            evidence.key_ref,
                            evidence.algorithm,
                            evidence.public_key,
                            evidence.provenance,
                        )
                    )
                    and callable(value.sign_digest)
                )

            fact_valid = valid_bootstrap_credential(fact_credential, fact_request)
            arrival_valid = valid_bootstrap_credential(arrival_credential, arrival_request)
            if not fact_valid or not arrival_valid:
                raise SdkValueError(
                    "mapped Arrival initialization resolver returned contradictory binding evidence"
                )
            if (
                fact_credential.evidence.public_key != arrival_credential.evidence.public_key
                or fact_credential.evidence.key_ref != arrival_credential.evidence.key_ref
            ):
                raise SdkValueError(
                    "mapped Arrival initialization requires FACT and ARRIVAL bindings with one key"
                )
            if public_key is not None and public_key != fact_credential.evidence.public_key:
                raise SdkValueError(
                    "mapped Arrival initialization public_key disagrees with its binding"
                )
            public_key = fact_credential.evidence.public_key

            def mapped_arrival_signer(author: str, digest: str) -> str | None:
                return arrival_credential.sign_digest(digest) if author == observer else None

            def mapped_fact_signer(author: str, digest: str) -> str | None:
                return fact_credential.sign_digest(digest) if author == observer else None

            signer = mapped_arrival_signer
            fact_signer = mapped_fact_signer
        elif signer is None and fact_signer is None and public_key is None:
            try:
                keypair = ensure_signing_key(vertex_path, observer=observer)
            except ValueError as exc:
                raise SdkValueError(str(exc)) from exc
            public_key = keypair.public_b64
            signer = arrival_signer_for(vertex_path)
            fact_signer = fact_signer_for(vertex_path)
        elif (
            signer is None
            or fact_signer is None
            or public_key is None
            or not callable(signer)
            or not callable(fact_signer)
        ):
            raise SdkValueError(
                "Arrival initialization custom credentials require arrival signer, "
                "fact signer, and public key"
            )
        if signer is None or fact_signer is None or public_key is None:
            raise SdkValueError("Arrival initialization requires usable custody signers")

    lineage = None
    if not recover:
        lineage = new_lineage()
        lines = [
            f"name {_kdl_quote(v_name, field='vertex name')}",
            f"store {_kdl_quote(relative_location, field='store location')} "
            f"backend={_kdl_quote(chosen_backend, field='backend')} "
            f"lineage={_kdl_quote(lineage, field='lineage')} role=\"authority\"",
        ]
        if strict:
            lines.append("strict true")
        lines.extend(
            [
                "observers {",
                f"  {_kdl_quote(observer, field='observer')} {{",
                f"    key {_kdl_quote(public_key, field='public key')}",
                "  }",
                "}",
                "",
                "loops {",
                "  item {",
                "    fold {",
                '      items "collect" 100',
                "    }",
                "  }",
                "}",
                "",
            ]
        )
        declaration_text = "\n".join(lines)
        try:
            ast = parse_vertex(declaration_text, path=vertex_path)
        except Exception as exc:
            raise SdkValueError(f"invalid Arrival declaration text: {exc}") from exc
        parsed_documents = [doc.as_json() for doc in vertex_to_documents(ast)]
        if documents is None:
            documents = parsed_documents
        elif documents != parsed_documents:
            raise SdkValueError(
                "Arrival declaration text and declaration documents disagree"
            )
        if (
            ast.store_backend is None
            or ast.store_backend.name != chosen_backend
            or ast.store_backend.role != "authority"
            or ast.store_backend.lineage != lineage
        ):
            raise SdkValueError(
                "Arrival declaration must carry the requested backend, lineage and authority role"
            )
    else:
        # Recovery reads the stable observer and descriptor from the intent;
        # the target is not re-rendered and no new lineage is selected.
        try:
            intent_data = intent_data or json.loads(arrival_intent_path(vertex_path).read_text())
            lineage = str(intent_data["lineage"])
            declaration_text = str(intent_data["declaration_text"])
            if documents is None:
                documents = list(intent_data["documents"])
            reserved_descriptor = intent_data["descriptor"]
            chosen_backend = str(reserved_descriptor["backend"])
            descriptor_location = str(reserved_descriptor["location"])
            relative_location = descriptor_location
            parsed = parse_vertex(declaration_text, path=vertex_path)
            v_name = parsed.name
        except (OSError, ValueError, KeyError) as exc:
            raise TargetError(f"cannot load Arrival initialization intent: {exc}") from exc

    descriptor = StoreDescriptor(
        backend=chosen_backend,
        location=descriptor_location,
        lineage=lineage,
        role=Profile.AUTHORITY,
    )
    active_registry = (
        registry if registry is not None else BackendRegistry.with_builtin_backends()
    )
    try:
        if recover:
            result = recover_arrival_initialization(
                active_registry,
                arrival_intent_path(vertex_path),
            )
        else:
            result = initialize_arrival(
                active_registry,
                descriptor,
                target=vertex_path,
                documents=documents or (),
                declaration_text=declaration_text,
                observer=observer,
                public_key=public_key,
                signer=signer,
                fact_signer=fact_signer,
                arrival_signer=signer,
                fact_verify=fact_verify,
                arrival_verify=arrival_verify,
                lineage=lineage,
            )
    except BaseException as exc:
        details = {"intent_path": str(arrival_intent_path(vertex_path))}
        context = {"fact_id": lineage} if lineage is not None else None
        normalized = normalize_exception(exc, context=context)
        if hasattr(normalized, "details"):
            normalized.details.update(details)
        if normalized is exc:
            # Keep SDK exceptions and process-control exceptions exactly as
            # raised.  ``raise exc from exc`` would install a self-cause and
            # obscure both cancellation and an already-established cause.
            raise
        raise normalized from exc
    return InitVertexResult(
        target_path=str(vertex_path),
        name=v_name,
        read_path="arrival",
        store=StoreDescriptorInfo(
            backend=chosen_backend,
            location=descriptor_location,
            lineage=result.lineage,
            role="authority",
        ),
        store_path=relative_location,
        store_type="arrival",
        is_root=False,
        file_written=result.file_written,
        lineage=result.lineage,
        head={
            "lineage": result.head.lineage,
            "ordinal": result.head.ordinal,
            "record_hash": result.head.record_hash,
        },
        phase=result.phase,
    )


def inspect_declaration(
    target: Path | str,
    *,
    registry: BackendRegistry | None = None,
) -> DeclarationInspectionResult:
    """Inspect a .vertex declaration without materializing its projection.

    Parameters:
        target: Path to the .vertex file.
        registry: Optional Arrival backend registry used for descriptor opens.

    Returns:
        DeclarationInspectionResult containing AST metadata, admission rules, and syntax health.
    """
    path = Path(target).resolve()
    if not path.exists():
        raise TargetNotFound(f"target path does not exist: {path}")

    # A descriptor is residence, not a legacy probe hint. Establish its
    # attested bounded snapshot before considering the compatibility branch.
    from .read import _arrival_declaration, _open_arrival_read
    from .target import _arrival_definition

    definition = _arrival_definition(path, allow_aggregate=True)
    if definition is not None and definition[2] is not None:
        definition_path, definition_ast, descriptor = definition
        arrival = (definition_path, definition_ast, descriptor)
        with _open_arrival_read(arrival, registry=registry) as (
            locator_ast,
            descriptor,
            opened,
        ):
            effective_ast, effective_status, _facts, _own_lineage = _arrival_declaration(
                locator_ast, path, opened, allow_aggregate=True
            )
            local_fingerprint = _document_fingerprint(locator_ast)
            effective_fingerprint = _document_fingerprint(effective_ast)
            declared_kinds, declared_observers, cadence_ticks, strict, is_aggregate = (
                _inspection_fields(effective_ast)
            )
            local_combine, local_discover = _inspection_topology(locator_ast)
            effective_combine, effective_discover = _inspection_topology(effective_ast)
            return DeclarationInspectionResult(
                read_path="arrival",
                store=StoreDescriptorInfo.from_descriptor(descriptor),
                basis=opened.basis,
                target_path=str(path),
                name=effective_ast.name,
                status=effective_status,
                local_status=(
                    "matches-effective"
                    if local_fingerprint == effective_fingerprint
                    else "drifted"
                ),
                effective_status=effective_status,
                local_fingerprint=local_fingerprint,
                effective_fingerprint=effective_fingerprint,
                store_mode=descriptor.backend,
                store_path=descriptor.location,
                declared_kinds=declared_kinds,
                declared_observers=declared_observers,
                cadence_ticks=cadence_ticks,
                strict=strict,
                is_aggregate=is_aggregate,
                local_combine=local_combine,
                local_discover=local_discover,
                effective_combine=effective_combine,
                effective_discover=effective_discover,
                syntax_valid=True,
                errors=[],
            )

    # A valid storeless aggregate has no adopted declaration to consult. Its
    # root AST is the exact one just parsed by the target resolver, avoiding a
    # second file read before a legacy probe could observe replacement bytes.
    if (
        definition is not None
        and definition[2] is None
        and definition[1].store is None
        and (definition[1].combine is not None or definition[1].discover is not None)
    ):
        return _frozen_local_aggregate_inspection(definition[0], definition[1])

    probe = probe_target(path)
    if probe.target_type != "vertex":
        raise SdkValueError(
            f"inspect_declaration requires a .vertex target, got {probe.target_type}"
        )

    errors: list[str] = []
    syntax_valid = True
    file_ast = None
    try:
        file_ast = parse_vertex_file(path)
    except Exception as exc:
        syntax_valid = False
        errors.append(str(exc))

    decl_status = None
    if syntax_valid:
        try:
            decl_ast, decl_status = load_declaration_status(path)
        except Exception as exc:
            errors.append(str(exc))

    v_name = getattr(file_ast, "name", path.stem) if file_ast else path.stem
    store_mode = probe.canonical_mode
    store_path = str(probe.canonical_path) if probe.canonical_path else None

    declared_kinds, declared_observers, cadence_ticks, strict, is_aggregate = _inspection_fields(
        file_ast
    )
    local_combine, local_discover = _inspection_topology(file_ast)

    return DeclarationInspectionResult(
        target_path=str(path),
        name=v_name,
        status=decl_status or "uninitialized",
        local_status=decl_status if syntax_valid else "syntax-invalid",
        effective_status=decl_status,
        store_mode=store_mode,
        store_path=store_path,
        declared_kinds=declared_kinds,
        declared_observers=declared_observers,
        cadence_ticks=cadence_ticks,
        strict=strict,
        is_aggregate=is_aggregate,
        local_combine=local_combine,
        local_discover=local_discover,
        syntax_valid=syntax_valid,
        errors=errors,
    )


def _frozen_local_aggregate_inspection(
    path: Path, ast: Any
) -> DeclarationInspectionResult:
    """Return storeless aggregate topology from one retained local AST."""
    declared_kinds, declared_observers, cadence_ticks, strict, is_aggregate = (
        _inspection_fields(ast)
    )
    combine, discover = _inspection_topology(ast)
    fingerprint = _document_fingerprint(ast)
    return DeclarationInspectionResult(
        read_path="local-frozen",
        target_path=str(path),
        name=ast.name,
        status="local-only",
        local_status="frozen-local",
        effective_status="local-only",
        local_fingerprint=fingerprint,
        effective_fingerprint=fingerprint,
        declared_kinds=declared_kinds,
        declared_observers=declared_observers,
        cadence_ticks=cadence_ticks,
        strict=strict,
        is_aggregate=is_aggregate,
        local_combine=combine,
        local_discover=discover,
        effective_combine=None if combine is None else [dict(entry) for entry in combine],
        effective_discover=discover,
        syntax_valid=True,
        errors=[],
    )


def _inspection_fields(ast: Any | None) -> tuple[list[str], list[str], list[str], bool, bool]:
    """Extract public declaration fields from one already-chosen AST."""
    if ast is None:
        return [], [], [], False, False
    return (
        sorted(ast.loops.keys()) if getattr(ast, "loops", None) else [],
        (
            sorted(observer.name for observer in ast.observers)
            if getattr(ast, "observers", None)
            else []
        ),
        sorted(tick.name for tick in ast.cadence) if getattr(ast, "cadence", None) else [],
        getattr(ast, "strict", False),
        getattr(ast, "combine", None) is not None or getattr(ast, "discover", None) is not None,
    )


def _inspection_topology(
    ast: Any | None,
) -> tuple[list[dict[str, str | None]] | None, str | None]:
    """Serialize only one declaration root's unexpanded aggregate shape."""
    if ast is None:
        return None, None
    combine = getattr(ast, "combine", None)
    return (
        None
        if combine is None
        else [{"name": entry.name, "alias": entry.alias} for entry in combine],
        getattr(ast, "discover", None),
    )


def _document_fingerprint(ast: Any) -> str:
    """Hash semantic declaration documents, deliberately excluding residence."""
    from lang import vertex_to_documents

    documents = vertex_to_documents(ast)
    canonical = json.dumps(
        [document.as_json() for document in documents],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
