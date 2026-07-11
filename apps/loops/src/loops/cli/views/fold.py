"""cli.views.fold — the read/fold view (the big one).

Collapses the legacy fold entry points into a single
``argparse → Operation → dispatch`` shape, and (S4) binds the read grammar
to the typed Surface transforms:

  - positionals + intermixed ``field=value`` predicates collect into ONE
    ``tokens`` bucket (``parse_intermixed_args``); ``_classify_tokens`` sorts
    them into vertex / entity / where-predicate / observer-filter.
  - the transform flags (``--full`` / ``--limit`` / ``--last`` / ``--fields`` /
    ``--count`` / ``--by``) + comma-OR ``--key`` + the ``field=value`` predicate
    assemble a ``SurfaceSpec`` carried on the Operation; dispatch applies it over
    the projected Surface so plain and ``--json`` encode the SAME rows.

The framework flags (``-q``/``-v``, ``--json``/``--plain``,
``--static``/``--live``/``-i``) are registered EXPLICITLY here — painted's
bundled arg-registration was dissolved so the read grammar is self-documenting
at the parser and the out-of-scope density budgets
(``--max-chars``/``--max-lines``) drop out. The ``parse_*`` compilers stay (they
read ``getattr`` dests). Painted
is never imported at view scope beyond those pure arg compilers; the renderer
boundary lives in ``cli.output`` (Reporter), live mode in ``dispatch``.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape;
decision/cli-refactor-fast-path-retired;
decision/design/surface-base-order-is-fold-order.
"""
from __future__ import annotations

import argparse
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from painted.cli import Format
from painted.cli.types import parse_fidelity, parse_format, parse_zoom

from ..dispatch import dispatch
from ..invocation import Invocation
from ..operation import Operation, SurfaceSpec


# --- Helpers (absorbed from main.py) --------------------------------------


def _looks_like_vertex_path(s: str) -> bool:
    """True when ``s`` looks like a filesystem path to a vertex file.

    Conservative — recognises the forms tests and callers actually use:
    absolute path, ``./`` / ``../`` relative, or a ``.vertex`` suffix.
    """
    if s.startswith("/") or s.startswith("./") or s.startswith("../"):
        return True
    if s.endswith(".vertex"):
        return True
    return False


def _extract_refs_depth(rest: list[str]) -> tuple[int, list[str]]:
    """Extract ``--refs [N]`` from rest; return ``(depth, cleaned_rest)``.

    Manual scan rather than ``nargs='?'`` because the latter is brittle
    when the optional integer is followed by another flag.

      ``--refs``        → depth 1
      ``--refs 2``      → depth 2 (and the 2 is consumed)
      ``--refs=N``      → depth N
      absent            → depth 0
      ``--refs <non-int>`` → depth 1, non-int stays in rest
    """
    depth = 0
    out: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--refs":
            if i + 1 < len(rest):
                try:
                    depth = int(rest[i + 1])
                    i += 2
                    continue
                except ValueError:
                    pass
            depth = 1
            i += 1
            continue
        if arg.startswith("--refs="):
            try:
                depth = int(arg.split("=", 1)[1])
            except ValueError:
                depth = 1
            i += 1
            continue
        out.append(arg)
        i += 1
    return depth, out


# --- Argparse construction -------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the unified read parser.

    A single ``tokens`` bucket (``nargs='*'``) absorbs the vertex/entity
    positionals AND intermixed ``field=value`` predicates;
    ``parse_intermixed_args`` + ``_classify_tokens`` do the disambiguation
    (the brittle ``nargs='?'``-pair shape is retired — §3.4).
    """
    parser = argparse.ArgumentParser(prog="loops read")
    parser.add_argument(
        "tokens", nargs="*", default=[],
        help="[vertex] [kind/key] [field=value ...]",
    )
    # Domain selectors — change WHAT is fetched (folded state vs raw facts).
    parser.add_argument("--kind", default=None, help="Filter by fact kind")
    parser.add_argument(
        "--key", default=None,
        help="Filter by fold key (prefix; comma-OR for multiple)",
    )
    parser.add_argument("--lens", default=None, help="Lens name for rendering")
    parser.add_argument(
        "--facts", action="store_true", default=False,
        help="Show raw fact stream instead of folded state",
    )
    parser.add_argument(
        "--why", action="store_true", default=False,
        help="Per-field provenance drill for one exact kind/key address",
    )
    parser.add_argument(
        "--match", "--grep", default=None, metavar="QUERY", dest="match",
        help="Content search — FTS5 for indexed kinds, substring for the rest",
    )
    # Read-grammar transforms (S4) — applied over the projected Surface, so
    # plain and --json carry the same transformed rows.
    parser.add_argument(
        "--full", action="store_true", default=False,
        help="Force full-body (whole) granularity on every row",
    )
    parser.add_argument(
        "--fields", default=None,
        help="Comma-separated payload fields to project (narrow each row)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Keep the top-N rows by salience",
    )
    parser.add_argument(
        "--last", type=int, default=None,
        help="Keep the newest-N rows by timestamp",
    )
    parser.add_argument(
        "--count", action="store_true", default=False,
        help="Aggregate rows into counts (with --by, one row per group)",
    )
    parser.add_argument(
        "--by", default=None,
        help="Group --count by a row attribute / payload field",
    )
    # Framework survivors — registered explicitly (painted's bundled
    # registration dissolved). The dests (quiet/verbose/interactive/static/
    # live/json/plain) match what painted's parse_zoom / parse_mode /
    # parse_format read via getattr.
    zoom = parser.add_mutually_exclusive_group()
    zoom.add_argument(
        "-q", "--quiet", action="store_true",
        help="Minimal output (zoom=0)",
    )
    zoom.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="Increase detail (-v detailed, -vv full)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "-i", "--interactive", action="store_true",
        help="Interactive TUI mode (autoresearch lens)",
    )
    mode.add_argument(
        "--static", action="store_true",
        help="Static output, no animation",
    )
    mode.add_argument(
        "--live", action="store_true",
        help="Live output with in-place updates",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="JSON output — the structured Surface encoding (implies --static)",
    )
    parser.add_argument(
        "--plain", action="store_true",
        help="Plain text, no ANSI codes",
    )
    return parser


# --- Token classification --------------------------------------------------


def _classify_tokens(
    tokens: list[str], has_vertex_path: bool,
) -> tuple[str | None, str | None, dict[str, tuple[str, ...]], str | None]:
    """Sort the intermixed token bucket into (vname, entity, where, observer).

    A token containing ``=`` (and not itself a vertex path) is a PREDICATE:
    ``observer=NAME`` becomes the row-observer filter (who emitted — distinct
    from the ``--observer`` identity peel); any other ``field=value`` joins
    ``where`` (comma-OR within the value). The remaining barewords are
    positional, disambiguated exactly as the legacy ``_resolve_positionals``
    did:

      vertex file path → vertex, next bareword → entity
      contains "/"     → entity, vertex resolves locally
      bare token       → named vertex, next bareword → entity
    """
    barewords: list[str] = []
    where: dict[str, tuple[str, ...]] = {}
    observer: str | None = None
    for tok in tokens:
        if "=" in tok and not _looks_like_vertex_path(tok):
            field, _, value = tok.partition("=")
            field = field.strip()
            if not field:
                barewords.append(tok)
                continue
            if field == "observer":
                observer = value
            else:
                values = tuple(v for v in value.split(",") if v != "")
                where[field] = values or (value,)
        else:
            barewords.append(tok)

    vname: str | None = None
    entity: str | None = None
    if has_vertex_path:
        entity = barewords[0] if barewords else None
    elif barewords:
        first = barewords[0]
        if _looks_like_vertex_path(first):
            vname = first
            entity = barewords[1] if len(barewords) > 1 else None
        elif "/" in first:
            entity = first
        else:
            vname = first
            entity = barewords[1] if len(barewords) > 1 else None
    return vname, entity, where, observer


# --- Entity / vertex resolution -------------------------------------------


def _resolve_vertex_path(
    ctx: Invocation, vname: str | None,
) -> Path | None:
    """Resolve the fold's target vertex.

    Honours ``ctx.vertex_path`` first (dispatch already resolved it).
    Otherwise: name → ``_resolve_vertex_for_dispatch`` (local-first) →
    ``_resolve_named_vertex`` (config-level) → local fallback. Returns
    ``None`` only when no vertex can be located at all.
    """
    if ctx.vertex_path is not None:
        return ctx.vertex_path
    from loops.commands.identity import resolve_local_vertex
    from loops.commands.resolve import (
        _resolve_named_vertex,
        _resolve_vertex_for_dispatch,
    )

    if vname is not None:
        local = _resolve_vertex_for_dispatch(vname)
        if local is not None:
            return local
        try:
            return _resolve_named_vertex(vname)
        except Exception:
            return None
    try:
        return resolve_local_vertex()
    except FileNotFoundError:
        return None


# --- Mode resolution -------------------------------------------------------


def _resolve_mode(
    args: argparse.Namespace, lens: str | None, *, is_tty: bool
) -> str:
    """Pick an output mode from flags + lens context.

    Defaults to ``"static"`` — mirrors the legacy ``default_mode=STATIC``
    for fold. ``--live`` wins over ``--static`` **but requires a TTY**: on a
    non-tty (pipe/file) the alt-screen + infinite stream would hang with zero
    output, so it downgrades to ``"static"``
    (friction:live-mode-hangs-silently-on-pipe). ``-i`` only triggers
    INTERACTIVE for views that bind a handler (autoresearch lens).
    """
    if args.live:
        return "live" if is_tty else "static"
    if args.interactive and lens == "autoresearch":
        return "interactive"
    return "static"


# --- Fetch closures --------------------------------------------------------


def _build_fold_fetch(
    vertex_path: Path,
    observer: str | None,
    kind: str | None,
    key: str | None,
    refs_depth: int,
    want_facts: bool,
    lens: str | None,
) -> Any:
    """Return a zero-arg callable that produces the fold data.

    Honours lens-declared fetch (composition lenses) when present;
    otherwise calls ``commands.fetch.fetch_fold`` with the full kwarg
    surface.
    """
    from loops.commands.resolve import _apply_vertex_scope

    obs = _apply_vertex_scope(observer, vertex_path) or None
    _validate_kind_or_exit(kind, vertex_path)

    from loops.cli.lens import _resolve_lens_fetch

    lens_fetch = _resolve_lens_fetch(lens, vertex_path, "fold_view")

    def fetch_data():
        if lens_fetch is not None:
            from loops.lens_resolver import call_lens_fetch

            return call_lens_fetch(
                lens_fetch, vertex_path,
                kind=kind, key=key, observer=obs,
                retain_facts=want_facts,
                refs_depth=refs_depth,
            )
        from loops.commands.fetch import fetch_fold

        return fetch_fold(
            vertex_path, kind=kind, key=key, observer=obs,
            retain_facts=want_facts,
            refs_depth=refs_depth,
        )

    return fetch_data


async def _build_fold_stream(fetch_data) -> AsyncIterator[Any]:
    """Wrap a sync fetch into an async generator for live mode."""
    import asyncio

    yield fetch_data()
    while True:
        await asyncio.sleep(2)
        yield fetch_data()


def _validate_kind_or_exit(kind: str | None, vertex_path: Path | None) -> None:
    """Validate kind against vertex declarations; exit 2 on mismatch."""
    if vertex_path is None:
        return
    from loops.commands.resolve import _validate_kind_or_exit as _impl

    _impl(kind, vertex_path)


# --- Surface-spec assembly -------------------------------------------------


def _resolve_kind_key(
    entity: str | None, kind: str | None, key: str | None,
) -> tuple[str | None, str | None]:
    """Resolve the effective (kind, key_raw) from --kind/--key + entity.

    An entity ``kind/key`` splits explicitly (replacing the old args.kind
    stuffing) so the key can drive both fetch filtering AND project()'s
    complete-key whole-detection. A bare entity (no "/") is IGNORED — exactly
    as the legacy view did (it only routed "/"-bearing entities to --kind).
    Explicit --kind/--key always win (entity is only consulted when both unset).
    """
    if entity is not None and "/" in entity and kind is None and key is None:
        ekind, ekey = entity.split("/", 1)
        return ekind, ekey
    return kind, key


def _colon_address_suggestion(
    entity: str | None, kind: str | None, key: str | None
) -> str | None:
    """If ``entity`` uses ':' as the kind/key separator (the ref idiom) where
    the positional address wants '/', return the '/'-form suggestion; else None.

    A bare no-slash entity used to be silently ignored, so ``kind:key`` widened
    to the whole fold instead of addressing. Catch the colon slip and suggest
    the slash form (friction:read-address-separator-colon-vs-slash). Explicit
    --kind/--key win, so the entity is only consulted when both are unset.
    """
    if entity is None or kind is not None or key is not None:
        return None
    colon, slash = entity.find(":"), entity.find("/")
    if colon != -1 and (slash == -1 or colon < slash):
        return entity.replace(":", "/", 1)
    return None


def _resolve_key_grammar(
    key_raw: str | None,
) -> tuple[str | None, str | None, tuple[str, ...]]:
    """Resolve comma-OR --key into (fetch_key, queried_key, key_or).

    A single value flows to ``fetch_fold(key=)`` + ``project(queried_key=)``
    (preserves S1's complete-key whole-detection); 2+ values fetch unfiltered
    and filter in the Surface via ``key_or`` (fetch_fold can't express OR).
    """
    if key_raw is None:
        return None, None, ()
    parts = [p for p in key_raw.split(",") if p]
    if len(parts) > 1:
        return None, None, tuple(parts)
    if parts:
        return parts[0], parts[0], ()
    return None, None, ()


# --- Entry point -----------------------------------------------------------


def run(argv: list[str], ctx: Invocation) -> int:
    """Read/fold view entry — single argparse → Operation → dispatch.

    Steps:
      1. Pre-extract ``--refs [N]`` (manual scan; argparse can't model
         the optional-int-or-flag form cleanly).
      2. Parse remaining argv with ``parse_intermixed_args`` (positionals +
         ``field=value`` predicates intermix freely).
      3. Classify the token bucket → vertex name + entity + where + observer.
      4. Resolve effective kind/key (entity split, comma-OR --key grammar).
      5. Resolve the vertex path; build the fold fetch closure.
      6. Assemble the SurfaceSpec + Operation; dispatch.
    """
    has_vertex_path = ctx.vertex_path is not None
    refs_depth, argv = _extract_refs_depth(argv)
    parser = _build_parser()
    try:
        args = parser.parse_intermixed_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    # Plain / ANSI: --plain forces ANSI off. The reporter DERIVES use_ansi from
    # env + TTY (NO_COLOR/FORCE_COLOR/isatty — the plain-default inversion), so
    # this explicit flag is the override that wins over that derived default
    # (and over FORCE_COLOR on a TTY). Harmless for BufferReporter.
    if args.plain and hasattr(ctx.reporter, "use_ansi"):
        ctx.reporter.use_ansi = False

    vname, entity, where, observer_filter = _classify_tokens(
        list(args.tokens), has_vertex_path,
    )

    # Catch the kind:key (colon) ref-idiom reach where the positional address
    # wants kind/key (slash); it used to silently widen to the whole fold.
    suggestion = _colon_address_suggestion(entity, args.kind, args.key)
    if suggestion is not None:
        ctx.reporter.err(
            f"'{entity}': the positional address is kind/key (slash), not "
            f"kind:key (colon). Did you mean '{suggestion}'?"
        )
        return 2

    kind, key_raw = _resolve_kind_key(entity, args.kind, args.key)
    fetch_key, queried_key, key_or = _resolve_key_grammar(key_raw)

    vertex_path = _resolve_vertex_path(ctx, vname)
    if vertex_path is None:
        ctx.reporter.err("No vertex resolved — run `loops init` first.")
        return 1

    # --why is an address-scoped provenance drill: it renders ONE folded
    # (kind, key) entry field by field, so it short-circuits the multi-section
    # fold path entirely (own fetch, own lens, own --json shape).
    if args.why:
        return _run_why(
            ctx, vertex_path, kind, queried_key, key_or,
            json=(parse_format(args) is Format.JSON),
            zoom=parse_zoom(args),
        )

    fetch_data = _build_fold_fetch(
        vertex_path, ctx.observer,
        kind=kind, key=fetch_key,
        refs_depth=refs_depth,
        want_facts=args.facts,
        lens=args.lens,
    )

    # Format (JSON / PLAIN / AUTO) flows onto the Operation; dispatch forks on
    # JSON to encode the Surface via to_dict (gate-pass) or the raw FoldState
    # dump (gate-fail). No view-level short-circuit — the lens path owns it.
    fmt_format = parse_format(args)

    # Fidelity: painted compiles the pure-terminal axes (depth from -q/-v). The
    # domain-query selectors' visibility (--facts, --refs N>0) is merged in
    # loops-side — they are not painted disclosure tags
    # (decision/design/disclosure-vs-domain-query-axis).
    from dataclasses import replace as _replace

    base = parse_fidelity(args, parse_zoom(args), tags=None)
    domain_visible = set(base.visible)
    if args.facts:
        domain_visible.add("facts")
    if refs_depth > 0:
        domain_visible.add("refs")
    fidelity = _replace(base, visible=frozenset(domain_visible))

    surface_spec = SurfaceSpec(
        queried_key=queried_key,
        full=args.full,
        match=args.match,
        key_or=key_or,
        where=tuple((f, v) for f, v in where.items()),
        observer=observer_filter,
        fields=(
            tuple(f for f in args.fields.split(",") if f) if args.fields else None
        ),
        limit=args.limit,
        last=args.last,
        count_by=args.by,
        do_count=args.count,
    )

    mode = _resolve_mode(args, args.lens, is_tty=ctx.isatty)
    # JSON is a one-shot structured encode — live/interactive make no sense.
    if fmt_format is Format.JSON:
        mode = "static"
    # --live needs a TTY; on a pipe _resolve_mode downgraded it to static —
    # say so rather than silently swallowing the request.
    elif args.live and not ctx.isatty:
        ctx.reporter.err("live mode needs a TTY; rendering static instead")

    # Stream / interactive bindings ---------------------------------------
    stream_fn: Callable[[], AsyncIterator[Any]] | None = None
    if mode == "live":
        stream_fn = lambda: _build_fold_stream(fetch_data)  # noqa: E731

    interactive_handler = None
    if mode == "interactive":
        interactive_handler = _build_autoresearch_handler(vertex_path, ctx.observer)

    op = Operation(
        verb="read",
        fn=fetch_data,
        params={},
        render_lens="fold",
        lens_override=args.lens,
        fidelity=fidelity,
        format=fmt_format,
        surface_spec=surface_spec,
        # Presentation register keys on the channel (TTY = human "Threads (N):"
        # headers, pipe = terse "## KIND (N)"), decoupled from width/truncation.
        render_context={"piped": not ctx.isatty},
        vertex_path=vertex_path,
        observer=ctx.observer,
        mode=mode,  # type: ignore[arg-type]
        stream_fn=stream_fn,
        interactive_handler=interactive_handler,
    )
    return dispatch(op, reporter=ctx.reporter)


# --- Provenance drill (--why) ---------------------------------------------


def _run_why(
    ctx: Invocation,
    vertex_path: Path,
    kind: str | None,
    key: str | None,
    key_or: tuple[str, ...],
    *,
    json: bool,
    zoom: Any,
) -> int:
    """Render the per-field provenance drill for one exact (kind, key) address.

    Requires an EXACT address — a single, complete fold key (not a prefix, not
    a comma-OR set). Rejects anything else with guidance, mirroring the
    --key-on-keyless-kind error shape. Own fetch (forces retain_facts so the
    source facts are present), own lens, own --json encoding — it never touches
    the multi-section fold dispatch.
    """
    if kind is None or key is None or key_or:
        ctx.reporter.err(
            "--why needs an exact kind/key address (e.g. "
            "`read <vertex> decision/design/foo --why`) — it drills one folded "
            "entry, so a bare kind, a comma-OR set, or no address doesn't apply."
        )
        return 2
    if key.endswith("/"):
        ctx.reporter.err(
            f"--why needs an EXACT fold key, not the prefix '{key}' — "
            "name the single entry to drill (drop the trailing '/')."
        )
        return 2

    from loops.commands.fetch import fetch_fold
    from loops.commands.resolve import _apply_vertex_scope
    from loops.provenance import replay_attribution

    obs = _apply_vertex_scope(ctx.observer, vertex_path) or None
    _validate_kind_or_exit(kind, vertex_path)

    fold_op = _resolve_fold_op(vertex_path, kind)

    from atoms.fold import Upsert

    if isinstance(fold_op, Upsert):
        state = fetch_fold(
            vertex_path, kind=kind, key=key, observer=obs, retain_facts=True,
        )
        key, source = _lookup_source_facts(state, kind, key)
        prov = replay_attribution(
            fold_op, source, kind=kind, key=key, key_field=fold_op.key,
        )
    else:
        # Collect-fold (or unknown) — keyless, so chronology IS the provenance.
        # Fetch the kind unfiltered and hand the folded items over as the
        # chronological ledger; replay degrades to mode="collect".
        state = fetch_fold(vertex_path, kind=kind, observer=obs, retain_facts=True)
        facts = _collect_section_facts(state, kind)
        prov = replay_attribution(
            fold_op, facts, kind=kind, key=key, key_field=None,
        )

    if json:
        import json as _json

        from loops.provenance import to_dict as _prov_to_dict

        ctx.reporter.msg(_json.dumps(_prov_to_dict(prov)))
        return 0

    import shutil

    from loops.lenses.provenance import why_view

    width = shutil.get_terminal_size().columns if ctx.isatty else None
    block = why_view(prov, zoom, width, piped=not ctx.isatty)
    ctx.reporter.print_block(block)
    return 0


def _resolve_fold_op(vertex_path: Path, kind: str) -> Any:
    """The kind's real fold op (``spec.folds[0]``), or None when undeclared."""
    from engine.vertex_reader import _resolve_full_specs
    from lang import parse_vertex_file

    try:
        ast = parse_vertex_file(vertex_path)
        specs = _resolve_full_specs(ast, vertex_path)
    except Exception:
        return None
    spec = specs.get(kind)
    if spec is None or not spec.folds:
        return None
    return spec.folds[0]


def _lookup_source_facts(state: Any, kind: str, key: str) -> tuple[str, list[dict]]:
    """Source facts for an exact ``kind/key`` — exact, then case-folded fallback.

    Returns ``(canonical_key, facts)``: the fallback resolves a case-variant
    user key to the key the fold state actually holds, and the replay must
    use that canonical key too — ``replay_attribution`` looks the entry up
    exactly, so replaying under the user's variant would find the source
    facts yet attribute zero fields.
    """
    src = state.source_facts
    exact = src.get(f"{kind}/{key}")
    if exact is not None:
        return key, list(exact)
    want = f"{kind}/{key}".lower()
    for addr, facts in src.items():
        if addr.lower() == want:
            return addr.split("/", 1)[1], list(facts)
    return key, []


def _collect_section_facts(state: Any, kind: str) -> list[dict]:
    """Folded items of a collect kind as chronological fact dicts (ts/observer)."""
    facts: list[dict] = []
    for section in state.sections:
        if section.kind != kind:
            continue
        for item in section.items:
            pd = dict(item.payload)
            if item.ts is not None:
                pd.setdefault("_ts", item.ts)
            if item.observer:
                pd.setdefault("_observer", item.observer)
            facts.append(pd)
    facts.sort(key=lambda f: f.get("_ts") or 0)
    return facts


# --- Interactive handler (autoresearch TUI) -------------------------------


def _build_autoresearch_handler(vertex_path: Path, observer: str | None):
    """Bind the autoresearch TUI to the resolved vertex + observer.

    The handler runs the asyncio TUI app and returns its exit code (or
    0 on graceful close). Lives here rather than in dispatch so it
    stays one indirection from the args that triggered it.
    """

    def handle() -> int:
        import asyncio

        from loops.commands.resolve import _apply_vertex_scope
        from loops.tui.autoresearch_app import AutoresearchApp

        obs = _apply_vertex_scope(observer, vertex_path)
        app = AutoresearchApp(vertex_path, observer=obs)
        asyncio.run(app.run())
        return 0

    return handle
