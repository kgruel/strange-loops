"""Verb / command registry — maps names to view callables.

Two tables:

  VERBS: the five primary vertex verbs (read, emit, sync, close, cite)
    plus the data-access verbs that share the verb-first dispatch shape
    (store, ticks). Each entry is a ``View`` — ``(argv, ctx) -> int``.

  COMMANDS: the dev-tool and setup commands (test, compile, validate,
    init, ls, add, rm, export, whoami). Same View shape.

In step 2 every entry wraps a legacy ``loops.main._run_*`` function
through ``_legacy_view``. The wrapper bridges the (argv, kwargs=…)
signature the legacy code uses to the (argv, ctx) signature the
registry promises. As individual views migrate (steps 3–5) their
entries are repointed at the new ``cli/views/<name>.py:run`` directly.

The registry is intentionally lazy: each entry resolves its target
function on first call via a lambda + ``importlib``. This keeps
``cli.app`` importable without dragging the whole CLI surface in,
which preserves the ``loops <vertex>`` fast-path's cold-start budget
during the migration.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import CliContext


# A view is a callable that takes argv + context and returns an exit code.
View = Callable[[list[str], "CliContext"], int]


def _legacy_view(
    fn_name: str,
    *,
    takes_observer: bool = True,
) -> View:
    """Wrap a legacy ``loops.main._run_*`` symbol into View shape.

    Resolves ``fn_name`` against ``loops.main`` on each call (lazy lookup
    — the symbol may be a re-export that swaps target during migration).
    Passes ``vertex_path`` always; passes ``observer`` only for verbs
    that accept it (``sync`` and ``store`` don't).
    """

    def view(argv: list[str], ctx: "CliContext") -> int:
        import loops.main as main_mod

        fn = getattr(main_mod, fn_name)
        kwargs: dict = {"vertex_path": ctx.vertex_path}
        if takes_observer:
            kwargs["observer"] = ctx.observer
        return fn(argv, **kwargs)

    return view


def _legacy_view_argv_only(fn_name: str) -> View:
    """Wrap a legacy function that takes just ``argv`` (no vertex/observer).

    Used by dev/setup commands whose entrypoints don't accept the
    vertex_path/observer kwargs (test, compile, validate, init, whoami,
    ls/add/rm/export — which take vertex embedded in argv).
    """

    def view(argv: list[str], ctx: "CliContext") -> int:  # noqa: ARG001 — ctx reserved
        import loops.main as main_mod

        fn = getattr(main_mod, fn_name)
        return fn(argv)

    return view


def _view(module_path: str, fn_name: str = "run") -> View:
    """Wrap a new cli.views module's ``run`` (or named) function as a View.

    Resolves lazily on first call to avoid pulling argparse + downstream
    imports at registry-build time. The optional ``fn_name`` lets a
    single view module expose several entries (cli.views.population
    re-uses one module for ls/add/rm/export).
    """

    def view(argv: list[str], ctx: "CliContext") -> int:
        from importlib import import_module

        mod = import_module(module_path)
        return getattr(mod, fn_name)(argv, ctx)

    return view


# Primary vertex verbs — used by both verb-first and vertex-first dispatch.
# As individual views migrate to cli/views/* they swap from _legacy_view
# (which wraps loops.main._run_*) to _view (which calls the new run()).
VERBS: dict[str, View] = {
    "read": _view("loops.cli.views.read"),
    "emit": _view("loops.cli.views.emit"),
    "close": _legacy_view("_run_close"),
    "sync": _legacy_view("_run_sync", takes_observer=False),
    "cite": _view("loops.cli.views.cite"),
    "store": _view("loops.cli.views.store"),
}


# Dev tools and setup commands — direct dispatch (no vertex resolution).
# Top-level "ls" lists vertices (population.run_ls_root); the per-vertex
# variant (population.run_ls) is reached only via vertex-first dispatch
# and lives in POPULATION_OPS["ls"].
COMMANDS: dict[str, View] = {
    "test": _legacy_view_argv_only("_run_test"),
    "compile": _legacy_view_argv_only("_run_compile"),
    "validate": _legacy_view_argv_only("_run_validate"),
    "store": _view("loops.cli.views.store"),
    "init": _legacy_view_argv_only("_run_init"),
    "whoami": _legacy_view_argv_only("_run_whoami"),
    "ls": _view("loops.cli.views.population", "run_ls_root"),
    "add": _view("loops.cli.views.population", "run_add"),
    "rm": _view("loops.cli.views.population", "run_rm"),
    "export": _view("loops.cli.views.population", "run_export"),
}


# Population ops reached via ``loops <vertex> <op>`` — these consume the
# qualified vertex name as the first positional in argv. Disambiguated
# from COMMANDS because the top-level "ls" means "list vertices" while
# the vertex-first "ls" means "list template populations".
POPULATION_OPS: dict[str, View] = {
    "ls": _view("loops.cli.views.population", "run_ls"),
    "add": _view("loops.cli.views.population", "run_add"),
    "rm": _view("loops.cli.views.population", "run_rm"),
    "export": _view("loops.cli.views.population", "run_export"),
}


# Vertex-first ops dispatchable as `loops <vertex> <op>`. Subset of VERBS
# plus the population ops. Some entries differ from VERBS because the
# vertex name is reconstructed into argv by the dispatcher (ls/add/rm/
# export), so they go through their _argv_only counterparts.
VERTEX_OPS: frozenset[str] = frozenset({
    "read", "emit", "close", "sync", "cite", "store",
    "ls", "add", "rm", "export",
})


def has_verb(name: str) -> bool:
    """True if ``name`` is a known primary verb."""
    return name in VERBS


def has_command(name: str) -> bool:
    """True if ``name`` is a known dev/setup command."""
    return name in COMMANDS
