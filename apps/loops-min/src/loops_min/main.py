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
    EmissionFailed,
    SdkError,
    SdkValueError,
    TargetError,
    TargetUnsupported,
    export_target,
    inspect_declaration,
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
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

    # These names are reserved for the Arrival SDK contracts that are still
    # being implemented. Keeping them in help makes the process boundary
    # discoverable without routing them through legacy writer code.
    for name, help_text in (
        ("init", "initialize an Arrival target (SDK operation pending)"),
        ("emit", "emit a fact (Arrival SDK operation pending)"),
        ("emit-batch", "emit a batch (Arrival SDK operation pending)"),
        ("replicate", "replicate an exact prefix (SDK operation pending)"),
        ("admit", "admit records into an authority (SDK operation pending)"),
        ("declaration", "edit a declaration (Arrival SDK operation pending)"),
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


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    command = args.command
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
