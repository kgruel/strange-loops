"""Emit and close action commands — parse args, mutate stores, exit."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from engine import gen_id
from loops.errors import LoopsError

if TYPE_CHECKING:
    from loops.cli.output import Reporter


def _reporter(reporter: "Reporter | None") -> "Reporter":
    """Resolve a Reporter — caller-supplied or the module default."""
    if reporter is None:
        from loops.cli.output import default_reporter
        return default_reporter()
    return reporter


def _build_receipt_lines(
    kind: str,
    fact_id: str,
    status: "object",  # EmitStatus, kept loose to avoid circular import
    unresolved: list,
    refs_resolved_count: int,
    refuse: bool,
    refuse_reasons: list[str],
    vertex_strict_source: bool,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Build receipt content as (warns, success_or_error) tuples of (line, role).

    ``role`` is one of: "error", "warn", "muted" — caller maps to palette.
    Returns (warn_lines, primary_lines):
      * warn_lines — WARN: ... lines (shown unless --quiet AND not strict)
      * primary_lines — either the ERROR + hint (refuse) or the stored: receipt
    """
    warn_lines: list[tuple[str, str]] = []
    primary_lines: list[tuple[str, str]] = []

    kind_declared = getattr(status, "kind_declared", False)
    fold_key_field = getattr(status, "fold_key_field", None)
    fold_key_present = getattr(status, "fold_key_present", True)
    fold_key_value = getattr(status, "fold_key_value", None)

    # WARN composition (also fuels ERROR composition when refuse=True)
    if not kind_declared:
        warn_lines.append((
            f"WARN: kind '{kind}' not declared on this vertex — "
            "fact stored, will not fold",
            "warn",
        ))
    elif fold_key_field is not None and not fold_key_present:
        warn_lines.append((
            f"WARN: kind '{kind}' folds by '{fold_key_field}' but payload has no "
            f"'{fold_key_field}=' field — fact stored, will not fold",
            "warn",
        ))

    for u in unresolved:
        warn_lines.append((
            f"WARN: ref '{getattr(u, 'addr', u)}' did not resolve — dropped",
            "warn",
        ))

    if refuse:
        # Strict refusal — ERROR + hint, no stored line
        for reason in refuse_reasons:
            primary_lines.append((f"ERROR: {reason}", "error"))
        if vertex_strict_source:
            primary_lines.append((
                "hint: vertex declares strict — fix the emit or update the vertex spec",
                "muted",
            ))
        else:
            primary_lines.append((
                "hint: declare the kind in the vertex file, or omit --strict / LOOPS_EMIT_STRICT",
                "muted",
            ))
        return warn_lines, primary_lines

    # Success path — build the stored: line
    if kind_declared and fold_key_present and fold_key_value:
        key_display = fold_key_value
    else:
        key_display = "<no-fold>"

    suffix = ""
    if refs_resolved_count > 0:
        suffix = f"  (refs: {refs_resolved_count} resolved)"
    primary_lines.append((
        f"stored: {kind}/{key_display} @ {fact_id}{suffix}",
        "muted",
    ))

    return warn_lines, primary_lines


def _emit_lines(lines: list[tuple[str, str]]) -> None:
    """Render receipt lines to stderr via painted, mapping role→palette."""
    if not lines:
        return
    from painted import show, Block
    from painted.palette import current_palette
    p = current_palette()
    role_map = {"error": p.error, "warn": p.error, "muted": p.muted}
    for text, role in lines:
        show(Block.text(text, role_map.get(role, p.muted)), file=sys.stderr)


def _resolve_strict(args: argparse.Namespace, vertex_path: Path | None) -> tuple[bool, bool]:
    """Resolve effective strict mode.

    Returns ``(effective_strict, vertex_declared)``:
      * effective_strict — True if any source declares strict
      * vertex_declared — True iff the vertex spec itself declared strict
        (used to shape the receipt's hint message)

    Precedence (any True → strict):
      1. vertex.spec.strict      (no override possible from CLI/env)
      2. LOOPS_EMIT_STRICT=1     (session opt-in)
      3. --strict flag           (per-call opt-in)
    """
    vertex_declared = False
    if vertex_path is not None:
        try:
            from lang import parse_vertex_file
            ast = parse_vertex_file(vertex_path)
            vertex_declared = bool(getattr(ast, "strict", False))
        except Exception:
            vertex_declared = False

    env_strict = os.environ.get("LOOPS_EMIT_STRICT", "") == "1"
    flag_strict = bool(getattr(args, "strict", False))
    return (vertex_declared or env_strict or flag_strict, vertex_declared)


def _apply_input_sources(
    parts: list[str],
    stdin_field: str | None,
    file_specs: list[str],
) -> list[str]:
    """Apply --stdin and --file flags by injecting expanded values into parts.

    ``--stdin FIELD`` reads ``sys.stdin`` once and injects ``FIELD=<content>``.
    ``--file FIELD=PATH`` reads the file at PATH and injects ``FIELD=<content>``.
    A single trailing newline is stripped from both sources (matches echo/file
    convention; internal newlines preserved).

    Errors raised as ``LoopsError``:

    * ``--stdin`` requested but stdin is a TTY (would hang silently)
    * ``--file FIELD=PATH`` where PATH does not exist or is unreadable
    * ``--file`` argument missing ``=`` (must be FIELD=PATH form)
    * field appears both in ``parts`` (as ``FIELD=value``) AND in --stdin/--file
      (conflicting sources — ambiguous intent, refuse rather than guess)
    * same field named in multiple --file flags (which read wins?)
    * field name not a valid identifier

    Returns the augmented parts list. Original ``parts`` is unchanged.
    """
    # Parse --file FIELD=PATH specs into (field, path) tuples
    parsed_files: list[tuple[str, Path]] = []
    for spec in file_specs:
        if "=" not in spec:
            raise LoopsError(
                f"--file expects FIELD=PATH form, got: {spec!r}"
            )
        field, _, path_str = spec.partition("=")
        if not field.isidentifier():
            raise LoopsError(
                f"--file field name is not a valid identifier: {field!r}"
            )
        parsed_files.append((field, Path(path_str).expanduser()))

    # Detect duplicate --file fields (ambiguous: which read wins?)
    file_fields = [f for f, _ in parsed_files]
    if len(set(file_fields)) != len(file_fields):
        seen: set[str] = set()
        dup = next(f for f in file_fields if f in seen or seen.add(f))  # type: ignore[func-returns-value]
        raise LoopsError(
            f"--file specified multiple times for field {dup!r}"
        )

    # Detect --stdin / --file collision on same field
    if stdin_field is not None and stdin_field in file_fields:
        raise LoopsError(
            f"--stdin and --file both target field {stdin_field!r}"
        )

    # Validate --stdin field name
    if stdin_field is not None and not stdin_field.isidentifier():
        raise LoopsError(
            f"--stdin field name is not a valid identifier: {stdin_field!r}"
        )

    # Detect conflict with inline parts (FIELD=value already present)
    inline_fields: set[str] = set()
    for item in parts:
        if "=" in item:
            k, _, _ = item.partition("=")
            if k.isidentifier():
                inline_fields.add(k)

    injected_fields = set(file_fields)
    if stdin_field is not None:
        injected_fields.add(stdin_field)

    collisions = inline_fields & injected_fields
    if collisions:
        names = ", ".join(sorted(collisions))
        raise LoopsError(
            f"field(s) {names} specified both inline and via --stdin/--file "
            "— ambiguous intent, remove one source"
        )

    augmented = list(parts)

    # Read stdin (once, before files — order of injection is cosmetic since
    # _parse_emit_parts builds a dict)
    if stdin_field is not None:
        if sys.stdin.isatty():
            raise LoopsError(
                f"--stdin {stdin_field} requested but stdin is a TTY — "
                "pipe input or use --file"
            )
        content = sys.stdin.read()
        if content.endswith("\n"):
            content = content[:-1]
        augmented.append(f"{stdin_field}={content}")

    # Read files
    for field, path in parsed_files:
        try:
            content = path.read_text()
        except OSError as e:
            raise LoopsError(f"--file {field}={path}: {e}")
        if content.endswith("\n"):
            content = content[:-1]
        augmented.append(f"{field}={content}")

    return augmented


def _parse_emit_parts(parts: list[str]) -> dict[str, str]:
    """Parse emit args into a payload dict.

    Any KEY=VALUE tokens become payload entries. Any trailing non-key=value
    tokens are joined with spaces into payload["message"].

    The ``ref`` key is special: repeated ``ref=X`` occurrences accumulate into
    a single comma-separated value (matching the downstream fold convention
    in ``_make_upsert`` / ``_make_collect``). Both ``ref=A,B`` and
    ``ref=A ref=B`` produce the same payload. This dissolves a long-lived
    footgun where argparse-style dict-overwrite silently dropped all but
    the last ``ref=`` occurrence.
    """
    payload: dict[str, str] = {}
    refs_accum: list[str] = []  # preserve order; dedup-on-insert
    message_parts: list[str] = []

    for item in parts:
        if "=" in item:
            key, _, value = item.partition("=")
            if key.isidentifier():
                if key == "ref":
                    for r in value.split(","):
                        r = r.strip()
                        if r and r not in refs_accum:
                            refs_accum.append(r)
                    continue
                payload[key] = value
                continue
        message_parts.append(item)

    if refs_accum:
        payload["ref"] = ",".join(refs_accum)
    if message_parts:
        payload["message"] = " ".join(message_parts)

    return payload


def cmd_emit(
    args: argparse.Namespace,
    *,
    vertex_path: Path | None = None,
    reporter: "Reporter | None" = None,
) -> int:
    """Inject a fact directly into a vertex store (or print in --dry-run)."""
    _ = _reporter(reporter)  # reserved for future error routing
    from atoms import Fact
    from loops.commands.identity import resolve_observer, validate_emit
    from loops.commands.resolve import (
        loops_home, _find_local_vertex, _resolve_vertex_for_dispatch,
        _resolve_writable_vertex, _resolve_vertex_store_path,
        _resolve_entity_refs, classify_emit_status,
    )
    from painted import show, Block
    from painted.palette import current_palette
    p = current_palette()

    # Resolve observer from flag → env → .vertex declaration
    observer = resolve_observer(args.observer)

    kind = args.kind
    parts = list(args.parts or [])
    template_qualifier = None

    if vertex_path is not None:
        # Vertex-first dispatch: vertex already resolved, no ambiguity
        pass
    else:
        # Legacy path: resolve vertex from args
        vertex_ref = args.vertex

        def _is_path_like(s: str) -> bool:
            return s.endswith(".vertex") or s.startswith("./") or s.startswith("/")

        if vertex_ref is not None:
            # Local-first resolution (matches vertex-first dispatch behavior)
            local_candidate = _resolve_vertex_for_dispatch(vertex_ref)
            if local_candidate is not None:
                vertex_path = local_candidate
            else:
                # Try config-level resolution (handles slashed names like comms/native)
                from lang.population import resolve_vertex
                candidate = resolve_vertex(vertex_ref, loops_home()).resolve()

                if not candidate.exists() and "/" in vertex_ref and not _is_path_like(vertex_ref):
                    # Full name didn't resolve — try splitting as vertex/template
                    vertex_ref, template_qualifier = vertex_ref.split("/", 1)
                    candidate = resolve_vertex(vertex_ref, loops_home()).resolve()
                if candidate.exists():
                    vertex_path = candidate
                elif _is_path_like(vertex_ref):
                    # Explicit path that doesn't exist — error
                    show(Block.text(f"Error: {candidate} not found", p.error), file=sys.stderr)
                    return 1
                else:
                    # vertex_ref doesn't resolve — reinterpret as kind, shift args
                    parts = [kind] + parts
                    kind = vertex_ref
                    vertex_ref = None

        if vertex_ref is None:
            # No vertex: try local
            local = _find_local_vertex()
            if local is not None:
                vertex_path = local.resolve()
            else:
                show(
                    Block.text(
                        "No vertex found. Run 'loops init' first.", p.error
                    ),
                    file=sys.stderr,
                )
                return 1

    # Apply --stdin / --file flags (inject expanded payload values into parts).
    # Errors raised as LoopsError → caller-facing message, exit 1.
    try:
        parts = _apply_input_sources(
            parts,
            getattr(args, "stdin", None),
            list(getattr(args, "file", None) or []),
        )
    except LoopsError as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    payload = _parse_emit_parts(parts)

    # Thread auto-tagging: inherit LOOPS_THREAD as default thread association.
    # Priority: explicit thread= in payload > LOOPS_THREAD env > none.
    if "thread" not in payload:
        thread_hint = os.environ.get("LOOPS_THREAD", "")
        if thread_hint:
            payload["thread"] = thread_hint

    # Validate observer + kind against declaration chain
    if vertex_path is not None:
        err = validate_emit(vertex_path, observer, kind)
        if err is not None:
            show(Block.text(f"Error: {err}", p.error), file=sys.stderr)
            return 1

    # Resolve store path early — needed for entity reference resolution
    try:
        writable_path = _resolve_writable_vertex(vertex_path)
        if writable_path is None:
            if not args.dry_run:
                show(
                    Block.text("Error: vertex has no store configured", p.error),
                    file=sys.stderr,
                )
                return 1
            store_path = None
        else:
            # _resolve_writable_vertex only returns a path when the vertex has a
            # store directive (directly or via combine chain), so
            # _resolve_vertex_store_path is always non-None here.
            store_path = _resolve_vertex_store_path(writable_path)
    except LoopsError as e:
        if not args.dry_run:
            show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
            return 1
        store_path = None

    # Resolve entity references in payload values (kind/fold_key_value → ULID)
    # store_path may not exist yet (first emit to this vertex) — cross-vertex
    # resolution can still succeed via topology widening.
    unresolved_refs: list = []
    refs_resolved_count = 0
    if vertex_path is not None and store_path is not None:
        payload_before_refs = payload
        payload, unresolved_refs = _resolve_entity_refs(vertex_path, store_path, payload, kind=kind)
        refs_resolved_count = sum(
            1 for k in payload if k.endswith("_ref") and k not in payload_before_refs
        )

    # Classify emit status for receipt (pure — no side effects)
    if vertex_path is not None:
        emit_status = classify_emit_status(vertex_path, kind, payload)
    else:
        emit_status = None  # no vertex → no classification possible

    # Resolve effective strict mode (vertex.spec.strict > env > flag)
    strict_mode, vertex_declared_strict = _resolve_strict(args, vertex_path)
    quiet = bool(getattr(args, "quiet", False))

    # If strict and any validation failure: refuse, do not store.
    if strict_mode and emit_status is not None:
        refuse_reasons: list[str] = []
        if not emit_status.kind_declared:
            refuse_reasons.append(
                f"kind '{kind}' not declared on this vertex"
            )
        elif emit_status.fold_key_field is not None and not emit_status.fold_key_present:
            refuse_reasons.append(
                f"kind '{kind}' folds by '{emit_status.fold_key_field}' "
                f"but payload has no '{emit_status.fold_key_field}=' field"
            )
        for u in unresolved_refs:
            refuse_reasons.append(f"ref '{u.addr}' did not resolve")

        if refuse_reasons:
            warn_lines, primary_lines = _build_receipt_lines(
                kind=kind,
                fact_id="",
                status=emit_status,
                unresolved=unresolved_refs,
                refs_resolved_count=0,
                refuse=True,
                refuse_reasons=refuse_reasons,
                vertex_strict_source=vertex_declared_strict,
            )
            _emit_lines(primary_lines)
            return 2

    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(
        kind=kind,
        ts=ts,
        payload=payload,
        observer=observer,
        origin="",
    )

    if args.dry_run:
        import json
        show(
            Block.text(
                json.dumps(fact.to_dict(), sort_keys=True, default=str), p.muted
            ),
            file=sys.stdout,
        )
        return 0

    # Pre-generate the fact ID so the receipt reports the same ULID the store assigns.
    fact_id = gen_id()

    try:
        from engine import load_vertex_program

        # Load the vertex runtime — facts route through loops, boundaries fire.
        # Inject the run-clause dispatcher so program.receive/sync fire
        # boundary run clauses automatically when ticks have .run set.
        store_path.parent.mkdir(parents=True, exist_ok=True)
        from loops.commands.signing import fact_signer_for, tick_signer_for
        from loops.commands.sync import _execute_boundary_run
        program = load_vertex_program(
            writable_path, validate_ast=False, run_dispatcher=_execute_boundary_run,
            tick_signer=tick_signer_for(writable_path),
            fact_signer=fact_signer_for(writable_path),
        )

        try:
            # Route fact through the vertex runtime — fold, boundary check, store.
            # program.receive dispatches the run clause if the resulting tick has one.
            # id_override threads the pre-generated fact_id so the receipt
            # reports the same ULID the store assigns.
            tick = program.receive(fact, id_override=fact_id)
            if tick is not None:
                # Boundary fired — a tick was produced
                show(
                    Block.text(
                        f"tick: {tick.name} ({len(tick.payload)} fields)",
                        p.muted,
                    ),
                )

            # Emit receipt: WARN lines (kind/fold-key/refs degradation) plus
            # success line. Stderr for both. -q suppresses the success line
            # but keeps WARN lines visible (load-bearing for in-moment feedback).
            if emit_status is not None:
                warn_lines, primary_lines = _build_receipt_lines(
                    kind=kind,
                    fact_id=fact_id,
                    status=emit_status,
                    unresolved=unresolved_refs,
                    refs_resolved_count=refs_resolved_count,
                    refuse=False,
                    refuse_reasons=[],
                    vertex_strict_source=vertex_declared_strict,
                )
                _emit_lines(warn_lines)
                if not quiet:
                    _emit_lines(primary_lines)
        finally:
            # Clean up the store connection
            if program.has_store:
                program.vertex._store.close()

        return 0
    except Exception as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1


def _run_emit(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
    reporter: "Reporter | None" = None,
) -> int:
    """Thin wrapper: parse argv for emit, delegate to cmd_emit."""
    _ = _reporter(reporter)  # reserved for future error routing
    parser = argparse.ArgumentParser(prog="loops emit", add_help=False)
    if vertex_path is None:
        parser.add_argument(
            "vertex",
            nargs="?",
            default=None,
            help="Vertex name or .vertex path (optional; auto-resolves local vertex)",
        )
    parser.add_argument("kind", help="Fact kind")
    parser.add_argument(
        "parts", nargs="*", help="KEY=VALUE pairs and optional trailing message text"
    )
    parser.add_argument(
        "--observer",
        default=None,
        help="Observer string (default: from .vertex declaration or $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the fact JSON without storing"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Refuse on validation failures (unknown kind, missing fold-key, "
            "unresolved ref). Overridden by vertex 'strict true' declaration "
            "(which always refuses)."
        ),
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress the 'stored:' success receipt line (WARN/ERROR still print).",
    )
    parser.add_argument(
        "--stdin",
        metavar="FIELD",
        default=None,
        help=(
            "Read sys.stdin into the named payload field (e.g. --stdin message). "
            "Sidesteps shell-quoting friction for natural-voice prose. "
            "Errors if stdin is a TTY. Single trailing newline stripped."
        ),
    )
    parser.add_argument(
        "--file",
        action="append",
        metavar="FIELD=PATH",
        default=None,
        help=(
            "Read file contents into the named payload field (e.g. --file message=notes.md). "
            "May repeat for different fields. Tilde expansion supported. "
            "Single trailing newline stripped."
        ),
    )
    args = parser.parse_args(argv)
    if vertex_path is not None:
        args.vertex = None
    # Use dispatch-level observer if emit didn't override
    if args.observer is None:
        args.observer = observer or None
    return cmd_emit(args, vertex_path=vertex_path)


def _run_close(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
    reporter: "Reporter | None" = None,
) -> int:
    """Close a thread — resolve it and capture what it produced.

    Volitional boundary: the observer decides when a thread is done.
    Collects associated artifacts (decisions, tasks, threads) by:
    1. Temporal proximity — facts emitted since the thread opened
    2. Explicit tagging — facts with thread=<name> in payload

    Emits the resolution fact with a ``produced`` field listing what
    the thread generated.
    """
    from datetime import datetime, timezone

    from atoms import Fact
    from engine import vertex_facts, vertex_fold
    from painted import show, Block, Style
    from painted.palette import current_palette
    from loops.commands.identity import resolve_local_vertex, resolve_observer, validate_emit
    from loops.commands.resolve import _resolve_vertex_for_dispatch, _resolve_writable_vertex

    rep = _reporter(reporter)
    p = current_palette()

    parser = argparse.ArgumentParser(prog="loops close")
    if vertex_path is None:
        parser.add_argument("vertex", nargs="?", default=None)
    parser.add_argument("kind", help="Fact kind to close (e.g. thread, task)")
    parser.add_argument("name", help="Name/key of the item to close")
    parser.add_argument("message", nargs="?", default=None, help="Resolution summary")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    # Resolve vertex
    if vertex_path is None:
        vname = getattr(args, "vertex", None)
        if vname is not None:
            resolved = _resolve_vertex_for_dispatch(vname)
            if resolved is not None:
                vertex_path = resolved
            else:
                # Not a vertex — shift: it's the kind, kind is name, name is message
                if args.message is None:
                    args.message = args.name
                args.name = args.kind
                args.kind = vname
                vertex_path = resolve_local_vertex()
        else:
            vertex_path = resolve_local_vertex()

    # Resolve observer
    obs = resolve_observer(observer or None)

    # Find the item in fold state to get its open timestamp
    fold_state = vertex_fold(vertex_path, observer=None, kind=args.kind)
    target_item = None
    for section in fold_state.sections:
        if section.kind == args.kind:
            for item in section.items:
                # Match by key field value (name, topic, etc.)
                key_field = section.key_field
                if key_field and item.payload.get(key_field) == args.name:
                    target_item = item
                    break
                # Fallback: check common key fields
                for kf in ("name", "topic", "title"):
                    if item.payload.get(kf) == args.name:
                        target_item = item
                        break
                if target_item:
                    break

    if target_item is None:
        rep.err(f"No {args.kind} named '{args.name}' found in fold state.")
        return 1

    # Collect produced artifacts via two strategies:
    # 1. Tagged — facts with thread=<name> in payload (precise)
    # 2. Temporal — artifact kinds emitted since thread opened (approximate)
    # Tagged wins when any tagged facts exist; temporal is the fallback.
    tagged = []
    temporal = []
    now = datetime.now(timezone.utc).timestamp()
    if target_item.ts:
        all_facts = vertex_facts(vertex_path, target_item.ts, now)
        for f in all_facts:
            payload = f.get("payload", {})

            # Skip the thread's own facts
            if f["kind"] == args.kind:
                is_self = False
                for kf in ("name", "topic", "title"):
                    if payload.get(kf) == args.name:
                        is_self = True
                        break
                if is_self:
                    continue

            # Check explicit thread tag
            if payload.get("thread") == args.name:
                _add_produced(tagged, f)
                continue

            # Temporal: artifact kinds emitted during thread lifetime
            if f["kind"] in ("decision", "task", "thread", "change"):
                _add_produced(temporal, f)

    # Tagged wins when available; temporal is fallback
    if tagged:
        produced = tagged
        produced_mode = "tagged"
    else:
        produced = temporal
        produced_mode = "temporal"

    # Deduplicate produced artifacts (same kind:key = same artifact)
    seen = set()
    deduped = []
    for pr in produced:
        ref = f"{pr['kind']}:{pr['key']}"
        if ref not in seen:
            seen.add(ref)
            deduped.append(pr)
    produced = deduped

    # Build resolution payload
    key_field = "name"
    for section in fold_state.sections:
        if section.kind == args.kind and section.key_field:
            key_field = section.key_field
            break

    resolution_payload = {
        key_field: args.name,
        "status": "resolved",
    }
    if args.message:
        resolution_payload["message"] = args.message
    if produced:
        resolution_payload["produced"] = [
            f"{p['kind']}:{p['key']}" for p in produced
        ]

    # Show what we found
    show(Block.text(f"Closing {args.kind}: {args.name}", Style(bold=True)))
    if target_item.ts:
        opened = datetime.fromtimestamp(target_item.ts, tz=timezone.utc)
        show(Block.text(f"  opened: {opened.strftime('%Y-%m-%d %H:%M')}", Style(dim=True)))

    if produced:
        show(Block.text(f"  produced ({len(produced)}, {produced_mode}):", Style()))
        for pr in produced:
            show(Block.text(f"    {pr['kind']}: {pr['key']}", Style(dim=True)))
    else:
        show(Block.text("  no associated artifacts found", Style(dim=True)))

    if args.dry_run:
        import json as _json
        show(Block.text(f"\n  dry-run payload: {_json.dumps(resolution_payload)}", Style(dim=True)))
        return 0

    # Emit the resolution fact
    fact = Fact.of(args.kind, obs, **resolution_payload)

    # Validate and emit through runtime
    err = validate_emit(vertex_path, obs, args.kind)
    if err is not None:
        rep.err(f"Error: {err}")
        return 1

    from engine import load_vertex_program
    from loops.commands.signing import fact_signer_for, tick_signer_for
    from loops.commands.sync import _execute_boundary_run

    vp = _resolve_writable_vertex(vertex_path)
    program = load_vertex_program(
        vp, run_dispatcher=_execute_boundary_run, tick_signer=tick_signer_for(vp),
        fact_signer=fact_signer_for(vp),
    )
    program.receive(fact)

    show(Block.text(f"  ✓ {args.kind} '{args.name}' resolved", p.success))
    return 0


def _add_produced(produced: list[dict], fact: dict) -> None:
    """Extract a reference from a fact for the produced list."""
    payload = fact.get("payload", {})
    # Find the best key for this fact
    for kf in ("name", "topic", "title"):
        if payload.get(kf):
            produced.append({"kind": fact["kind"], "key": payload[kf]})
            return
    # Fallback: first non-empty string field
    for k, v in payload.items():
        if isinstance(v, str) and v and not k.startswith("_"):
            produced.append({"kind": fact["kind"], "key": v[:60]})
            return
