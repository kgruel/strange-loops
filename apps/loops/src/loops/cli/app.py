"""cli.app — top-level entry point for the loops CLI.

Owns the three-tier dispatch logic that used to live in
``loops.main.main`` + ``_dispatch_verb_first`` + ``_dispatch_observer`` +
``_dispatch_command``. Routing only — the actual ``_run_*`` work happens
in the views under ``cli/views/*`` (and, for the legacy shims, in
``loops.commands.*``) looked up through ``cli.registry``.

Dispatch tiers:

  1. Verbs (``loops <verb> [vertex] …``) — ``registry.VERBS``
  2. Commands (``loops <command> …``) — ``registry.COMMANDS``
  3. Vertex shorthand (``loops <vertex> …``) — implicit read or a
     vertex-first op from ``registry.VERTEX_OPS``

``cli.app.main`` is the canonical entry point. ``loops.main.main`` is a
back-compat shim that delegates here. The previous fast-path
``_try_fast_read`` short-circuit was retired (see
``decision/cli-refactor-fast-path-retired``) and the ``argparse``
lazy-import optimisation moved out with it.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape;
decision/cli-refactor-fast-path-retired.
"""
from __future__ import annotations

import sys
from pathlib import Path

from painted.cli import AppCommand, run_app

from .invocation import Invocation
from .output import default_reporter
from .registry import COMMANDS, POPULATION_OPS, VERBS


# Verbs that use ``--observer`` as a section-selector flag rather than an
# identity override. When dispatch encounters one of these as the op, the
# global identity peel is skipped so ``--observer [NAME]`` (bare or with a
# value, in either ``--observer NAME`` or ``--observer=NAME`` form) flows
# through to the view intact. Adding a future verb that overloads
# ``--observer`` the same way is a one-line addition here.
_VERBS_USING_OBSERVER_AS_FLAG = frozenset({"ls"})

# Global flags that consume the next token as their value. Used by
# ``_identify_op_token`` so that an op-token search skips over the
# value slot — preventing ``--observer ls emit ...`` from mis-identifying
# ``"ls"`` (the observer value) as the operation token.
_VALUE_TAKING_GLOBAL_FLAGS = frozenset({"--observer"})


def _identify_op_token(
    argv: list[str],
) -> tuple[str | None, list[str], list[str]]:
    """Find the operation token in argv, skipping value-taking global flags.

    The naive "first non-flag token" peek fails when a value-taking global
    flag's value happens to match a verb name (e.g. ``--observer ls`` —
    "ls" is the observer identifier, not the op). This scan respects the
    ``--observer VALUE`` and ``--observer=VALUE`` shapes so the op-token
    classification is correct regardless of what the value happens to be.

    Bare global flags (``--observer`` with no following value) are treated
    as bare flags and skipped past — the value-absence is downstream's
    problem, not the dispatcher's.

    Returns ``(op_token, before_op, after_op)`` so callers can decide
    whether to peel global flags only from ``before_op`` (verbs that
    overload the flag) or from the full argv (verbs that don't):
      ``before_op``: tokens scanned past while searching for the op
      ``after_op``:  the op token and everything beyond
    """
    i = 0
    while i < len(argv):
        tok = argv[i]
        # --observer=VALUE form: single token, advance one.
        if "=" in tok and tok.split("=", 1)[0] in _VALUE_TAKING_GLOBAL_FLAGS:
            i += 1
            continue
        # --observer VALUE form: only skip the value when a value actually
        # follows (and isn't itself another flag). Otherwise treat as a
        # bare flag — falling into the next branch.
        if tok in _VALUE_TAKING_GLOBAL_FLAGS:
            if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                i += 2
                continue
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok, argv[:i], argv[i:]
    return None, list(argv), []


def _is_predicate_token(tok: str) -> bool:
    """True when a token is a read-grammar ``field=value`` / ``observer=``
    predicate rather than an operation name.

    Such tokens route to the implicit read so ``sl <vertex> status=open`` filters
    rather than erroring as an unknown op. A leading ``-`` (a flag) or a ``.vertex``
    path is never a predicate. The ``=`` discriminator mirrors the fold view's
    ``_classify_tokens`` — both must agree on what counts as a predicate.
    """
    return (
        "=" in tok
        and not tok.startswith("-")
        and not tok.endswith(".vertex")
    )


def _peel_observer(rest: list[str]) -> tuple[str | None, list[str]]:
    """Strip ``--observer X`` from rest and return (resolved_observer, rest').

    Mirrors the pre-parse the legacy ``_dispatch_verb_first`` and
    ``_dispatch_observer`` performed inline — keeps observer resolution
    out of individual view parsers. Resolution itself defers to
    ``commands.resolve._resolve_observer_flag`` to preserve the env →
    .vertex chain.

    Note (fix/ls-flag-grammar, 2026-05-17): ls now accepts ``--observer``
    as a section-selector flag (bare or with a name). To avoid colliding
    with the identity peel, only ``--observer VALUE`` pairs are consumed
    here; a bare ``--observer`` (with no value, or followed by another
    ``--*`` token) is left in place for the downstream view to interpret.
    """
    from loops.commands.resolve import _resolve_observer_flag

    observer_value: str | None = None
    out: list[str] = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg == "--observer":
            # Only consume the pair when a non-flag value follows.
            if i + 1 < len(rest) and not rest[i + 1].startswith("-"):
                observer_value = rest[i + 1]
                i += 2
                continue
            # Bare --observer (or --observer --something) — leave for downstream.
            out.append(arg)
            i += 1
            continue
        if arg.startswith("--observer="):
            observer_value = arg.split("=", 1)[1]
            i += 1
            continue
        out.append(arg)
        i += 1

    return _resolve_observer_flag(observer_value), out


def _vertex_first(
    vertex_name: str, vertex_path: Path, rest: list[str]
) -> int:
    """Dispatch ``loops <vertex> [op] [args]`` — vertex resolved upfront.

    Replicates legacy ``_dispatch_observer``: default (no subcommand) is
    an implicit read; named ops route through ``VERBS`` or the
    population helpers; population ops reconstruct the qualified-vertex
    argv shape the legacy commands expect.
    """
    # Peek the verb (skipping value-taking global flags like
    # ``--observer VALUE``) so we can decide where the identity peel
    # applies. The peek is value-aware: ``--observer ls emit ...``
    # correctly identifies ``emit`` as the op (and not ``ls``, which is
    # the observer value).
    #
    # When the verb itself uses ``--observer`` as a flag (currently just
    # ``ls``), we peel only from the args BEFORE the op token — so
    # ``sl <v> --observer alice ls`` still applies ``alice`` as the
    # global identity override while leaving ``sl <v> ls --observer kyle``
    # to flow through to ls as the section narrow. For all other verbs
    # the peel runs over the full rest as before.
    verb, before_op, after_op = _identify_op_token(rest)
    if verb in _VERBS_USING_OBSERVER_AS_FLAG:
        observer, before_op = _peel_observer(before_op)
        rest = before_op + after_op
    else:
        observer, rest = _peel_observer(rest)
    ctx = Invocation(
        reporter=default_reporter(),
        vertex_path=vertex_path,
        vertex_name=vertex_name,
        observer=observer,
    )

    # Default: no subcommand, flags only, or a leading read-grammar predicate
    # (``sl <vertex> status=open``) → implicit read (fold). The predicate guard
    # keeps ``field=value`` / ``observer=`` from being mis-read as an unknown op.
    if not rest or rest[0].startswith("-") or _is_predicate_token(rest[0]):
        return VERBS["read"](rest, ctx)

    op = rest[0]
    args = rest[1:]

    if op in VERBS:
        return VERBS[op](args, ctx)

    # Population ops embed the (possibly qualified) vertex name into argv.
    # `loops <vertex> ls [qualifier] [flags]` → `loops ls vertex/qualifier flags`.
    # The qualifier is for template-population narrowing (e.g. `sl reading ls
    # feeds`). Section sub-verbs (kind/observer/combine/row) and section
    # flags (--kind/...) pass through unchanged so ls.py can interpret them.
    if op == "ls":
        ls_subverbs = {"kind", "observer", "combine", "row"}
        target = vertex_name
        flags = list(args)
        if flags and not flags[0].startswith("-") and flags[0] not in ls_subverbs:
            target = f"{vertex_name}/{flags[0]}"
            flags = flags[1:]
        return POPULATION_OPS["ls"]([target, *flags], ctx)

    if op in POPULATION_OPS:
        return POPULATION_OPS[op]([vertex_name, *args], ctx)

    ctx.reporter.err(f"Unknown operation: {op}")
    return 1


# ---------------------------------------------------------------------------
# run_app integration — painted owns dispatch and top-level help rendering.
#
# Tiers 1 (verbs) and 2 (dev/setup commands) collapse into ONE painted
# ``run_app`` call over a unified ``AppCommand`` list. painted routes
# ``argv[0]`` → handler, renders the top-level help (``loops`` / ``loops -h``)
# through its doc_lens, and forwards per-command ``-h`` to each view's own
# argparse. The hand-rolled three-tier dispatcher + argparse help epilog
# dissolve into the framework (decision/design/full-painted-integration-residue:
# "anything painted can do, prefer painted").
#
# What stays loops-side (domain residue, correctly):
#   - Observer peeling (``--observer`` as identity override) — a verb-only
#     selector painted has no concept of.
#   - The vertex-shorthand pre-router (``loops <vertex> [op]``) — painted's
#     run_app routes known arg0 → command; it does not model "unknown arg0 ⇒
#     default handler with arg0 as data."
# ---------------------------------------------------------------------------

# One-line descriptions for the painted top-level help. Source of truth for
# the command roster shown by ``loops`` / ``loops -h``.
_DESCRIPTIONS: dict[str, str] = {
    # verbs (peel --observer)
    "read": "Fold and show vertex state",
    "emit": "Append a fact to a vertex",
    "close": "Close a session — mint a boundary tick",
    "sync": "Sync facts between stores",
    "cite": "Bump prior facts that informed this turn",
    "seal": "Seal a window — mint a signed tick",
    "store": "Inspect a store database",
    # dev / setup commands (do not peel --observer)
    "test": "Run a .loop source and preview facts",
    "compile": "Compile a .loop / .vertex file",
    "validate": "Validate .loop / .vertex syntax",
    "init": "Scaffold a vertex from a template",
    "whoami": "Show the resolved observer identity",
    "ls": "List vertices (or template populations)",
    "add": "Add a template-population row",
    "rm": "Remove a template-population row",
    "export": "Export a template population",
}

# Verbs peel a leading ``--observer NAME`` from their post-verb argv as an
# identity override; dev/setup commands do not (``ls`` overloads ``--observer``
# as a section selector and interprets it itself — preserved from the legacy
# ``_command`` path, which never peeled).
_PEEL_OBSERVER: frozenset[str] = frozenset(VERBS)


def _make_handler(view, *, peel_observer: bool):
    """Adapt a registry ``View`` (argv, Invocation)->int to a painted handler.

    painted's ``AppCommand.handler`` receives only the post-command argv and
    returns an exit code. The Invocation (domain phase) is constructed here:
    observer is peeled for verbs, vertex_path stays ``None`` (verb-first
    resolves the vertex inside the view from the first positional / local
    fallback, unchanged from the legacy ``_verb_first`` / ``_command``).
    """

    def handler(argv: list[str]) -> int:
        if peel_observer:
            observer, rest = _peel_observer(argv)
        else:
            observer, rest = None, argv
        ctx = Invocation(
            reporter=default_reporter(),
            vertex_path=None,
            observer=observer,
        )
        return view(rest, ctx)

    return handler


def _build_commands() -> list[AppCommand]:
    """Build the unified painted ``AppCommand`` roster (verbs ∪ commands).

    ``store`` is registered under both VERBS and COMMANDS; the verb shape
    (which peels observer) wins, and the duplicate command entry is skipped
    so painted's one-name-one-command invariant holds.
    """
    cmds: list[AppCommand] = []
    for name, view in VERBS.items():
        cmds.append(
            AppCommand(
                name,
                _DESCRIPTIONS[name],
                _make_handler(view, peel_observer=name in _PEEL_OBSERVER),
            )
        )
    for name, view in COMMANDS.items():
        if name in VERBS:  # `store` — already registered as a verb
            continue
        cmds.append(
            AppCommand(
                name,
                _DESCRIPTIONS[name],
                _make_handler(view, peel_observer=name in _PEEL_OBSERVER),
            )
        )
    return cmds


_APP_DESCRIPTION = (
    "loops — emit, fold, stream across vertices\n"
    "Zoom: -q minimal · default summary · -v detailed · -vv full"
)


def main(argv: list[str] | None = None) -> int:
    """Top-level CLI entry point.

    painted's ``run_app`` owns verb/command dispatch + top-level help. The
    loops-side residue is the vertex-shorthand pre-router (tier 3) and the
    observer peel inside each handler. ``loops.main.main`` is a back-compat
    shim that delegates here.
    """
    if argv is None:
        argv = sys.argv[1:]

    commands = _build_commands()
    known = {c.name for c in commands}

    # Tiers 1+2 and top-level help → painted run_app.
    if not argv or argv[0] in ("-h", "--help") or argv[0] in known:
        return run_app(
            argv, commands, prog="loops", description=_APP_DESCRIPTION
        )

    # Tier 3: vertex shorthand — ``loops <vertex> [op] …``. painted has no
    # notion of "unknown arg0 ⇒ default command", so this stays the loops
    # pre-router in front of the framework.
    vertex_name = argv[0]
    from loops.commands.resolve import _resolve_vertex_for_dispatch

    vertex_path = _resolve_vertex_for_dispatch(vertex_name)
    if vertex_path is not None:
        return _vertex_first(vertex_name, vertex_path, argv[1:])

    # Path-like arg with no resolved vertex → hint the right invocation.
    if (
        vertex_name.endswith(".vertex")
        or vertex_name.startswith("./")
        or vertex_name.startswith("/")
    ):
        default_reporter().err(
            f"File arguments go with a command: loops sync {vertex_name}"
        )
        return 1

    default_reporter().err(f"Unknown command: {vertex_name}")
    return 1


__all__ = ["main"]
