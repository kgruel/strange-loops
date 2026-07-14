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
        return [
            Candidate(info.name, info.description)
            for info in enumerate_lenses(vertex_dir=vertex_dir)
        ]
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

        return [
            Candidate(info.name, info.description) for info in enumerate_vertices()
        ]
    except Exception:
        return []


def _vertex_dir_on_line(ctx: CompletionContext):
    """Resolve the vertex already typed on the line to its directory, or None.

    Scopes vertex-local candidates to the vertex being read. Best-effort: the
    first positional token that resolves as a vertex wins; no token, or nothing
    resolvable, → None (which still lists cwd / user / built-in lenses). Any
    failure → None.
    """
    try:
        tokens = ctx.args.get("tokens") or []
    except Exception:
        return None

    from loops.commands.resolve import _resolve_vertex_for_dispatch

    for tok in tokens:
        # Skip predicates (field=value) and flags — only barewords name a vertex.
        if not isinstance(tok, str) or "=" in tok or tok.startswith("-"):
            continue
        path = _resolve_vertex_for_dispatch(tok)
        if path is not None:
            return path.parent
    return None
