"""Emit and close action commands — parse args, mutate stores, exit."""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from loops.errors import LoopsError


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


def cmd_emit(args: argparse.Namespace, *, vertex_path: Path | None = None) -> int:
    """Inject a fact directly into a vertex store (or print in --dry-run)."""
    from atoms import Fact
    from loops.commands.identity import resolve_observer, validate_emit
    from loops.commands.resolve import (
        loops_home, _find_local_vertex, _resolve_vertex_for_dispatch,
        _resolve_writable_vertex, _resolve_vertex_store_path,
        _resolve_entity_refs, _warn_missing_fold_key,
    )
    from loops.pop_store import POP_ADD_KIND, POP_RM_KIND
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

        # Warn if payload is missing the fold key field (data quality)
        _warn_missing_fold_key(vertex_path, kind, payload)

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
    if vertex_path is not None and store_path is not None:
        payload = _resolve_entity_refs(vertex_path, store_path, payload)

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

    try:
        from engine import load_vertex_program

        # Special-case: pop facts also materialize the configured .list file.
        is_pop = kind in (POP_ADD_KIND, POP_RM_KIND)
        list_path = None
        header = None
        template_name = None
        include_unscoped = True
        template = None

        if is_pop:
            from lang import parse_vertex_file
            from lang.population import resolve_template, list_file_header, list_file_read
            from loops.pop_store import pop_materialize_list, pop_store_has_facts
            ast = parse_vertex_file(vertex_path)

            # Resolve template target:
            # - prefer explicit vertex/template qualifier
            # - else payload["template"] if provided
            # - else allow implicit if only one template exists
            payload_template = payload.get("template")
            qualifier = template_qualifier or payload_template

            templates = [
                s
                for s in (ast.sources or ())
                if getattr(s, "template", None) is not None
            ]
            is_multi = len(templates) > 1
            include_unscoped = not is_multi

            if is_multi and not qualifier:
                show(
                    Block.text(
                        "Error: multiple templates in vertex; specify one as "
                        "'vertex/template' or include template=... in payload",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            template = resolve_template(ast, qualifier)
            template_name = template.template.stem if is_multi else None

            if template.from_ is None or not hasattr(template.from_, "path"):
                show(
                    Block.text(
                        "Error: template has no 'from file' population configured",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            list_path = template.from_.path
            if not Path(list_path).is_absolute():
                list_path = (vertex_path.parent / list_path).resolve()
            else:
                list_path = Path(list_path)

            header = list_file_header(list_path)
            if not header:
                show(
                    Block.text(
                        f"Error: no .list header found at {list_path}",
                        p.error,
                    ),
                    file=sys.stderr,
                )
                return 1

            if kind == POP_ADD_KIND:
                if "key" not in payload:
                    show(
                        Block.text("Error: pop.add requires key=...", p.error),
                        file=sys.stderr,
                    )
                    return 1
                missing = [h for h in header[1:] if h not in payload]
                if missing:
                    show(
                        Block.text(
                            "Error: pop.add requires all non-key columns: "
                            + ", ".join(missing),
                            p.error,
                        ),
                        file=sys.stderr,
                    )
                    return 1
            if kind == POP_RM_KIND and "key" not in payload:
                show(
                    Block.text("Error: pop.rm requires key=...", p.error),
                    file=sys.stderr,
                )
                return 1

            if template_name is not None:
                if "template" in payload and payload.get("template") != template_name:
                    show(
                        Block.text(
                            f"Error: payload template={payload.get('template')!r} does not match "
                            f"resolved template {template_name!r}",
                            p.error,
                        ),
                        file=sys.stderr,
                    )
                    return 1
                payload["template"] = template_name

        # Load the vertex runtime — facts route through loops, boundaries fire
        store_path.parent.mkdir(parents=True, exist_ok=True)
        program = load_vertex_program(writable_path, validate_ast=False)

        try:
            if is_pop and list_path is not None and header is not None:
                # If this is the first pop mutation for this template, seed the store
                # from the existing .list to avoid clobbering on first materialization.
                if not pop_store_has_facts(
                    store_path,
                    template=template_name,
                    include_unscoped=include_unscoped,
                ):
                    if list_path.exists():
                        hdr, rows = list_file_read(list_path)
                        if hdr:
                            for row in rows:
                                seed_payload: dict[str, str] = {"key": row.key}
                                if template_name is not None:
                                    seed_payload["template"] = template_name
                                for field in hdr[1:]:
                                    seed_payload[field] = row.values.get(field, "")
                                seed_fact = Fact(
                                    kind=POP_ADD_KIND,
                                    ts=datetime.now(timezone.utc).timestamp(),
                                    payload=seed_payload,
                                    observer=args.observer or "",
                                    origin="",
                                )
                                program.vertex.receive(seed_fact)

            # Route fact through the vertex runtime — fold, boundary check, store
            tick = program.vertex.receive(fact)
            if tick is not None:
                # Boundary fired — a tick was produced
                show(
                    Block.text(
                        f"tick: {tick.name} ({len(tick.payload)} fields)",
                        p.muted,
                    ),
                )
                # Execute boundary run clause if present — fire and forget
                if tick.run:
                    from loops.commands.sync import _execute_boundary_run
                    _execute_boundary_run(tick.run, tick.name, writable_path)
        finally:
            # Clean up the store connection
            if hasattr(program.vertex, '_store') and program.vertex._store is not None:
                program.vertex._store.close()

        if is_pop and list_path is not None and header is not None:
            pop_materialize_list(
                store_path=store_path,
                list_path=list_path,
                header=header,
                template=template_name,
                include_unscoped=include_unscoped,
            )
        return 0
    except Exception as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1


def _run_emit(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Thin wrapper: parse argv for emit, delegate to cmd_emit."""
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
    args = parser.parse_args(argv)
    if vertex_path is not None:
        args.vertex = None
    # Use dispatch-level observer if emit didn't override
    if args.observer is None:
        args.observer = observer or None
    return cmd_emit(args, vertex_path=vertex_path)


def _run_close(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
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
    from loops.main import _err

    p = current_palette()

    parser = argparse.ArgumentParser(prog="loops close", add_help=False)
    if vertex_path is None:
        parser.add_argument("vertex", nargs="?", default=None)
    parser.add_argument("kind", help="Fact kind to close (e.g. thread, task)")
    parser.add_argument("name", help="Name/key of the item to close")
    parser.add_argument("message", nargs="?", default=None, help="Resolution summary")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args(argv)

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
        _err(f"No {args.kind} named '{args.name}' found in fold state.")
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
        _err(f"Error: {err}")
        return 1

    from engine import load_vertex_program

    vp = _resolve_writable_vertex(vertex_path)
    program = load_vertex_program(vp)
    program.vertex.receive(fact)

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
