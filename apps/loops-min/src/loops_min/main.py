"""Small JSON-only process client for the headless SDK.

The CLI deliberately contains no target probing or storage implementation.
Every supported operation delegates to an export from :mod:`sdk`; operations
that do not yet have an Arrival SDK contract return a typed unavailable result.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from typing import Any

from sdk import (
    AdmissionFailed,
    CeremonyFailed,
    CommittedEmissionError,
    CredentialBindingIncomplete,
    EmissionFailed,
    MappedCredentialProvider,
    SdkError,
    SdkValueError,
    TargetError,
    TargetUnsupported,
    edit_declaration,
    emit_batch,
    emit_fact,
    export_target,
    init_vertex,
    inspect_declaration,
    preview_emission,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
    recover_declaration,
    resolve_arrival_target,
    resolve_entity,
    restore_forward,
    search_facts,
    sync_search_index,
    sync_target,
    verify_target,
)
from sdk.errors import (
    ArrivalRefusal,
    CommittedOutcome,
    ProjectionOutcomeUnknown,
    normalize_exception,
)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_UNSUPPORTED = 3
EXIT_REFUSAL = 4
EXIT_ADMISSION = 5
EXIT_COMMITTED = 6
EXIT_INTERNAL = 70


class UnavailableOperation(Exception):
    """The SDK has not exposed this operation's Arrival contract yet."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"{operation} is unavailable until its Arrival SDK operation exists")


class UsageError(Exception):
    """A malformed invocation that should use the JSON process envelope."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


def _finite_float(raw: str) -> float:
    try:
        value = float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    try:
        json.dumps(value, allow_nan=False)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a finite number")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="loops-min",
        description="JSON process client for the Loops headless SDK",
    )
    parser.add_argument("--pretty", action="store_true", help="indent JSON output")
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=_ArgumentParser
    )

    def target_command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("target")
        # Permit the presentation switch either before or after the command.
        # Suppressing the subparser default preserves a root-level --pretty.
        sub.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return sub

    target_command("target", "resolve an explicit Arrival descriptor")
    target_command("inspect", "inspect a declaration")
    target_command("summary", "read a target summary")
    facts = target_command("facts", "read a bounded fact page")
    facts.add_argument("--limit", type=int, default=50)
    facts.add_argument("--kind")
    facts.add_argument("--observer")
    facts.add_argument("--order", choices=("newest", "oldest"), default="newest")
    facts.add_argument("--include-internal", action="store_true")
    fact = target_command("fact", "look up one fact by ID or prefix")
    fact.add_argument("fact_id")
    state = target_command("state", "read folded state")
    state.add_argument("--kind")
    ticks = target_command("ticks", "read tick records")
    ticks.add_argument("--name")
    search = target_command("search", "search facts through the SDK")
    search.add_argument("query")
    search.add_argument("--kind")
    search.add_argument("--limit", type=int, default=50)
    target_command("search-sync", "build exact-prefix Arrival search coverage")
    timeline = target_command("timeline", "read the SDK timeline")
    timeline.add_argument("--start-ts", type=float)
    timeline.add_argument("--end-ts", type=float)
    timeline.add_argument("--limit", type=int, default=100)
    timeline.add_argument("--order", choices=("newest", "oldest"), default="oldest")
    entity = target_command("resolve", "resolve a folded entity key")
    entity.add_argument("kind")
    entity.add_argument("key")
    entity.add_argument("value")
    target_command("sync", "synchronize a derived index through the SDK")
    target_command("verify", "fully verify an Arrival custody prefix")
    export = target_command("export", "write an exact captured Arrival prefix")
    export.add_argument("output", help="new output artifact path")
    restore = target_command("restore-forward", "restore an existing exact Arrival copy")
    restore.add_argument("receiver", help="receiver descriptor target")

    def mapped_credentials(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--credential-root", required=True)
        sub.add_argument("--credential-namespace", required=True)
        sub.add_argument("--receipt-observer", required=True)

    init = target_command("init", "initialize a mapped Arrival file target")
    init.add_argument("--name")
    init.add_argument("--location", required=True)
    init.add_argument("--observer", required=True)
    init.add_argument("--strict", action="store_true")
    mapped_credentials(init)

    def emission_command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = target_command(name, help_text)
        sub.add_argument("kind")
        payload = sub.add_mutually_exclusive_group(required=True)
        payload.add_argument("--payload-json")
        payload.add_argument("--payload-file")
        sub.add_argument("--observer", required=True)
        sub.add_argument("--origin", default="")
        sub.add_argument("--ts", type=_finite_float)
        sub.add_argument("--id", dest="id_override")
        mapped_credentials(sub)
        return sub

    emission_command("emit", "emit one fact through the Arrival SDK")
    emission_command("preview", "preview one fact emission through the Arrival SDK")

    batch = target_command("emit-batch", "atomically emit a fact batch through the SDK")
    facts = batch.add_mutually_exclusive_group(required=True)
    facts.add_argument("--facts-json")
    facts.add_argument("--facts-file")
    mapped_credentials(batch)

    declaration = target_command("declaration", "apply one Arrival declaration edit")
    declaration.add_argument("--proposed-file", required=True)
    declaration.add_argument("--observer", required=True)
    mapped_credentials(declaration)

    recovery = commands.add_parser(
        "declaration-recover",
        help="recover one interrupted Arrival declaration edit intent",
    )
    recovery.add_argument("intent")
    recovery.add_argument(
        "--pretty", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )

    target_command(
        "init-recover",
        "recover one interrupted Arrival initialization intent",
    )

    def binding_command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("root")
        sub.add_argument("--namespace", required=True)
        sub.add_argument("--observer", required=True)
        sub.add_argument("--token", required=True)
        sub.add_argument(
            "--pretty", action="store_true", default=argparse.SUPPRESS,
            help=argparse.SUPPRESS,
        )
        return sub

    binding_command("credential-create", "create one explicit mapped credential binding")
    binding_command("credential-recover", "recover one mapped credential binding intent")
    existing = binding_command(
        "credential-bind-existing-ref",
        "bind an observer to an existing managed key reference",
    )
    existing.add_argument("--key-ref", required=True)
    existing.add_argument("--expected-public-key", required=True)
    legacy_import = binding_command(
        "credential-import-legacy",
        "import one explicitly selected legacy credential",
    )
    legacy_import.add_argument("--vertex", required=True)

    # These names are reserved for the Arrival SDK contracts that are still
    # being implemented. Keeping them in help makes the process boundary
    # discoverable without routing them through legacy writer code.
    for name, help_text in (
        ("replicate", "replicate an exact prefix (SDK operation pending)"),
        ("admit", "admit records into an authority (SDK operation pending)"),
    ):
        target_command(name, help_text)

    return parser


def _as_dict(result: Any) -> dict[str, Any]:
    method = getattr(result, "as_dict", None)
    if not callable(method):
        raise TypeError(f"SDK result {type(result).__name__} has no as_dict()")
    value = method()
    if not isinstance(value, dict):
        raise TypeError(f"SDK result {type(result).__name__} did not serialize to an object")
    return value


def _json_argument(raw: str, *, name: str, shape: type) -> Any:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise UsageError(f"{name} contains duplicate key {key!r}")
            value[key] = item
        return value

    def nonfinite(value: str) -> None:
        raise UsageError(f"{name} contains non-finite number {value!r}")

    try:
        value = json.loads(raw, object_pairs_hook=object_pairs, parse_constant=nonfinite)
        # JSON exponent overflow (for example 1e999) is not passed through
        # parse_constant, so validate the decoded transport once more.
        json.dumps(value, allow_nan=False)
    except UsageError:
        raise
    except (TypeError, ValueError) as exc:
        raise UsageError(f"{name} is not valid finite JSON: {exc}") from exc
    if not isinstance(value, shape):
        expected = "object" if shape is dict else "array"
        raise UsageError(f"{name} must be a JSON {expected}")
    return value


def _read_transport_file(path: str, *, name: str) -> str:
    """Read one JSON transport source with strict UTF-8 decoding.

    The binary stdin path is intentional: the default text wrapper may use
    ``surrogateescape``, which would otherwise let invalid UTF-8 cross the
    process boundary. Text-only streams remain useful for in-process tests.
    """
    try:
        if path == "-":
            if sys.stdin is None:
                raise UsageError(f"cannot read {name}: stdin is unavailable")
            binary = getattr(sys.stdin, "buffer", None)
            if binary is not None:
                raw = binary.read()
                if isinstance(raw, bytes):
                    return raw.decode("utf-8")
                if isinstance(raw, str):
                    return raw
                raise TypeError("stdin buffer did not return text or bytes")
            raw = sys.stdin.read()
            if isinstance(raw, bytes):
                return raw.decode("utf-8")
            if isinstance(raw, str):
                return raw
            raise TypeError("stdin did not return text or bytes")
        with open(path, encoding="utf-8", errors="strict") as stream:
            return stream.read()
    except (OSError, ValueError, TypeError) as exc:
        # UnicodeError is a ValueError; closed streams also raise ValueError.
        raise UsageError(f"cannot read {name}: {exc}") from exc


def _transport_json(
    args: argparse.Namespace,
    *,
    json_attribute: str,
    file_attribute: str,
    json_name: str,
    file_name: str,
    shape: type,
) -> Any:
    raw_json = getattr(args, json_attribute)
    if raw_json is not None:
        return _json_argument(raw_json, name=json_name, shape=shape)
    raw_file = getattr(args, file_attribute)
    return _json_argument(
        _read_transport_file(raw_file, name=file_name), name=file_name, shape=shape
    )


def _credentials(args: argparse.Namespace) -> MappedCredentialProvider:
    return MappedCredentialProvider(
        args.credential_root,
        namespace=args.credential_namespace,
        receipt_observer=args.receipt_observer,
    )


def _binding_provider(args: argparse.Namespace) -> MappedCredentialProvider:
    return MappedCredentialProvider(args.root, namespace=args.namespace)


def _require_arrival_target(target: str) -> None:
    # This is an SDK classification gate, not a second CLI target resolver.
    # The writer repeats descriptor resolution under its own captured contract.
    resolve_arrival_target(target)


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
    if command == "init-recover":
        return _as_dict(
            init_vertex(args.target, store_type="arrival", recover=True)
        )
    if command == "credential-create":
        return _as_dict(
            _binding_provider(args).create_binding(args.observer, token=args.token)
        )
    if command == "credential-recover":
        return _as_dict(
            _binding_provider(args).recover_binding(args.observer, token=args.token)
        )
    if command == "credential-bind-existing-ref":
        return _as_dict(
            _binding_provider(args).bind_existing_ref(
                args.observer,
                args.key_ref,
                args.expected_public_key,
                token=args.token,
            )
        )
    if command == "credential-import-legacy":
        return _as_dict(
            _binding_provider(args).import_legacy(
                args.vertex, args.observer, token=args.token
            )
        )
    if command == "init":
        return _as_dict(
            init_vertex(
                args.target,
                name=args.name,
                store_type="arrival",
                backend="file",
                location=args.location,
                observer=args.observer,
                strict=args.strict,
                credentials=_credentials(args),
            )
        )
    if command in {"emit", "preview"}:
        payload = _transport_json(
            args,
            json_attribute="payload_json",
            file_attribute="payload_file",
            json_name="--payload-json",
            file_name="--payload-file",
            shape=dict,
        )
        _require_arrival_target(args.target)
        operation = preview_emission if command == "preview" else emit_fact
        return _as_dict(
            operation(
                args.target,
                args.kind,
                payload,
                observer=args.observer,
                origin=args.origin,
                ts=args.ts,
                id_override=args.id_override,
                credentials=_credentials(args),
            )
        )
    if command == "emit-batch":
        facts = _transport_json(
            args,
            json_attribute="facts_json",
            file_attribute="facts_file",
            json_name="--facts-json",
            file_name="--facts-file",
            shape=list,
        )
        if not all(isinstance(item, dict) for item in facts):
            raise UsageError("--facts-json or --facts-file must contain only JSON objects")
        _require_arrival_target(args.target)
        return _as_dict(emit_batch(args.target, facts, credentials=_credentials(args)))
    if command == "declaration":
        try:
            with open(args.proposed_file, encoding="utf-8") as stream:
                proposed_text = stream.read()
        except (OSError, UnicodeError) as exc:
            raise UsageError(f"cannot read --proposed-file: {exc}") from exc
        _require_arrival_target(args.target)
        return _as_dict(
            edit_declaration(
                args.target,
                proposed_text,
                observer=args.observer,
                credentials=_credentials(args),
            )
        )
    if command == "declaration-recover":
        return _as_dict(recover_declaration(args.intent))
    if command == "target":
        return _as_dict(resolve_arrival_target(args.target))
    if command == "inspect":
        return _as_dict(inspect_declaration(args.target))
    if command == "summary":
        return _as_dict(read_summary(args.target))
    if command == "facts":
        return _as_dict(
            read_facts(
                args.target,
                limit=args.limit,
                kind=args.kind,
                observer=args.observer,
                order=args.order,
                include_internal=args.include_internal,
            )
        )
    if command == "fact":
        return _as_dict(read_fact_by_id(args.target, args.fact_id))
    if command == "state":
        return _as_dict(read_state(args.target, kind=args.kind))
    if command == "ticks":
        return _as_dict(read_ticks(args.target, name=args.name))
    if command == "search":
        return _as_dict(search_facts(args.target, args.query, kind=args.kind, limit=args.limit))
    if command == "search-sync":
        return _as_dict(sync_search_index(args.target))
    if command == "timeline":
        return _as_dict(
            read_timeline(
                args.target,
                start_ts=args.start_ts,
                end_ts=args.end_ts,
                limit=args.limit,
                order=args.order,
            )
        )
    if command == "resolve":
        return _as_dict(resolve_entity(args.target, args.kind, args.key, args.value))
    if command == "sync":
        return _as_dict(sync_target(args.target))
    if command == "verify":
        return _as_dict(verify_target(args.target))
    if command == "restore-forward":
        return _as_dict(restore_forward(args.target, args.receiver))
    if command == "export":
        return _as_dict(export_target(args.target, args.output))
    raise UnavailableOperation(command)


def _error_details(exc: BaseException) -> dict[str, Any]:
    raw_details = getattr(exc, "details", {})
    try:
        details = dict(raw_details) if isinstance(raw_details, Mapping) else {}
    except (TypeError, ValueError):
        details = {}
    for name in ("fact_id", "observer", "kind", "vertex", "operation"):
        value = getattr(exc, name, None)
        if value is not None:
            details[name] = value
    return details


def _exit_code(exc: BaseException) -> int:
    if isinstance(exc, UsageError):
        return EXIT_USAGE
    if isinstance(exc, UnavailableOperation):
        return EXIT_UNSUPPORTED
    if isinstance(exc, (SdkValueError, argparse.ArgumentError)):
        return EXIT_USAGE
    if isinstance(exc, (AdmissionFailed, CeremonyFailed)):
        return EXIT_ADMISSION
    if isinstance(exc, CommittedOutcome):
        return EXIT_COMMITTED
    if isinstance(exc, CredentialBindingIncomplete):
        return EXIT_COMMITTED
    if isinstance(exc, CommittedEmissionError):
        return EXIT_COMMITTED
    if isinstance(exc, TargetUnsupported):
        return EXIT_UNSUPPORTED
    if isinstance(exc, TargetError):
        return EXIT_REFUSAL
    if isinstance(exc, (ArrivalRefusal, ProjectionOutcomeUnknown)):
        return EXIT_REFUSAL
    if isinstance(exc, (EmissionFailed, SdkError)):
        return EXIT_REFUSAL
    return EXIT_INTERNAL


def _write(value: dict[str, Any], *, pretty: bool) -> None:
    encoded = json.dumps(
        value,
        allow_nan=False,
        indent=2 if pretty else None,
        sort_keys=True,
    )
    sys.stdout.write(encoded + "\n")


def _write_error(exc: BaseException, *, command: str, pretty: bool) -> None:
    """Write one safe error document, even if an exception detail is not JSON-native."""
    try:
        message = str(exc)
    except Exception:  # noqa: BLE001 - keep the process boundary serializable
        message = type(exc).__name__
    fallback = {
        "type": type(exc).__name__ if not isinstance(exc, UnavailableOperation) else "Unavailable",
        "message": message,
        "details": _error_details(exc),
    }
    try:
        serializer = getattr(exc, "as_dict", None)
        error = serializer() if callable(serializer) else fallback
        if not isinstance(error, dict):
            error = fallback
        _write({"ok": False, "error": error}, pretty=pretty)
    except (TypeError, ValueError):
        _write(
            {
                "ok": False,
                "error": {
                    "type": "Serialization",
                    "message": "the SDK error could not be serialized as JSON",
                    "details": {},
                },
            },
            pretty=pretty,
        )
    print(f"loops-min {command}: {fallback['message']}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        invocation = sys.argv[1:] if argv is None else argv
        pretty = "--pretty" in invocation
        _write_error(exc, command="parse", pretty=pretty)
        return EXIT_USAGE
    except SystemExit as exc:
        # argparse has already emitted help/usage. Preserve its conventional
        # status while keeping normal operation's stdout JSON-only.
        return int(exc.code or 0) if not isinstance(exc.code, str) else 1

    try:
        result = _dispatch(args)
    except Exception as exc:  # noqa: BLE001 - serialize the process boundary failure
        normalized = normalize_exception(exc)
        code = _exit_code(normalized)
        _write_error(normalized, command=args.command, pretty=args.pretty)
        return code

    try:
        _write({"ok": True, "result": result}, pretty=args.pretty)
    except (TypeError, ValueError):
        exc = TypeError("the SDK result could not be serialized as JSON")
        _write_error(exc, command=args.command, pretty=args.pretty)
        return EXIT_INTERNAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
