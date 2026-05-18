"""Vertex command dispatchers — thin shims over commands/{ls,add,rm}.

After Phase 3 (plan:vertex-living-document) these functions are just
delegates: the real work happens in commands/ls.py, commands/add.py,
commands/rm.py. `_run_export` is retired (returns an error message).
`_run_ls_root` remains for `loops ls` (no vertex) which lists all
discovered vertices.
"""
from __future__ import annotations


def _run_ls(argv: list[str]) -> int:
    """Dispatch ``loops ls`` — unified declarations view (Phase 3).

    Routes to the new ``commands/ls.py`` dispatcher: unified by default,
    narrowed by subcommand (kind / observer / combine / row).
    """
    from .ls import _run_ls as _dispatch

    return _dispatch(argv)


def _run_ls_root(argv: list[str]) -> int:
    """Run root-level ls: list all discovered vertices."""
    from painted import run_cli
    from .resolve import loops_home
    from .vertices import fetch_vertices
    from ..lenses.vertices import vertices_view

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
    """Dispatch ``loops add`` — vertex declarations or legacy row-add.

    Phase 2 (plan:vertex-living-document) adds subcommands kind/observer/
    combine for declaring new entities directly in the vertex file. The
    bare-positional form (``loops add reading lobsters URL``) is preserved
    as an implicit ``row`` and will be retired in Phase 3.
    """
    from .add import _run_add as _dispatch

    return _dispatch(argv)


def _run_rm(argv: list[str]) -> int:
    """Dispatch ``loops rm`` — vertex declarations or legacy row-rm.

    Phase 3 (plan:vertex-living-document) adds subcommands kind/observer/
    combine for removing declared entities from the vertex file. The
    bare-positional form (``loops rm reading lobsters``) is preserved as
    an implicit ``row`` and will be retired in a later cleanup.
    """
    from .rm import _run_rm as _dispatch

    return _dispatch(argv)


def _run_export(argv: list[str]) -> int:  # noqa: ARG001 — argv kept for back-compat
    """Retired in Phase 3 (plan:vertex-living-document).

    `loops export <vertex>` used to materialize a .list file by folding
    pop.add/pop.rm facts. Phase 3 dissolves the fact-driven indirection:
    the .list file is canonical; direct edits via `loops add/rm row`
    are the only path. There is nothing to materialize from.
    """
    import sys

    from painted import Block, show
    from painted.palette import current_palette

    show(
        Block.text(
            "loops export was retired in Phase 3. "
            "The .list file is canonical now; use `loops add/rm <vertex> row` "
            "to edit it directly.",
            current_palette().error,
        ),
        file=sys.stderr,
    )
    return 1
