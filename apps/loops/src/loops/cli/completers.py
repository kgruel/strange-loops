"""loops domain completers — dynamic ``<TAB>`` values the parser can't hold.

Painted owns the completion engine (parse → candidates, the parser's third
reflection); loops owns the *domain* completers hung on individual argparse
actions via ``complete_via`` (see ``cli/read_args.py`` for the attachment
sites). This module holds the callables.

Two invariants every completer here keeps:

- **Render-free to import.** The module-level imports touch only the
  render-free ``painted.cli`` completion surface — never ``painted`` (the
  renderer), never a lens/command body. A completer that reflects heavier
  state imports it *inside its own body*, so pressing TAB imports the renderer
  for no completer and runs no command. (A regression test asserts this via
  ``sys.modules``.)
- **Under-list, never crash.** A completer tolerates missing or broken state
  by returning ``[]``. TAB must never traceback — a partial line, an
  unreadable vertex, a syntax-broken lens file all degrade to fewer
  candidates, never an exception into the shell.
"""
from __future__ import annotations

from painted.cli import Candidate, CompletionContext


def _clean(values: list[Candidate]) -> list[Candidate]:
    """Drop candidates that would corrupt the line-oriented shell protocol.

    painted's zsh emitter escapes ``:`` but not control characters (Sol
    review review/completion-t3 #8, round 2 #6), and fold keys are arbitrary
    JSON strings — a ``\\n`` splits the line protocol, a leading ``\\x1f``
    collides with painted's file-completion directive, and ``\\x1b`` injects
    terminal escapes into the menu. Values with ANY control character are
    dropped (under-list, never lie); descriptions are soft — control chars
    collapse to a space.
    """

    def _has_ctl(s: str) -> bool:
        return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in s)

    cleaned: list[Candidate] = []
    for c in values:
        if _has_ctl(c.value):
            continue
        desc = c.description
        if desc and _has_ctl(desc):
            desc = "".join(
                " " if (ord(ch) < 0x20 or ord(ch) == 0x7F) else ch for ch in desc
            )
            desc = " ".join(desc.split())
            c = Candidate(c.value, desc)
        cleaned.append(c)
    return cleaned


def complete_lens(ctx: CompletionContext) -> list[Candidate]:
    """Complete ``--lens <TAB>`` with every resolvable lens + its description.

    Offers built-in lenses (``loops.lenses.*``) and custom lens files across
    the three resolver tiers (vertex-local, cwd, user-global), each with its
    module-docstring one-liner as a described row. When the line already names
    a vertex, vertex-local lenses are scoped to *that* vertex's ``lenses/`` dir
    — a lens local to another vertex isn't offered.

    Enumeration is inspection-only (``ast``), so this stays on the render-free
    TAB path. Any failure → ``[]``.
    """
    try:
        from loops.lens_resolver import enumerate_lenses

        vertex_dir = _vertex_dir_on_line(ctx)
        return _clean([
            Candidate(info.name, info.description)
            for info in enumerate_lenses(vertex_dir=vertex_dir)
        ])
    except Exception:
        return []


def complete_vertex(ctx: CompletionContext) -> list[Candidate]:
    """Complete the leading vertex positional with every resolvable name.

    Scoped to the FIRST token only: once a bareword already occupies the
    vertex slot (``ctx.args["tokens"]`` non-empty — the positional's
    already-parsed prefix), this is completing a later slot (kind/key,
    ``field=value``) that this slice doesn't offer candidates for, so it
    defers by returning ``[]`` rather than guessing.

    Enumeration is a filesystem walk plus a per-candidate KDL parse (no store
    open), so this stays on the render-free TAB path. Any failure -> ``[]``.
    """
    try:
        tokens = ctx.args.get("tokens") or []
    except Exception:
        return []
    if tokens:
        return []
    try:
        from loops.commands.resolve import enumerate_vertices

        return _clean([
            Candidate(info.name, info.description) for info in enumerate_vertices()
        ])
    except Exception:
        return []


def complete_read_vertex(ctx: CompletionContext) -> list[Candidate]:
    """``complete_vertex`` narrowed to names READ's classifier accepts.

    Read's positional grammar treats a slash-bearing bareword as an entity
    address, never a vertex (``fold._classify_tokens``) — so a slashed vertex
    name (``comms/discord``), legal for emit, is *invented* if offered on the
    read line (Sol review review/completion-t3 #4). Same enumeration, slashed
    names filtered.
    """
    return [c for c in complete_vertex(ctx) if "/" not in c.value]


def complete_kind(ctx: CompletionContext) -> list[Candidate]:
    """Complete ``--kind <TAB>`` with the kinds declared by the vertex on the line.

    Resolves the vertex bareword the same way ``complete_vertex``/
    ``_vertex_path_on_line`` do; no vertex on the line (or resolution
    failure) → ``[]`` rather than guessing.

    Enumeration is a plain KDL parse of the ``.vertex`` (``_declared_kind_names``
    — no store open), so this stays on the render-free, instant TAB path. Any
    failure → ``[]``.
    """
    try:
        vertex_path = _vertex_path_on_line(ctx)
        if vertex_path is None:
            return []
        return _kind_candidates(vertex_path)
    except Exception:
        return []


def _kind_candidates(vertex_path) -> list[Candidate]:
    """Kind candidates for one resolved vertex path — shared read/emit core."""
    from loops.commands.resolve import _declared_kind_names

    return _clean([Candidate(name) for name in _declared_kind_names(vertex_path)])


def complete_key(ctx: CompletionContext) -> list[Candidate]:
    """Complete ``--key <TAB>`` with namespace prefixes for the (vertex, kind)
    already on the line.

    Requires both a resolvable vertex and a ``--kind`` value already typed —
    a fold key's namespace is scoped per kind, so without ``--kind`` there is
    no single key space to prefix-complete, and this defers with ``[]``.

    Unlike ``complete_vertex``/``complete_kind``, this DOES open the store:
    namespace prefixes live in fact key values, not the declaration
    (``enumerate_key_prefixes`` — a single ``LIMIT``-bounded probe). Any
    failure (no vertex, no store, broken database) → ``[]``.
    """
    try:
        vertex_path = _vertex_path_on_line(ctx)
        if vertex_path is None:
            return []
        kind = ctx.args.get("kind")
        if not kind:
            return []
        from loops.commands.resolve import enumerate_key_prefixes

        return _clean([
            Candidate(key)
            for key in enumerate_key_prefixes(vertex_path, kind, ctx.prefix)
        ])
    except Exception:
        return []


def complete_emit_tokens(ctx: CompletionContext) -> list[Candidate]:
    """Complete emit's single ``tokens`` bucket — vertex, then kind.

    Emit's grammar (``sl emit <vertex> <kind> key=value...``) collects into
    one ``nargs='*'`` positional, so — unlike ``read``'s separate ``--kind``/
    ``--key`` flags — there is only one action to hang a completer off. This
    composes the two existing completers by position: an empty bucket is the
    vertex slot (``complete_vertex``); exactly one token typed is the kind
    slot (``complete_kind``, which resolves the vertex from that token).
    Anything beyond that (``field=value`` payload parts) is out of scope for
    this slice — ``[]``.
    """
    try:
        tokens = ctx.args.get("tokens") or []
    except Exception:
        return []
    if not tokens:
        return complete_vertex(ctx)
    if len(tokens) == 1:
        # Emit's vertex slot resolves through the DISPATCH resolver (slashed
        # names legal), not read's entity classification — mirror emit's
        # runtime, not read's.
        vertex_path = _dispatch_vertex_path(tokens[0])
        if vertex_path is None:
            return []
        return _kind_candidates(vertex_path)
    return []


def _vertex_path_on_line(ctx: CompletionContext):
    """Resolve read's target vertex for the tokens already on the line.

    Mirrors the READ runtime's positional classification
    (``cli/views/fold._classify_tokens`` — a parity regression test holds the
    two together), not the dispatch resolver: a slash-bearing first bareword
    is an *entity address* to read, never a vertex name, and the read then
    targets the local vertex (Sol review review/completion-t3 #4). Offering
    ``remote/vertex``'s kinds there would invent candidates the runtime
    rejects.

      first bareword is a .vertex path  → that file
      first bareword contains "/"       → entity → the LOCAL vertex
      first bareword is a bare name     → resolve the name
      no bareword at all                → the LOCAL vertex (runtime fallback)

    Best-effort: ``None`` on any failure.
    """
    try:
        tokens = ctx.args.get("tokens") or []
    except Exception:
        return None

    first = None
    for tok in tokens:
        # Skip predicates (field=value) and flags — only barewords classify.
        # Vertex-like paths are exempt from the predicate skip, exactly as
        # fold's classifier exempts them (``"=" in tok and not
        # _looks_like_vertex_path(tok)``) — ``./x=y.vertex`` is a path, not
        # a predicate (Sol review review/completion-t3 round 2 #5).
        if not isinstance(tok, str) or tok.startswith("-"):
            continue
        if "=" in tok and not (
            tok.startswith(("/", "./", "../")) or tok.endswith(".vertex")
        ):
            continue
        first = tok
        break

    from loops.commands.resolve import _find_local_vertex, _resolve_vertex_for_dispatch

    try:
        if first is None:
            return _find_local_vertex()
        # Mirror fold._looks_like_vertex_path: absolute / ./ / ../ / .vertex
        if (
            first.startswith(("/", "./", "../"))
            or first.endswith(".vertex")
        ):
            from pathlib import Path

            p = Path(first)
            return p if p.is_file() else None
        if "/" in first:  # entity address → runtime reads the LOCAL vertex
            return _find_local_vertex()
        return _resolve_vertex_for_dispatch(first)
    except Exception:
        return None


def _dispatch_vertex_path(token: str):
    """Resolve a vertex token the way EMIT's runtime does (dispatch resolver).

    Emit accepts slashed vertex names (``comms/native``) — its resolution is
    ``_resolve_vertex_for_dispatch``, not read's entity classification. Kept
    separate from ``_vertex_path_on_line`` so each completer mirrors its own
    runtime. ``None`` on any failure.
    """
    try:
        from loops.commands.resolve import _resolve_vertex_for_dispatch

        return _resolve_vertex_for_dispatch(token)
    except Exception:
        return None


def _vertex_dir_on_line(ctx: CompletionContext):
    """Resolve the vertex already typed on the line to its directory, or None.

    Scopes vertex-local candidates to the vertex being read (``complete_lens``).
    Thin wrapper over ``_vertex_path_on_line`` — same best-effort/None-on-miss
    contract, one level up (directory, not file).
    """
    path = _vertex_path_on_line(ctx)
    return path.parent if path is not None else None
