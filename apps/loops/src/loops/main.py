"""CLI for the loops runtime.

Verb-first dispatch — three-tier:
  1. Verbs: loops <verb> [vertex] [args]
  2. Commands: loops <command> [args]
  3. Vertex shorthand: loops <vertex> [flags]  (implicit read)

Verbs (vertex operations):
    loops read project                  Read vertex state (fold, default)
    loops read project --facts          Read filtered fact history
    loops read project --facts --kind decision --since 7d
    loops project                       Implicit read (= loops read project)
    loops emit project decision topic=x Inject a fact
    loops sync project                  Run sources (cadence-gated)
    loops sync project --force          Run all sources unconditionally
    loops close thread my-thread        Resolve thread, capture artifacts

Commands:
    loops test <file>                   Test a .loop file (run command, show facts)
    loops test <file> --input <f>       Test parse pipeline against sample input
    loops compile <file>                Show compiled structure
    loops validate <file>               Validate syntax and flow
    loops store [file]                  Inspect store (name, path, or .db)
    loops init [name]                   Initialize vertex
    loops ls                            List vertices
"""

from __future__ import annotations

import argparse  # noqa: F401 — many _run_* functions below reference it lazily
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
# typing deferred — TextIO only used in annotations (strings with __future__)


def _err(msg: str, file: TextIO | None = None) -> None:
    """Show an error message — thin alias to cli.output.err.

    Kept through step 6 of the CLI refactor for back-compat with tests and
    callers that haven't been threaded with a Reporter yet. ``file`` is
    accepted for legacy signature parity but ignored — cli.output.err
    always writes to stderr via PaintedReporter.
    """
    from loops.cli.output import err as _err_impl
    _ = file
    _err_impl(msg)


def _msg(msg: str, file: TextIO | None = None) -> None:
    """Show a success/info message — thin alias to cli.output.msg.

    See _err for the back-compat note. ``file`` is accepted for legacy
    signature parity but ignored.
    """
    from loops.cli.output import msg as _msg_impl
    _ = file
    _msg_impl(msg)


def _parse_vars(raw: list[str]) -> dict[str, str]:
    """Parse ['KEY=VALUE', ...] into {key: value}."""
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var format (expected KEY=VALUE): {item!r}")
        key, _, value = item.partition("=")
        result[key] = value
    return result


from loops.errors import LoopsError  # noqa: E402
from loops.commands.resolve import (  # noqa: E402 — re-export for back-compat
    loops_home,
    _find_local_vertex,
    _warn_missing_fold_key,
    _extract_kind_keys,
    _try_topology_from_store,
    _topology_kind_keys_and_stores,
    _resolve_entity_refs,
    _resolve_writable_vertex,
    _resolve_vertex_store_path,
    _resolve_named_store,
    _resolve_named_vertex,
    _resolve_combine_child,
    _resolve_vertex_for_dispatch,
    _resolve_observer_flag,
    _apply_vertex_scope,
)

# --- Init cluster moved to commands/init.py ---
from loops.commands.init import (  # noqa: E402 — re-export for back-compat
    _ROOT_VERTEX, _MINIMAL_INSTANCE, _extract_block_text, _extract_loops_text,
    _find_source_vertex, _init_local_vertex, _register_with_aggregator,
    _seed_config_facts, _scaffold_artifacts, cmd_init, _run_init,
)


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    _err(f"Error: {root} not found. Run 'loops init' first.")
    return None



# --- Validate/test/compile moved to commands/devtools.py ---
from loops.commands.devtools import (  # noqa: E402 — re-export for back-compat
    _run_validate, _run_test, _run_compile,
)


# --- Sync cluster moved to commands/sync.py ---
from loops.commands.sync import (  # noqa: E402 — re-export for back-compat
    _resolve_combine_vertex_paths, _execute_boundary_run,
    _run_sync_aggregate, _run_sync,
)



# --- Emit cluster moved to commands/emit.py ---
from loops.commands.emit import (  # noqa: E402 — re-export for back-compat
    _parse_emit_parts, cmd_emit, _run_emit, _run_close, _add_produced,
)


def _run_cite(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Emit a cite fact — a reference-only attention signal, no key, no body.

    ``loops cite [vertex] REF1 REF2 ... [--context NAME] [-m MESSAGE] [--dry-run]``

    Capture what informed the current reasoning: every ref named here
    accumulates an inbound count on the target item, boosting its salience
    in lenses. Cite is vocabulary-aligned with how the signal is generated
    — during design sessions, when prior work is referenced, it's
    *cited* (the target is informing the current work), not merely pinged.

    The optional ``--message`` / ``-m`` carries in-the-moment context
    alongside the ref pointer — closing the partial-information gap per
    ``design/cite-as-partial-information-primitive``. Without a message
    the cite is a bare attention signal; with one it carries the thought
    that prompted the cite, surfaced when the target is read.

    Dissolves into ``emit`` with kind=cite — the positional refs translate
    to a single ``ref=R1,R2,...`` payload, ``--message`` becomes a
    ``message=`` payload field, and the collect-fold handles the rest.
    See ``design/cite-as-attention-signal``, ``design/cite-as-partial-information-primitive``,
    and ``design/derived-keys-as-focus-filter`` for rationale.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="loops cite", add_help=False)
    if vertex_path is None:
        parser.add_argument("vertex", nargs="?", default=None)
    parser.add_argument(
        "refs",
        nargs="+",
        help="kind/key refs or bare ULIDs — the attention targets",
    )
    parser.add_argument(
        "--context",
        default=None,
        help="Optional thread or task name to tag the citation",
    )
    parser.add_argument(
        "-m",
        "--message",
        default=None,
        help="Optional in-the-moment context for the citation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fact JSON without storing",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    # Translate to emit-shaped argv: [vertex?] cite ref=R1 ref=R2 ... [--flags]
    emit_argv: list[str] = []
    if vertex_path is None:
        vname = getattr(args, "vertex", None)
        if vname:
            emit_argv.append(vname)
    emit_argv.append("cite")
    for r in args.refs:
        emit_argv.append(f"ref={r}")
    if args.context:
        emit_argv.append(f"context={args.context}")
    if args.message:
        emit_argv.append(f"message={args.message}")
    if args.dry_run:
        emit_argv.append("--dry-run")

    return _run_emit(emit_argv, vertex_path=vertex_path, observer=observer)


def _exit_lens_not_found(
    name: str,
    view_name: str,
    vertex_dir: Path | None,
    *,
    source: str,
) -> None:
    """Print a helpful error and ``sys.exit(2)`` for an unresolvable lens request.

    Lists the file-search tiers tried so the user can drop the lens in the
    right place or fix the typo. The view_name appears in the message because
    a lens module CAN exist but lack the requested view (e.g. fold_view
    present, stream_view missing) — same surface error, distinct cause, and
    the user inspects the named module to tell them apart.
    """
    from .lens_resolver import _build_search_path

    lines = [
        f"Lens '{name}' (requested via {source}) not found, "
        f"or found but missing {view_name}().",
        "Searched:",
    ]
    for d in _build_search_path(vertex_dir):
        lines.append(f"  {d}/{name}.py")
    lines.append(f"  built-in: loops.lenses.{name}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


def _declared_kinds(vertex_path: Path) -> set[str]:
    """Return the set of kinds declared by a vertex (instance or aggregation).

    For an instance vertex, returns the kinds in its ``loops {}`` block.
    For an aggregation vertex that defines its own loops, those kinds.
    For an aggregation vertex with no loops block (pure combine), returns
    the union of source-vertex kinds — same union ``vertex_fold`` uses.

    Returns an empty set on parse/compile failure (validation is best-effort
    — callers should treat empty as "couldn't determine" rather than "vertex
    declares nothing").
    """
    try:
        from lang import parse_vertex_file
        from engine.compiler import compile_vertex
        from engine.vertex_reader import _collect_source_specs

        ast = parse_vertex_file(vertex_path)
        specs = compile_vertex(ast)
        if (ast.combine is not None or ast.discover is not None) and not specs:
            source_specs = _collect_source_specs(
                ast, vertex_path, override_kinds=frozenset(specs),
            )
            return set(source_specs.keys()) | set(specs.keys())
        return set(specs.keys())
    except Exception:
        return set()


def _validate_kind_or_exit(kind: str | None, vertex_path: Path | None) -> None:
    """If ``--kind X`` is set and X is not declared by the vertex, exit 2.

    Silent empty results hide the indistinguishability between:
    - typo in kind name (``--kind decsion``)
    - real kind that this vertex doesn't declare (``--kind decision`` on
      coupling-kernels, which only declares hypothesis/query-run/query-comparison)
    - valid kind with zero facts yet

    Strict validation surfaces the first two as actionable errors; the third
    keeps current "No data yet" behavior because the kind IS declared.

    Same fix shape as ``_exit_lens_not_found`` — third instance of the
    measurement-fidelity discipline. Honest naming: this is consumer-side
    validation of declared kinds, not the broader sensor-registry that
    alcove pointed at (that waits for concrete sensor use cases).

    Skips validation when ``kind`` is None (no filter requested) or the
    vertex's declared-kinds set is empty (couldn't determine — don't block).
    Path-style ``kind/key`` is split: only the kind half is validated.
    """
    if kind is None or vertex_path is None:
        return
    # kind/key drill-down: validate only the kind half.
    kind_only = kind.split("/", 1)[0]
    declared = _declared_kinds(vertex_path)
    if not declared:
        return  # Couldn't determine — don't second-guess the caller.
    if kind_only in declared:
        return

    import difflib
    suggestions = difflib.get_close_matches(
        kind_only, sorted(declared), n=3, cutoff=0.5,
    )
    lines = [
        f"Vertex '{vertex_path.stem}' does not declare kind '{kind_only}'.",
    ]
    if suggestions:
        lines.append(f"Did you mean: {', '.join(suggestions)}?")
    lines.append(f"Declared kinds: {', '.join(sorted(declared)) or '(none)'}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


def _resolve_render_fn(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
):
    """Resolve render function via 3-tier chain.

    Resolution order:
    1. --lens CLI flag (resolved via lens_resolver)
    2. Vertex lens{} declaration (resolved via lens_resolver)
    3. Built-in default

    Explicit lens requests fail loudly. When ``--lens NAME`` or a vertex
    ``lens { fold "NAME" }`` declaration cannot be resolved in any tier
    (vertex-local, cwd, user-global, built-in), this prints a helpful error
    listing the search path and calls ``sys.exit(2)``. Silent fallback to a
    different view would hide measurement misalignment — same failure shape
    as alcove's recency-counter-vs-emitted-kind bug. The user explicitly
    asked for a lens by name; they get either that lens or a clear failure.

    Implicit fallbacks (no ``lens_flag``, no vertex decl) still return the
    built-in default — that path is the normal "no lens requested" case.
    """
    from .lens_resolver import resolve_lens

    # Determine vertex directory for lens search path
    vertex_dir = vertex_path.parent if vertex_path is not None else None

    # Tier 1: --lens flag — explicit request, fail loudly if unresolvable
    if lens_flag is not None:
        fn = resolve_lens(lens_flag, view_name, vertex_dir=vertex_dir)
        if fn is not None:
            return fn
        _exit_lens_not_found(lens_flag, view_name, vertex_dir, source="--lens flag")

    # Tier 2: vertex lens{} declaration — explicit decl, fail loudly if unresolvable
    if vertex_path is not None:
        vertex_lens = _get_vertex_lens_decl(vertex_path)
        if vertex_lens is not None:
            if view_name == "fold_view" and vertex_lens.fold:
                fn = resolve_lens(vertex_lens.fold, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.fold, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )
            elif view_name == "stream_view" and vertex_lens.stream:
                fn = resolve_lens(vertex_lens.stream, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.stream, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )

    # Tier 3: built-in defaults
    if view_name == "fold_view":
        from .lenses.fold import fold_view
        return fold_view
    elif view_name == "stream_view":
        from .lenses.stream import stream_view
        return stream_view
    elif view_name == "ticks_view":
        from .lenses.ticks import ticks_view
        return ticks_view
    elif view_name == "trace_view":
        from .lenses.trace import trace_view
        return trace_view

    from .lenses.fold import fold_view
    return fold_view


def _effective_lens_name(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
) -> str | None:
    """Return the effective lens name for a command — flag or vertex decl.

    Used by fetch resolution so a lens-declared ``fetch`` overrides the
    default command fetch, regardless of whether the lens was requested
    via --lens or via the vertex's lens{} block.
    """
    if lens_flag is not None:
        return lens_flag
    if vertex_path is None:
        return None
    vertex_lens = _get_vertex_lens_decl(vertex_path)
    if vertex_lens is None:
        return None
    if view_name == "fold_view" and vertex_lens.fold:
        return vertex_lens.fold
    if view_name == "stream_view" and vertex_lens.stream:
        return vertex_lens.stream
    return None


def _resolve_lens_fetch(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
):
    """Return a lens-declared fetch callable, or None to fall through to default.

    A lens module may export ``fetch(vertex_path, **kwargs)`` alongside its
    view function. When present, the lens owns its input contract — useful
    for composition lenses (fold + ticks, etc.).
    """
    name = _effective_lens_name(lens_flag, vertex_path, view_name)
    if name is None:
        return None
    from .lens_resolver import resolve_lens_fetch
    vertex_dir = vertex_path.parent if vertex_path is not None else None
    return resolve_lens_fetch(name, vertex_dir=vertex_dir)


def _get_vertex_lens_decl(vertex_path: Path):
    """Extract LensDecl from a vertex file, if present."""
    try:
        from lang import parse_vertex_file
        vf = parse_vertex_file(vertex_path)
        return vf.lens
    except Exception:
        return None




def _vertex_name(vertex_path: Path | None) -> str | None:
    """Extract vertex name from path — stem without extension."""
    if vertex_path is None:
        return None
    name = vertex_path.stem
    # .vertex (bare dotfile) → infer from parent dir
    if name == "":
        return vertex_path.parent.name
    return name




def _run_stream(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Run stream command — unified event history with optional search.

    Dissolves the old log + search into one temporal mode.
    When vertex_path is None (verb-first), the first positional is tried as
    a vertex name before falling back to search query.
    """
    from painted import run_cli
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_query", nargs="?", default=None)
        pre.add_argument("query", nargs="?", default=None)
    else:
        pre.add_argument("query", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path, observer
        query = known.query

        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex

            first = getattr(known, "vertex_or_query", None)
            if first is not None:
                # Try as vertex name first; if it fails, treat as query
                resolved = _resolve_vertex_for_dispatch(first)
                if resolved is not None:
                    vertex_path = resolved
                else:
                    # Not a vertex — it's the query; shift known.query to unused
                    query = first
                    if known.query is not None:
                        query = f"{first} {known.query}"
            if vertex_path is None:
                vertex_path = _resolve_local_vertex()

        # Apply vertex scope — deferred until vertex_path is known
        observer = _apply_vertex_scope(observer, vertex_path)
        obs_for_engine = observer if observer else None

        # Kind validation: --kind X against vertex.declared_kinds.
        # Same fix shape as _exit_lens_not_found — surfaces consumer-side
        # measurement misalignment loudly instead of silent empty results.
        _validate_kind_or_exit(known.kind, vertex_path)

        # --id: single fact lookup by ID or prefix
        if known.fact_id is not None:
            from .commands.fetch import fetch_fact_by_id
            try:
                fact = fetch_fact_by_id(vertex_path, known.fact_id)
            except ValueError as e:
                _err(str(e))
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            if fact is None:
                return {"facts": [], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}
            return {"facts": [fact], "fold_meta": {}, "vertex": "", "_id_lookup": known.fact_id}

        from .commands.fetch import fetch_stream
        return fetch_stream(
            vertex_path,
            query=query,
            kind=known.kind,
            since=known.since,
            observer=obs_for_engine,
        )

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "stream_view",
            )
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
        )

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops stream",
        description="Show event stream",
        help_args=[
            HelpArg("query", "Search text (FTS5)", positional=True),
            HelpArg("--id", "Look up fact by ID or prefix"),
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--since", "Time window (7d, 24h, 1h)", default="7d"),
            HelpArg("--lens", "Render lens (prompt)"),
        ],
    )



# --- Fold helpers moved to cli.views.fold; re-exported for test back-compat ---
from loops.cli.views.fold import (  # noqa: E402
    _extract_refs_depth,
    _looks_like_vertex_path,
)


def _run_fold(argv: list[str], *, vertex_path: Path | None = None, observer: str | None = None) -> int:
    """Run fold command — show collapsed vertex state.

    Thin shim around ``cli.views.fold.run`` post-step-4 of the CLI refactor:
    constructs a CliContext from the legacy kwargs and delegates. Kept so
    callers that still go through the legacy router (``_run_read``) work
    unchanged — the registry routes ``read`` through ``_run_read`` until
    step 5 lands the dedicated read router.
    """
    from loops.cli.context import CliContext
    from loops.cli.output import default_reporter
    from loops.cli.views.fold import run

    ctx = CliContext(
        reporter=default_reporter(),
        vertex_path=vertex_path,
        observer=observer,
    )
    return run(argv, ctx)


# _run_fold_legacy placeholder retired in step 6 — see git history for the
# original orchestrator (last live at commit 68500ba pre-cli-refactor).
    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        # Two positionals: first is vertex-or-entity (disambiguated below),
        # second is entity (only when first was a vertex name).
        pre.add_argument("vertex_or_entity", nargs="?", default=None)
        pre.add_argument("entity", nargs="?", default=None)
    else:
        # Vertex already known (verb-first dispatch resolved it); first
        # positional is the entity.
        pre.add_argument("entity", nargs="?", default=None)
    pre.add_argument("--kind", default=None)
    pre.add_argument("--key", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Resolve entity / vertex from positionals. Disambiguation rules:
    #   - File paths (absolute, relative starting with ./, or ending in
    #     .vertex) are vertices, not entities — passed as the explicit
    #     vertex file.
    #   - Otherwise, "kind/key" entities are recognized by containing "/"
    #     somewhere (the runbook convention: kind/, kind/prefix/, kind/key).
    #   - Bare strings without "/" are treated as named-vertex references.
    entity: str | None = None
    if vertex_path is None:
        first = getattr(known, "vertex_or_entity", None)
        if first is not None and _looks_like_vertex_path(first):
            # File path → vertex. Second positional (if any) is entity.
            known.vertex = first
            entity = known.entity
        elif first is not None and "/" in first:
            # Entity form (kind/key); vertex resolves locally.
            entity = first
            known.vertex = None
        elif first is not None:
            # Named vertex; second positional (if any) is entity.
            known.vertex = first
            entity = known.entity
        else:
            known.vertex = None
            entity = None
    else:
        entity = getattr(known, "entity", None)

    # Route entity into --kind for fetch_fold's existing embedded-key split.
    # Only entities containing "/" are recognized — matches trace's convention
    # that an entity is always "kind/" (kind-wide), "kind/prefix/" (namespace
    # drill), or "kind/full-key" (single entity). Bare strings without "/"
    # are ambiguous (could be a stray arg, a typo, a kind name with no key)
    # and stay in rest unchanged — preserves the pre-B behavior where extra
    # positionals fell through without error. Use --kind/--key flags when
    # you want to filter by kind alone.
    # When --kind is already set explicitly, the entity positional is ignored
    # (flag wins — explicit beats positional). Same for --key.
    if (
        entity is not None and "/" in entity
        and known.kind is None and known.key is None
    ):
        known.kind = entity  # fetch_fold splits "decision/design/foo" via _split_kind_key

    # Pre-check --facts for fetch (it stays in rest for painted's parser too)
    want_facts = "--facts" in rest

    # Pre-extract --refs [N]. Unlike --facts (a presence flag), --refs carries
    # an optional int depth that fetch needs at fetch-time (the walk happens
    # before the lens renders). Manual scan removes the flag from rest so
    # painted's parser doesn't see it — refs_depth is plumbed through the
    # closure to both fetch() (as refs_depth=N) and _build_fold_fidelity()
    # (which adds "refs" to visible when depth > 0 so the lens decorates).
    refs_depth, rest = _extract_refs_depth(rest)

    # Pre-check --diff. When set, read renders cumulative field-deltas
    # across the entity's source-fact lifecycle (rather than the current
    # folded snapshot). C of the trace-dissolution arc — the diff rendering
    # was the one genuinely unique trace capability; absorbed here. Routes
    # the dispatch entirely to a trace-style path: fetch_trace + trace_view.
    want_diff = "--diff" in rest
    if want_diff:
        # Strip --diff from rest so painted's parser doesn't reject it.
        rest = [a for a in rest if a != "--diff"]
        return _run_fold_diff(
            known, rest, refs_depth, vertex_path=vertex_path, observer=observer,
        )

    # Fast path: --static --plain bypasses the CLI framework import (~7ms).
    # Detect these flags before importing painted.cli. The --refs bail-out
    # is here (not in _is_static_plain) because rest has already had --refs
    # stripped by _extract_refs_depth — only refs_depth is meaningful at
    # this point. Fast path's plain renderer doesn't know how to decorate
    # edges, so any walk/decoration request must take the slow path.
    if refs_depth == 0 and _is_static_plain(rest):
        return _run_fold_fast(known, rest, vertex_path=vertex_path, observer=observer)

    from painted import run_cli
    from painted.cli import HelpArg

    # Render function resolved lazily — vertex_path may not be known until fetch()
    resolved_render_fn = None

    def fetch():
        nonlocal vertex_path, observer
        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _resolve_local_vertex
            vname = getattr(known, "vertex", None)
            if vname is not None:
                # Local-first: .loops/name.vertex → cwd → config-level
                local = _resolve_vertex_for_dispatch(vname)
                vertex_path = local if local is not None else _resolve_named_vertex(vname)
            else:
                vertex_path = _resolve_local_vertex()
        # Apply vertex scope — deferred until vertex_path is known
        observer = _apply_vertex_scope(observer, vertex_path)
        obs_for_engine = observer if observer else None
        # Kind validation against vertex.declared_kinds (see _validate_kind_or_exit).
        _validate_kind_or_exit(known.kind, vertex_path)
        # Lens may declare its own fetch (composition lenses — fold + ticks,
        # fold + refs-graph, etc.). When present, the lens owns the input
        # contract; we pass through the standard kwargs and let the lens
        # consume what it needs.
        lens_fetch = _resolve_lens_fetch(known.lens, vertex_path, "fold_view")
        if lens_fetch is not None:
            from .lens_resolver import call_lens_fetch
            return call_lens_fetch(
                lens_fetch, vertex_path,
                kind=known.kind, key=known.key, observer=obs_for_engine,
                retain_facts=want_facts,
                refs_depth=refs_depth,
            )
        from .commands.fetch import fetch_fold
        return fetch_fold(
            vertex_path, kind=known.kind, key=known.key, observer=obs_for_engine,
            retain_facts=want_facts,
            refs_depth=refs_depth,
        )

    def render(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "fold_view",
            )
        # When piped (not TTY), pass width=None so text flows without
        # truncation or padding. The fold output IS the data — useful
        # directly as a system prompt or piped to other tools.
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
            vertex_path=str(vertex_path) if vertex_path else None,
            visible=ctx.fidelity.visible,
            lines=ctx.fidelity.lines,
            chars=ctx.fidelity.chars,
        )

    def _add_fold_args(parser):
        """Add fold-specific flags: visibility layers.

        --refs is consumed by the outer pre-parser (_extract_refs_depth) so it
        does not appear here — the int depth needs to be available at
        fetch-time, before painted parses. The visible-set update happens in
        _build_fold_fidelity via the refs_depth closure variable.
        """
        parser.add_argument("--facts", action="store_true", default=False,
                            help="Show source facts per item")

    def _build_fold_fidelity(parsed, base):
        """Inject visibility tags from fold-specific flags.

        refs_depth comes from the closure (pre-parsed before painted ran).
        When refs_depth > 0, "refs" is added to visible so the fold lens
        decorates each item with its inbound/outbound edges. The walk itself
        (refs_depth > 1) is handled in fetch_fold; this only controls
        rendering.
        """
        visible = set()
        if refs_depth > 0:
            visible.add("refs")
        if getattr(parsed, "facts", False):
            visible.add("facts")
        if not visible:
            return base
        return base.with_visible(*visible)

    async def fetch_stream():
        """Poll the store for updates — enables --live mode."""
        import asyncio
        yield fetch()
        while True:
            await asyncio.sleep(2)
            yield fetch()

    from painted.cli import OutputMode

    # Interactive handler for autoresearch TUI
    handlers: dict | None = None
    if known.lens == "autoresearch":
        def _handle_autoresearch_interactive(ctx):
            nonlocal vertex_path, observer
            if vertex_path is None:
                from .commands.identity import resolve_local_vertex as _rlv
                vname = getattr(known, "vertex", None)
                if vname is not None:
                    local = _resolve_vertex_for_dispatch(vname)
                    vertex_path = local if local is not None else _resolve_named_vertex(vname)
                else:
                    vertex_path = _rlv()
            observer = _apply_vertex_scope(observer, vertex_path)
            import asyncio as _asyncio
            from .tui.autoresearch_app import AutoresearchApp
            app = AutoresearchApp(vertex_path, observer=observer)
            _asyncio.run(app.run())
            return 0
        handlers = {OutputMode.INTERACTIVE: _handle_autoresearch_interactive}

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        fetch_stream=fetch_stream,
        default_mode=OutputMode.STATIC,
        handlers=handlers,
        add_args=_add_fold_args,
        build_fidelity=_build_fold_fidelity,
        prog="loops fold",
        description="Show folded state",
        help_args=[
            HelpArg("--kind", "Filter by fact kind"),
            HelpArg("--key", "Filter by fold-key prefix (kind-aware)"),
            HelpArg("--observer", "Filter by observer (default: you)"),
            HelpArg("--lens", "Render lens (prompt)"),
            HelpArg("--refs", "Walk + decorate ref graph; bare = depth 1, --refs N = depth N"),
            # --facts is added via _add_fold_args so painted auto-renders it
            # from the argparse parser; listing it here too produces a dup line.
        ],
    )


def _is_static_plain(rest: list[str]) -> bool:
    """Check if rest args contain --static --plain without help flags.

    Note: the --refs bail-out for the fast path is enforced at the call site
    in _run_fold (using refs_depth from _extract_refs_depth). Putting it here
    wouldn't work — the caller strips --refs from rest before this check, so
    has_refs would always be False at this point. The bug class
    exercising-catches-coherence-gaps caught this on first run.
    """
    has_static = "--static" in rest
    has_plain = "--plain" in rest
    has_help = "-h" in rest or "--help" in rest
    has_json = "--json" in rest
    has_live = "--live" in rest
    has_interactive = "-i" in rest
    return has_static and has_plain and not has_help and not has_json and not has_live and not has_interactive


# --- _render_fold_plain / _run_fold_diff / _run_fold_fast retired in step 6 ---
# See git history at commit 68500ba (pre-cli-refactor) for the legacy bodies.


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    def _resolve_store_target() -> Path:
        """Resolve file arg: vertex name, path, or LOOPS_HOME/.vertex fallback."""
        if vertex_path is not None:
            return vertex_path
        if file_arg is not None:
            p = Path(file_arg)
            # If it looks like a path (has extension or path separators), use directly
            if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
                return p
            # Otherwise treat as vertex name
            from lang.population import resolve_vertex

            return resolve_vertex(file_arg, loops_home())
        home = loops_home()
        root = home / ".vertex"
        if root.exists():
            return root
        raise FileNotFoundError(f"{root} not found. Run 'loops init' first.")

    def fetch():
        from .commands.store import make_fetcher

        path = _resolve_store_target().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        return make_fetcher(path, zoom=3)()

    def render(ctx, data):
        from .lenses.store import store_view

        return store_view(data, ctx.zoom, ctx.width)

    async def fetch_stream():
        import asyncio

        while True:
            try:
                yield fetch()
            except FileNotFoundError:
                pass
            await asyncio.sleep(2.0)

    def handle_interactive(ctx):
        import asyncio as _asyncio
        from .tui import StoreExplorerApp

        path = _resolve_store_target().resolve()
        app = StoreExplorerApp(path)
        _asyncio.run(app.run())
        return 0

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        render=render,
        handlers={OutputMode.INTERACTIVE: handle_interactive},
        default_mode=OutputMode.STATIC,
        prog="loops store",
        description="Inspect store contents",
        help_args=[
            HelpArg("file", "Store file, vertex name, or path", positional=True),
        ],
    )


def _run_ls(argv: list[str]) -> int:
    """Run ls command via painted CLI harness."""
    from painted import run_cli
    from painted.cli import HelpArg
    from .commands.pop import fetch_ls
    from .lenses.pop import pop_view

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("target")
    known, rest = pre.parse_known_args(argv)

    def fetch():
        return fetch_ls(known.target)

    def render(ctx, data):
        return pop_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops ls",
        description="List template populations",
        help_args=[
            HelpArg("target", "Population target name", positional=True),
        ],
    )


def _run_ls_root(argv: list[str]) -> int:
    """Run root-level ls: list all discovered vertices."""
    from painted import run_cli
    from .commands.vertices import fetch_vertices
    from .lenses.vertices import vertices_view

    home = loops_home()

    def fetch():
        return fetch_vertices(home)

    def render(ctx, data):
        return vertices_view(data, ctx.zoom, ctx.width)

    return run_cli(
        argv,
        fetch=fetch,
        render=render,
        prog="loops ls",
        description="List vertices",
    )










def _run_add(argv: list[str]) -> int:
    """Thin wrapper: parse argv for add, delegate to cmd_add."""
    from .commands.pop import cmd_add

    parser = argparse.ArgumentParser(prog="loops add", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument("values", nargs="+", help="Column values in header order")
    args = parser.parse_args(argv)
    return cmd_add(args)


def _run_rm(argv: list[str]) -> int:
    """Thin wrapper: parse argv for rm, delegate to cmd_rm."""
    from .commands.pop import cmd_rm

    parser = argparse.ArgumentParser(prog="loops rm", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument("key", help="Key (first column) to remove")
    args = parser.parse_args(argv)
    return cmd_rm(args)


def _run_export(argv: list[str]) -> int:
    """Thin wrapper: parse argv for export, delegate to cmd_export."""
    from .commands.pop import cmd_export

    parser = argparse.ArgumentParser(prog="loops export", add_help=False)
    parser.add_argument("target", help="Vertex name or vertex/template")
    parser.add_argument(
        "--output",
        "-o",
        help="(deprecated) ignored; export materializes configured .list",
    )
    args = parser.parse_args(argv)
    return cmd_export(args)


def _run_whoami(argv: list[str]) -> int:
    """Show resolved observer identity.

    Resolution chain:
    1. LOOPS_OBSERVER env var / .vertex single-observer (via resolve_observer)
    2. Identity store self/name fact (for multi-observer .vertex files)
    """
    from painted import show, Block, Style
    from .commands.identity import resolve_observer, resolve_local_vertex

    observer = resolve_observer()
    if not observer:
        # Fall back to identity store — handles multi-observer .vertex
        observer = _whoami_from_identity_store()
    if not observer:
        show(Block.text("No observer identity resolved.", Style(dim=True)))
        return 1
    show(Block.text(observer, Style()))
    return 0


def _whoami_from_identity_store() -> str:
    """Try to read observer name from the local identity vertex store.

    Uses dispatch resolution (local .loops/ first) so it finds the
    workspace identity, not the config-level template.
    """
    try:
        from .commands.fetch import fetch_fold
        identity_path = _resolve_vertex_for_dispatch("identity")
        if identity_path is None:
            return ""
        fold_state = fetch_fold(identity_path, kind="self")
        for section in fold_state.sections:
            if section.kind == "self":
                for item in section.items:
                    if item.payload.get("name") == "name":
                        msg = item.payload.get("message", "")
                        # "meta-claude. Some description..." → "meta-claude"
                        return msg.split(".")[0].strip() if msg else ""
        return ""
    except Exception:
        return ""


# Verb-first dispatch: `loops <verb> [vertex] [args]`.
# These are the primary CLI verbs — read (implicit default), emit, sync, close, cite.
# `trace` retired 2026-05-17 (D of trace-dissolution); use `read --diff`
# for entity lifecycle, optionally with --refs N for ref-graph walks.
_VERBS = frozenset({"read", "emit", "close", "sync", "cite"})

# Dev and setup commands dispatched directly.
_DEV_COMMANDS = frozenset({"test", "compile", "validate", "store"})
_SETUP_COMMANDS = frozenset({"init", "whoami", "ls", "add", "rm", "export"})

# Combined for dispatch check (verbs checked first, then these).
_COMMANDS = _DEV_COMMANDS | _SETUP_COMMANDS

# Vertex-first operations: `loops <vertex> <op>`.
_VERTEX_OPS = frozenset({
    "read", "emit", "close", "sync", "store", "cite",
    "ls", "add", "rm", "export",
})


def _tick_drill_header(tick_meta: dict, width: int | None) -> "Block":
    """Render a compact header for tick drill-down.

    Shows tick index, boundary trigger, and time window. Returns a
    Block that can be composed above the fold/lens output.
    """
    from painted import Block, Style, join_vertical

    if not tick_meta:
        return Block.text("", Style())

    boundary = tick_meta.get("boundary", {})
    bname = boundary.get("name", "")
    bstatus = boundary.get("status", "")
    trigger = f" — {bname} {bstatus}" if bname else ""

    range_end = tick_meta.get("range_end")
    if range_end is not None:
        # Range mode: "Ticks #0:3 of 120"
        range_boundaries = tick_meta.get("range_boundaries", [])
        observers = list(dict.fromkeys(
            b.get("name", "") for b in range_boundaries if b.get("name")
        ))
        if observers:
            trigger = f" — {', '.join(observers)}"
        title = f"Ticks #{tick_meta['index']}:{range_end} of {tick_meta['total']}{trigger}"
    else:
        title = f"Tick #{tick_meta['index']} of {tick_meta['total']}{trigger}"

    rows: list[tuple[str, Style]] = [(title, Style(bold=True))]

    if tick_meta.get("since") and tick_meta.get("ts"):
        rows.append((f"  window: {tick_meta['since']} → {tick_meta['ts']}", Style(dim=True)))

    rows.append(("", Style()))
    return Block.column(rows, width=width)


def _run_ticks(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Tick history and drill-down.

    ``loops read project --ticks``       — list recent ticks
    ``loops read project --ticks 0``     — drill into most recent tick
    ``loops read project --ticks 0:3``   — drill into last 3 ticks (range)
    ``loops read project --ticks 3``     — drill into 4th most recent tick
    """
    from painted import run_cli
    from painted.cli import HelpArg

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex_or_index", nargs="?", default=None)
        pre.add_argument("index", nargs="?", default=None)
    else:
        pre.add_argument("index", nargs="?", default=None)
    pre.add_argument("--since", default=None)
    pre.add_argument("--lens", default=None)
    known, rest = pre.parse_known_args(argv)

    # Parse index: int for single, "start:end" for range
    tick_index: int | None = None
    tick_range: tuple[int, int] | None = None

    def _try_index(s: str | None) -> bool:
        """Try parsing s as single index or range. Returns True if parsed."""
        nonlocal tick_index, tick_range
        if s is None:
            return False
        if ":" in s:
            parts = s.split(":", 1)
            try:
                tick_range = (int(parts[0]), int(parts[1]))
                return True
            except ValueError:
                return False
        try:
            tick_index = int(s)
            return True
        except ValueError:
            return False

    if vertex_path is None:
        first = getattr(known, "vertex_or_index", None)
        if first is not None:
            if not _try_index(first):
                # Not an index — try as vertex name
                resolved = _resolve_vertex_for_dispatch(first)
                if resolved is not None:
                    vertex_path = resolved
                    _try_index(known.index)
        if tick_index is None and tick_range is None:
            _try_index(known.index)
        if vertex_path is None:
            from .commands.identity import resolve_local_vertex as _rlv
            vertex_path = _rlv()
    else:
        _try_index(known.index)

    # Drill-down: show fold state snapshot from tick payload
    if tick_index is not None or tick_range is not None:
        resolved_render_fn = None

        def fetch():
            if tick_range is not None:
                from .commands.fetch import fetch_tick_range_fold
                return fetch_tick_range_fold(
                    vertex_path, tick_range[0], tick_range[1], since=known.since,
                )
            else:
                from .commands.fetch import fetch_tick_fold
                return fetch_tick_fold(vertex_path, tick_index, since=known.since)

        def render(ctx, data):
            nonlocal resolved_render_fn
            from painted import Block, Style, join_vertical

            w = ctx.width if ctx.is_tty else None

            # Error case
            if data.get("_tick_error"):
                return Block.text(data["_tick_error"], Style(dim=True))

            fold_state = data["fold_state"]
            tick_meta = data.get("_tick", {})

            # Resolve fold lens (not stream — tick payload is fold state)
            if resolved_render_fn is None:
                resolved_render_fn = _resolve_render_fn(
                    known.lens, vertex_path, "fold_view",
                )

            from .lens_resolver import call_lens
            body = call_lens(
                resolved_render_fn, fold_state, ctx.zoom, w,
                vertex_name=_vertex_name(vertex_path),
            )

            # Compose tick header + fold rendering
            header = _tick_drill_header(tick_meta, w)
            return join_vertical(header, body) if header else body

        return run_cli(
            rest,
            fetch=fetch,
            render=render,
            prog="loops ticks",
            description="Show fold state at tick boundary",
            help_args=[
                HelpArg("index", "Tick index or range (0, 0:3)", positional=True),
                HelpArg("--since", "Time window for tick search (30d)", default="30d"),
                HelpArg("--lens", "Render lens"),
            ],
        )

    # Listing mode: show tick history
    from .commands.fetch import fetch_ticks

    resolved_render_fn = None

    def fetch_listing():
        return fetch_ticks(vertex_path, since=known.since)

    def render_listing(ctx, data):
        nonlocal resolved_render_fn
        if resolved_render_fn is None:
            resolved_render_fn = _resolve_render_fn(
                known.lens, vertex_path, "ticks_view",
            )
        w = ctx.width if ctx.is_tty else None
        from .lens_resolver import call_lens
        return call_lens(
            resolved_render_fn, data, ctx.zoom, w,
            vertex_name=_vertex_name(vertex_path),
        )

    return run_cli(
        rest,
        fetch=fetch_listing,
        render=render_listing,
        prog="loops ticks",
        description="Show tick history",
        help_args=[
            HelpArg("index", "Tick index to drill into (0 = most recent)", positional=True),
            HelpArg("--since", "Time window (30d, 7d, 1h)", default="30d"),
            HelpArg("--lens", "Render lens"),
        ],
    )


def _run_read(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    observer: str | None = None,
) -> int:
    """Unified read verb — routes to fold (default, with visibility layers) or stream/ticks.

    ``loops read [vertex] [flags]`` is the primary read interface.
    Default (no flags) shows fold state. ``--facts`` and ``--refs`` are
    visibility layers on the fold view. ``--ticks`` routes to tick history.
    ``--facts`` with ``--since`` or ``--id`` routes to stream (temporal query).

    This is a thin router — delegates to ``_run_fold``, ``_run_stream``,
    or ``_run_ticks``.
    """
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--facts", action="store_true", default=False)
    pre.add_argument("--ticks", action="store_true", default=False)
    pre.add_argument("--since", default=None)
    pre.add_argument("--id", default=None, dest="fact_id")
    known, rest = pre.parse_known_args(argv)

    if known.facts and (known.since or known.fact_id):
        # Temporal query — delegate to stream (without --facts flag)
        stream_rest = rest
        if known.since:
            stream_rest = [*stream_rest, "--since", known.since]
        if known.fact_id:
            stream_rest = [*stream_rest, "--id", known.fact_id]
        return _run_stream(stream_rest, vertex_path=vertex_path, observer=observer)
    elif known.ticks:
        # Tick history mode — dedicated tick fetch and lens
        return _run_ticks(rest, vertex_path=vertex_path, observer=observer)
    else:
        # Default: fold state (re-inject --facts if present — it's a visibility layer)
        fold_rest = [*rest, "--facts"] if known.facts else rest
        return _run_fold(fold_rest, vertex_path=vertex_path, observer=observer)


def _render_main_help(argv: list[str]) -> int:
    """Render two-group help: vertex operations + root commands."""
    import shutil
    from painted.cli import (
        Format,
        HelpData,
        HelpFlag,
        HelpGroup,
        Zoom,
        render_help,
        scan_help_args,
    )
    from painted.core.writer import print_block

    zoom, fmt = scan_help_args(argv)

    verbs_group = HelpGroup(
        name="Verbs",
        hint="loops <verb> [vertex] [args]",
        detail="Implicit read: loops project = loops read project",
        flags=(
            HelpFlag(None, "read", "Read vertex state", detail="[vertex] [kind/key] [--diff] [--refs [N]] [--facts] [--ticks] [--kind K] [--key PREFIX]"),
            HelpFlag(None, "emit", "Inject a fact", detail="[vertex] <kind> [KEY=VALUE ...] [--dry-run]"),
            HelpFlag(None, "sync", "Run sources (cadence-gated)", detail="[vertex] [--force] [--var KEY=VALUE]"),
            HelpFlag(None, "close", "Resolve and capture artifacts", detail="[vertex] <kind> <name> [message] [--dry-run]"),
            HelpFlag(None, "cite", "Attention signal — inform current work with prior refs", detail="[vertex] <ref1> <ref2> ... [--context NAME] [-m MSG]"),
        ),
    )

    commands_group = HelpGroup(
        name="Commands",
        flags=(
            HelpFlag(None, "test", "Test a .loop file", detail="<file> [--input FILE] [--limit N]"),
            HelpFlag(None, "compile", "Show compiled structure", detail="<file>"),
            HelpFlag(None, "validate", "Validate syntax and flow", detail="[files...]"),
            HelpFlag(None, "store", "Inspect store contents", detail="[file]"),
            HelpFlag(None, "init", "Initialize vertex", detail="[name] [--template NAME]"),
            HelpFlag(None, "ls", "List vertices"),
            HelpFlag(None, "whoami", "Show resolved observer identity"),
        ),
    )

    zoom_group = HelpGroup(
        name="Zoom",
        hint="(what to show)",
        detail="Controls how much detail is rendered.",
        flags=(
            HelpFlag("-q", "--quiet", "Minimal output"),
            HelpFlag("-v", "--verbose", "Detailed (-v) or full (-vv)"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    format_group = HelpGroup(
        name="Format",
        hint="(serialization)",
        flags=(
            HelpFlag(None, "--json", "JSON output"),
            HelpFlag(None, "--plain", "Plain text, no ANSI codes"),
        ),
        min_zoom=Zoom.SUMMARY,
    )

    help_group = HelpGroup(
        name="Help",
        flags=(HelpFlag("-h", "--help", "Show this help", detail="Add -v for more detail."),),
        min_zoom=Zoom.SUMMARY,
    )

    help_data = HelpData(
        prog="loops",
        description="Runtime for .loop and .vertex files",
        groups=(verbs_group, commands_group, zoom_group, format_group, help_group),
    )

    if fmt == Format.JSON:
        import json
        from dataclasses import asdict
        print(json.dumps(asdict(help_data), default=str))
        return 0

    use_ansi = fmt != Format.PLAIN
    if fmt == Format.AUTO:
        use_ansi = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    width = shutil.get_terminal_size().columns
    block = render_help(help_data, zoom, width, use_ansi)
    print_block(block, use_ansi=use_ansi)
    return 0



# _resolve_observer_flag, _apply_vertex_scope — moved to commands/resolve.py, re-exported above


def _dispatch_verb_first(verb: str, rest: list[str]) -> int:
    """Dispatch verb-first operations: ``loops <verb> [vertex] [args]``.

    Resolves ``--observer`` the same way as ``_dispatch_observer``, then
    delegates to the appropriate ``_run_*`` function with ``vertex_path=None``
    so they resolve the vertex from context (optional positional or local).
    """
    import argparse

    # Pre-parse --observer from rest (same pattern as _dispatch_observer)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    if verb == "read":
        return _run_read(rest, vertex_path=None, observer=observer)
    if verb == "emit":
        return _run_emit(rest, vertex_path=None, observer=observer)
    if verb == "close":
        return _run_close(rest, vertex_path=None, observer=observer)
    if verb == "sync":
        return _run_sync(rest, vertex_path=None)
    if verb == "cite":
        return _run_cite(rest, vertex_path=None, observer=observer)

    _err(f"Unknown verb: {verb}")
    return 1


def _dispatch_observer(
    vertex_name: str, vertex_path: Path, rest: list[str]
) -> int:
    """Dispatch observer operations with resolved vertex.

    Resolves ``--observer`` once at dispatch level and threads it to all
    subcommands. Default is the current observer identity (from env /
    .vertex chain) — you're always yourself unless you explicitly look
    through someone else's eyes.

    Default (no subcommand or flags only) → read (fold by default).
    """
    import argparse

    # Pre-parse --observer from rest (before subcommand dispatch)
    obs_parser = argparse.ArgumentParser(add_help=False)
    obs_parser.add_argument("--observer", default=None)
    obs_known, rest = obs_parser.parse_known_args(rest)
    observer = _resolve_observer_flag(obs_known.observer)

    # Default: no subcommand or flags only → read (fold by default)
    if not rest or rest[0].startswith("-"):
        return _run_read(rest, vertex_path=vertex_path, observer=observer)

    op = rest[0]
    args = rest[1:]

    # Primary verbs
    if op == "read":
        return _run_read(args, vertex_path=vertex_path, observer=observer)
    if op == "emit":
        return _run_emit(args, vertex_path=vertex_path, observer=observer)
    if op == "close":
        return _run_close(args, vertex_path=vertex_path, observer=observer)
    if op == "sync":
        return _run_sync(args, vertex_path=vertex_path)
    if op == "cite":
        return _run_cite(args, vertex_path=vertex_path, observer=observer)

    # Dev tools
    if op == "store":
        return _run_store(args, vertex_path=vertex_path)

    # Population operations — reconstruct target argv
    if op == "ls":
        qualifier = None
        flags = []
        for arg in args:
            if qualifier is None and not arg.startswith("-"):
                qualifier = arg
            else:
                flags.append(arg)
        target = f"{vertex_name}/{qualifier}" if qualifier else vertex_name
        return _run_ls([target] + flags)
    if op in ("add", "rm", "export"):
        handler = {"add": _run_add, "rm": _run_rm, "export": _run_export}[op]
        return handler([vertex_name] + args)

    _err(f"Unknown operation: {op}")
    return 1


def _dispatch_command(cmd: str, argv: list[str]) -> int:
    """Dispatch dev tools and setup commands."""
    from painted.cli.app_runner import run_app, AppCommand
    from painted.cli import HelpArg

    commands = [
        # Dev tools
        AppCommand(
            "test",
            "Test a .loop file — preview facts, no persistence",
            _run_test,
            detail="<file> [--input FILE] [--limit N]",
        ),
        AppCommand("compile", "Show compiled structure", _run_compile, detail="<file>"),
        AppCommand(
            "validate",
            "Validate syntax and flow",
            _run_validate,
            detail="[files...] — defaults to *.loop/*.vertex in cwd",
        ),
        AppCommand(
            "store",
            "Inspect store contents",
            _run_store,
            detail="[file] — vertex name, path, or .db file",
        ),
        # Setup / utility
        AppCommand(
            "init",
            "Initialize vertex",
            _run_init,
            detail="[name] [--template NAME]",
            help_args=[
                HelpArg("name", "Vertex name (e.g., 'project' or 'dev/project')", positional=True),
                HelpArg("--template", "Source vertex name to use as template"),
            ],
        ),
        AppCommand("whoami", "Show resolved observer identity", _run_whoami),
        AppCommand("ls", "List vertices", _run_ls_root),
        AppCommand("add", "Add to template population", _run_add, detail="<target> <values...>"),
        AppCommand("rm", "Remove from template population", _run_rm, detail="<target> <key>"),
        AppCommand("export", "Materialize .list from store", _run_export, detail="<target>"),
    ]
    return run_app(
        [cmd] + argv, commands, prog="loops", description="Runtime for .loop and .vertex files"
    )


# _try_fast_read retired in step 6 — the fast path it served (--static
# --plain via _run_fold_fast) is gone as of step 4. See git history at
# commit 68500ba for the original implementation.


def main(argv: list[str] | None = None) -> int:
    """Main entry point — delegates to ``cli.app.main``.

    Behaviour is owned by the new dispatcher; this function only exists
    as the legacy entry point that the console-script and ``python -m
    loops`` resolve to.
    """
    from loops.cli.app import main as _cli_main

    return _cli_main(argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
