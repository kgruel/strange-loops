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
    """Run root-level ls: stat-over-containment listing, local layer first.

    `sl ls` is the resumption orient at the front door
    (decision:design/ls-as-stat-over-containment): the local layer is always
    stat'd (facts / last-update / kind-count), the config layer collapses to a
    drillable count-line unless ``--all`` expands it. ``-1`` is the terse
    names-only opt-out (decision B/C / `-1` in the design doc).
    """
    import argparse
    from pathlib import Path

    from painted import run_cli
    from .resolve import loops_home
    from .vertices import fetch_vertices, fetch_vertices_local
    from ..lenses.vertices import vertices_view

    home = loops_home()

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--all", "-a", dest="all_", action="store_true", default=False)
    pre.add_argument("-1", dest="terse", action="store_true", default=False)
    known, rest = pre.parse_known_args(argv)
    expand_config = known.all_
    terse = known.terse

    def fetch():
        # Local layer first — same precedence the verbs use
        # (thread:global-local-walk-broken). Local is always stat'd; config is
        # stat'd lazily, only when --all expands it past the count-line.
        from typing import Any

        local = fetch_vertices_local(with_stats=not terse)
        data: dict[str, Any]
        # Config is stat'd when expanded OR when it IS the primary listing
        # (no local layer — outside a project). Collapsed-to-count-line is the
        # only case that skips the per-vertex stat read.
        config_stats = (expand_config or not local) and not terse
        try:
            data = fetch_vertices(home, with_stats=config_stats)
        except FileNotFoundError:
            if not local:
                raise
            data = {"vertices": []}
        if local:
            # A local vertex shadows the config one of the same name; carry the
            # shadowed path so the listing can name what's being overridden.
            global_paths = {v["name"]: v.get("path") for v in data["vertices"]}
            for v in local:
                v["shadows"] = v["name"] in global_paths
                if v["shadows"]:
                    v["shadows_path"] = global_paths[v["name"]]
            data["local_vertices"] = local
            data["cwd"] = str(Path.cwd())
        data["expand_config"] = expand_config
        data["terse"] = terse
        return data

    def render(ctx, data):
        return vertices_view(
            data, ctx.zoom, ctx.width, piped=not getattr(ctx, "is_tty", True)
        )

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops ls",
        description="List vertices (stat-over-containment)",
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
