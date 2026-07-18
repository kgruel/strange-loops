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
from ..read_args import add_read_args


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
    """Build the unified read parser for the handler's own parse pass.

    The DOMAIN args live in ``cli/read_args.add_read_args`` — the single source
    shared with painted's intercepted ``-h`` and shell completion (which walk
    that declaration through ``build_parser`` without running the command). The
    FRAMEWORK flags are added here explicitly: this handler parser bypasses
    painted's ``build_parser`` (which would otherwise supply them via
    ``add_cli_args``), so it owns their registration. The dests
    (quiet/verbose/interactive/static/live/json/plain) match what painted's
    parse_zoom / parse_mode / parse_format read via ``getattr``.
    """
    parser = argparse.ArgumentParser(prog="loops read")
    add_read_args(parser)

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
    # painted's reflected parser advertises --no-input for every command, so
    # completion offers it; the runtime must accept it (Sol review
    # review/completion-t3 #1). Honest no-op: read asks no prompts.
    parser.add_argument("--no-input", action="store_true", help=argparse.SUPPRESS)
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


# --- Temporal cursor (0.8.0) — --at / --as-of resolution -------------------


class CursorAddressError(Exception):
    """Wraps any --at/--as-of resolution failure with a ``read --at/--as-of:
    `` prefix — the single catch site in ``run()`` reports it and exits 2."""


def _anchor_dict(position: Any) -> dict | None:
    """JSON-clean projection of a ``WitnessPosition.anchor`` (TickAnchor)."""
    anchor = position.anchor
    if anchor is None:
        return None
    return {"name": anchor.name, "ts": anchor.ts, "fact_cursor": anchor.fact_cursor}


def _resolve_cursor(
    vertex_path: Path, at_address: str | None, as_of_raw: str | None,
) -> tuple[Any, float | None, dict]:
    """Resolve ``--at``/``--as-of`` (mutually exclusive, enforced upstream by
    the read router) into ``(witness_position_or_None, as_of_ts_or_None,
    cursor_meta)``.

    ``cursor_meta`` is the machine-readable mode/status/position disclosure
    (A11) — carried in ``render_context`` for text rendering and merged into
    the JSON payload by ``dispatch``. Raises :class:`CursorAddressError` for
    every failure mode (aggregate refusal, unresolvable address, mid-ceremony
    position, out-of-range seq, unanchored wall-clock/tick) with the
    underlying teaching message intact.
    """
    from loops.cli.witness_address import (
        AddressError,
        is_aggregate_vertex,
        refuse_aggregate_at,
        resolve_at_address,
    )
    from loops.commands.resolve import _resolve_vertex_store_path

    if at_address is not None:
        if is_aggregate_vertex(vertex_path):
            raise CursorAddressError(str(refuse_aggregate_at(at_address)))
        try:
            store_path = _resolve_vertex_store_path(vertex_path)
        except Exception as exc:  # VertexNotFound/VertexParseError etc.
            raise CursorAddressError(str(exc)) from exc
        if store_path is None:
            raise CursorAddressError(
                "this vertex has no store — there is nothing to address a "
                "witness position against."
            )
        try:
            position = resolve_at_address(store_path, at_address)
        except AddressError as exc:
            raise CursorAddressError(str(exc)) from exc
        except Exception as exc:  # engine WitnessResolutionError family
            raise CursorAddressError(str(exc)) from exc

        from engine import durable_handle, load_declaration_status

        _ast, status = load_declaration_status(vertex_path, at=position)
        # A10 durable-handle contract (B1a): only an adopted store yields a
        # PORTABLE handle (fact:<lineage>/<id>); an unadopted position is
        # session-local, so no reusable handle is advertised — `durable_handle`
        # is None and consumers render the id as non-portable, never as a bare
        # `fact:ID` that would silently resolve in another store.
        handle = durable_handle(position)
        meta = {
            "mode": "witness",
            "address": at_address,
            "status": status,
            "fact_id": position.fact_id,
            "seq": position.seq,
            "unadopted": position.unadopted,
            "lineage": position.lineage,
            "durable_handle": handle,
            "portable": handle is not None,
            "anchor": _anchor_dict(position),
        }
        return position, None, meta

    # --as-of: the explicit event-time projection. Same duration/epoch/ISO
    # grammar the shipped stream/ticks --as-of already accepts.
    from datetime import datetime, timezone

    from loops.commands.fetch import _parse_as_of

    try:
        as_of_ts = _parse_as_of(as_of_raw, datetime.now(timezone.utc))
    except ValueError as exc:
        raise CursorAddressError(str(exc)) from exc

    from engine import load_declaration_status

    _ast, status = load_declaration_status(vertex_path, as_of=as_of_ts)
    meta = {"mode": "as_of", "address": as_of_raw, "status": status, "as_of": as_of_ts}
    return None, as_of_ts, meta


# --- Fetch closures --------------------------------------------------------


def _lens_fetch_accepts_cursor(fetch_fn: Any, *, at: bool, as_of: bool) -> bool:
    """True when a lens-declared fetch can honor the active cursor selector.

    Mirrors ``call_lens_fetch``'s own signature-based dispatch (``**kwargs``
    opts into everything; otherwise only named params are passed) so this
    check and the actual call always agree on what "accepts" means. Called
    by ``run()`` BEFORE dispatch — a lens fetch that doesn't declare the
    active selector would silently answer at head while the render context
    still carries witness/as_of metadata (review finding 2: a head answer
    mislabeled as a historical one). ``at``/``as_of`` here are just "is this
    selector active", not the resolved values.
    """
    import inspect

    params = inspect.signature(fetch_fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    if at and "at" not in params:
        return False
    if as_of and "as_of" not in params:
        return False
    return True


def _build_fold_fetch(
    vertex_path: Path,
    observer: str | None,
    kind: str | None,
    key: str | None,
    refs_depth: int,
    want_facts: bool,
    lens_fetch: Any,
    *,
    at: Any = None,
    as_of: float | None = None,
) -> Any:
    """Return a zero-arg callable that produces the fold data.

    Takes an already-resolved lens-declared fetch (composition lenses) —
    resolved once by the caller (``run``), which also checks it can honor
    an active cursor selector (``_lens_fetch_accepts_cursor``) before ever
    reaching here, so this closure never needs a fallback "did it actually
    apply the cursor" check of its own. ``None`` falls through to
    ``commands.fetch.fetch_fold``. ``at``/``as_of`` (0.8.0 temporal cursor)
    pass straight through either path.
    """
    from loops.commands.resolve import _apply_vertex_scope

    obs = _apply_vertex_scope(observer, vertex_path) or None
    _validate_kind_or_exit(kind, vertex_path)

    def fetch_data():
        if lens_fetch is not None:
            from loops.lens_resolver import call_lens_fetch

            return call_lens_fetch(
                lens_fetch, vertex_path,
                kind=kind, key=key, observer=obs,
                retain_facts=want_facts,
                refs_depth=refs_depth,
                at=at, as_of=as_of,
            )
        from loops.commands.fetch import fetch_fold

        return fetch_fold(
            vertex_path, kind=kind, key=key, observer=obs,
            retain_facts=want_facts,
            refs_depth=refs_depth,
            at=at, as_of=as_of,
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
    # fold path entirely (own fetch, own lens, own --json shape). Cursor
    # addressing on --why is out of scope tonight — refuse rather than
    # silently drop the flag (the same honesty stance as the router refusal).
    # --diff is a SEPARATE temporal operation (two reconstructions), not a
    # cursor address, but the same silent-discard hazard applies: --why
    # returns before the --diff branch ever runs, so `--why --diff A..B`
    # used to answer the head provenance query while --diff vanished with
    # no error (capstone M4).
    if args.why:
        if args.at or args.as_of or args.diff:
            flag = "--diff" if args.diff else ("--at" if args.at else "--as-of")
            ctx.reporter.err(
                f"read --why: {flag} is not supported together with --why "
                "yet — the provenance drill always reads at head (historical "
                "why is future work)."
            )
            return 2
        return _run_why(
            ctx, vertex_path, kind, queried_key, key_or,
            json=(parse_format(args) is Format.JSON),
            zoom=parse_zoom(args),
        )

    # --diff: two full reconstructions + a structural diff. Wholly different
    # render shape from a single fold, so it short-circuits here too (own
    # fetch pair, own render, own --json shape) — mirrors --why.
    if args.diff:
        return _run_diff(ctx, vertex_path, args, kind=kind, key=fetch_key)

    # Temporal cursor (0.8.0, A8/A11): --at (witness) / --as-of (event-time)
    # are mutually exclusive (enforced by the read router before this view
    # ever runs) and resolve to a position/ts + machine-readable metadata.
    at_position: Any = None
    as_of_ts: float | None = None
    cursor_meta: dict | None = None
    if args.at or args.as_of:
        try:
            at_position, as_of_ts, cursor_meta = _resolve_cursor(
                vertex_path, args.at, args.as_of,
            )
        except CursorAddressError as exc:
            ctx.reporter.err(f"read: {exc}")
            return 2

    # Resolve the lens fetch ONCE here (rather than inside _build_fold_fetch)
    # so a cursor selector can be checked against it before anything runs:
    # a lens-declared fetch that doesn't accept at=/as_of= would otherwise
    # silently answer at head while cursor_meta still claims a witness/as_of
    # position — a head answer mislabeled as historical (review finding 2).
    # Refuse rather than degrade; the built-in fold fetch (lens_fetch is
    # None) always supports both, so this never fires on the default path.
    from loops.cli.lens import _resolve_lens_fetch

    lens_fetch = _resolve_lens_fetch(args.lens, vertex_path, "fold_view")
    if cursor_meta is not None and lens_fetch is not None:
        if not _lens_fetch_accepts_cursor(
            lens_fetch, at=at_position is not None, as_of=as_of_ts is not None,
        ):
            flag = "--at" if at_position is not None else "--as-of"
            ctx.reporter.err(
                f"read: this vertex's lens fetch doesn't accept {flag} — "
                "it would answer at head while the response still claimed "
                "a historical position. Drop --at/--as-of, or use a lens "
                "whose fetch declares at=/as_of= (or **kwargs)."
            )
            return 2

    fetch_data = _build_fold_fetch(
        vertex_path, ctx.observer,
        kind=kind, key=fetch_key,
        refs_depth=refs_depth,
        want_facts=args.facts,
        lens_fetch=lens_fetch,
        at=at_position,
        as_of=as_of_ts,
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

    # Interactive dispatch (autoresearch TUI) is head-only in 0.8.0: the
    # cursor was already resolved above into at_position/as_of_ts/cursor_meta,
    # but dispatch's INTERACTIVE branch calls op.interactive_handler() directly
    # and never touches op.fn/fetch_data at all — the resolved position would
    # be silently discarded and the TUI would read live/head data while the
    # user believed they'd addressed a historical one (capstone M5). Refuse
    # rather than let the Operation carry a cursor no code path applies.
    if mode == "interactive" and (at_position is not None or as_of_ts is not None):
        flag = "--at" if at_position is not None else "--as-of"
        ctx.reporter.err(
            f"read -i: {flag} is not supported together with -i yet — "
            "interactive mode (autoresearch) is head-only in 0.8.0. Drop "
            f"{flag}, or drop -i for a static witnessed/event-time read."
        )
        return 2

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
        # "cursor" (0.8.0, A11) carries the --at/--as-of mode/status/position
        # disclosure — read by the fold lens (mode-line) and by dispatch's
        # JSON branch (merged into the structured payload).
        render_context={
            "piped": not ctx.isatty,
            **({"cursor": cursor_meta} if cursor_meta is not None else {}),
        },
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
    from engine.declaration import load_declaration
    from engine.vertex_reader import _resolve_full_specs

    try:
        ast = load_declaration(vertex_path)
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




# --- Structural diff (0.8.0, C2) -------------------------------------------


def _split_diff_addresses(
    at_value: str | None, diff_value: str,
) -> tuple[str | None, str | None, str | None]:
    """Split ``--diff``'s value (+ optional ``--at``) into two addresses.

    Two accepted forms: ``--diff A..B`` (split on the first ``..`` — ISO
    fractional seconds use a single dot, never a double, so this is
    unambiguous) or ``--at A --diff B`` (the trivial alt syntax). Returns
    ``(addr1, addr2, error)`` — exactly one of the pair is ``None`` on error.
    """
    if ".." in diff_value:
        if at_value:
            return None, None, (
                "give either `--diff A..B` or `--at A --diff B`, not both"
            )
        a, b = diff_value.split("..", 1)
        a, b = a.strip(), b.strip()
        if not a or not b:
            return None, None, (
                f"`--diff {diff_value!r}` needs two addresses on either "
                "side of '..'"
            )
        return a, b, None
    if not at_value:
        return None, None, (
            "--diff needs two addresses: `--diff A..B`, or `--at A --diff B`"
        )
    return at_value, diff_value, None


def _diff_snapshot(state: Any) -> dict[str, dict[str, dict]]:
    """A ``FoldState`` reduced to ``{kind: {key: payload}}`` for diffing.

    Keyed (``by``-fold) sections diff at the key level. Each key's payload
    carries a synthetic ``_n`` (revision count) alongside the visible
    fields — a backdated arrival that loses the ``(ts, id)`` replay to an
    earlier-received-but-later-ts fact leaves the VISIBLE payload unchanged
    (the winner didn't change) while still advancing the receipt count; `_n`
    is what makes that witnessed event honestly visible in the diff instead
    of two positions that "look" identical.

    Keyless (``collect``) sections have no stable per-item identity to diff
    against, so they reduce to a single synthetic ``"_count"`` entry — an
    honest degradation (item-level collect diffing is out of scope, not
    silently faked).
    """
    out: dict[str, dict[str, dict]] = {}
    for section in state.sections:
        if section.key_field:
            snap: dict[str, dict] = {}
            for item in section.items:
                key = str(item.payload.get(section.key_field, ""))
                payload = dict(item.payload)
                payload["_n"] = item.n
                snap[key] = payload
            out[section.kind] = snap
        else:
            out[section.kind] = {"_count": {"n": len(section.items)}}
    return out


def _compute_diff(before: dict, after: dict) -> list[dict]:
    """Structural (kind, key) diff between two ``_diff_snapshot`` maps.

    One row per kind that differs: keyed kinds carry added/removed/changed
    keys (changed = same key, different payload); collect kinds carry a
    before/after item count. Kinds identical across both sides are omitted.
    """
    rows: list[dict] = []
    for kind in sorted(set(before) | set(after)):
        b, a = before.get(kind, {}), after.get(kind, {})
        if "_count" in b or "_count" in a:
            bn, an = b.get("_count", {}).get("n", 0), a.get("_count", {}).get("n", 0)
            if bn != an:
                rows.append({"kind": kind, "collect_count": (bn, an)})
            continue
        added = sorted(set(a) - set(b))
        removed = sorted(set(b) - set(a))
        changed = sorted(k for k in (set(a) & set(b)) if a[k] != b[k])
        if added or removed or changed:
            rows.append({
                "kind": kind, "added": added, "removed": removed,
                "changed": [(k, b[k], a[k]) for k in changed],
            })
    return rows


def _diff_row_to_json(row: dict) -> dict:
    if "collect_count" in row:
        before, after = row["collect_count"]
        return {"kind": row["kind"], "collect_count": {"before": before, "after": after}}
    return {
        "kind": row["kind"],
        "added": row["added"],
        "removed": row["removed"],
        "changed": [
            {"key": k, "before": b, "after": a} for k, b, a in row["changed"]
        ],
    }


def _run_diff(
    ctx: Invocation, vertex_path: Path, args: argparse.Namespace,
    *, kind: str | None, key: str | None,
) -> int:
    """``--diff A..B``: two full reconstructions + a structural fold diff.

    Never incremental — a backdated arrival inserts early in ``(ts, id)``
    replay and can change order-sensitive state, so each endpoint is folded
    independently from scratch (the same discipline ``--at`` uses). Each
    endpoint resolves through the same address grammar and aggregate
    refusal as a bare ``--at`` (``_resolve_cursor``). Mixed axis (one
    endpoint witness, one event-time) is refused — same-axis endpoints only
    tonight (C2); since this implementation's two addresses are always
    witness-grammar, the only reachable "mixed" request is `--as-of`
    combined with `--diff`, refused explicitly below.
    """
    if args.as_of:
        ctx.reporter.err(
            "read --diff: mixed modes are refused — one endpoint would be "
            "event-time (--as-of), the other a witness address (--diff's "
            "grammar). Give two witness addresses instead: `--diff A..B` "
            "(or `--at A --diff B`)."
        )
        return 2

    addr1, addr2, err = _split_diff_addresses(args.at, args.diff)
    if err is not None:
        ctx.reporter.err(f"read --diff: {err}")
        return 2

    try:
        pos1, _, meta1 = _resolve_cursor(vertex_path, addr1, None)
        pos2, _, meta2 = _resolve_cursor(vertex_path, addr2, None)
    except CursorAddressError as exc:
        ctx.reporter.err(f"read --diff: {exc}")
        return 2

    from loops.commands.fetch import fetch_fold
    from loops.commands.resolve import _apply_vertex_scope

    obs = _apply_vertex_scope(ctx.observer, vertex_path) or None
    state1 = fetch_fold(vertex_path, kind=kind, key=key, observer=obs, at=pos1)
    state2 = fetch_fold(vertex_path, kind=kind, key=key, observer=obs, at=pos2)
    rows = _compute_diff(_diff_snapshot(state1), _diff_snapshot(state2))

    # Interval honesty (M8/A13): a structural diff can look "clean" while
    # something still happened between the two positions — a late (backdated)
    # arrival, or a declaration change — that a payload-level diff would never
    # surface. Both endpoints already resolved against the SAME store (a
    # precondition diff_interval_report also documents), so this is best-effort
    # supplementary info: a failure here must not sink the diff itself.
    interval: dict | None = None
    try:
        from engine import diff_interval_report
        from loops.commands.resolve import _resolve_vertex_store_path

        store_path = _resolve_vertex_store_path(vertex_path)
        if store_path is not None:
            interval = diff_interval_report(store_path, pos1, pos2)
    except Exception:
        interval = None

    if interval is not None:
        # Baseline attribution (codex re-verify, post-capstone): the engine
        # report is symmetric by rowid — late arrivals are computed against
        # the rowid-LOWER endpoint, whichever the user named first. Only this
        # layer knows which CLI label ('from'/'to') that endpoint wears, so
        # stamp it here for both the JSON contract and the lens sentence; a
        # reversed `--diff B..A` must attribute the baseline to 'to', not
        # hardcode 'from'.
        interval = {
            **interval,
            "baseline": "from" if pos1.rowid <= pos2.rowid else "to",
        }

    if parse_format(args) is Format.JSON:
        import json as _json

        ctx.reporter.msg(_json.dumps({
            "mode": "diff", "from": meta1, "to": meta2,
            "sections": [_diff_row_to_json(r) for r in rows],
            "interval": interval,
        }))
        return 0

    import shutil

    from loops.lenses.fold import diff_view

    width = shutil.get_terminal_size().columns if ctx.isatty else None
    block = diff_view(
        meta1, meta2, rows, width, piped=not ctx.isatty, interval=interval,
    )
    ctx.reporter.print_block(block)
    return 0


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
