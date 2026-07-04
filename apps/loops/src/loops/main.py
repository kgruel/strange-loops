"""loops CLI — entry point and back-compat re-export surface.

Verb-first dispatch: loops <verb> [vertex] [args]
Verbs: read, emit, close, sync, cite
Commands: test, compile, validate, store, init, ls, whoami

Behaviour is owned by ``loops.cli.app``. This module re-exports all
symbols that tests and internal callers address via ``loops.main``.
"""
from __future__ import annotations

import os
import sys

from loops.errors import LoopsError  # noqa: F401
from loops.commands.resolve import (  # noqa: F401 — re-export for back-compat
    loops_home, _find_local_vertex, _warn_missing_fold_key, _extract_kind_keys,
    _try_topology_from_store, _topology_kind_keys_and_stores, _resolve_entity_refs,
    _resolve_writable_vertex, _resolve_vertex_store_path, _resolve_named_store,
    _resolve_named_vertex, _resolve_combine_child, _resolve_vertex_for_dispatch,
    _resolve_observer_flag, _apply_vertex_scope,
    _parse_vars, _resolve_vertex_path, _vertex_name, _declared_kinds, _validate_kind_or_exit,
)
from loops.commands.init import (  # noqa: F401
    _ROOT_VERTEX, _MINIMAL_INSTANCE, _extract_block_text, _extract_loops_text,
    _find_source_vertex, _init_local_vertex, _register_with_aggregator,
    _seed_config_facts, _scaffold_artifacts, cmd_init, _run_init,
)
from loops.commands.store import _run_store  # noqa: F401
from loops.commands.population import (  # noqa: F401
    _run_ls, _run_ls_root, _run_add, _run_rm, _run_export,
)
from loops.commands.devtools import _run_validate, _run_test, _run_compile  # noqa: F401
from loops.commands.sync import (  # noqa: F401
    _resolve_combine_vertex_paths, _execute_boundary_run, _run_sync_aggregate, _run_sync,
)
from loops.commands.emit import (  # noqa: F401
    _parse_emit_parts, cmd_emit, _run_emit, _run_close, _add_produced,
)
from loops.commands.stream import _run_stream  # noqa: F401
from loops.cli.views.fold import _extract_refs_depth, _looks_like_vertex_path  # noqa: F401
from loops.commands.whoami import _run_whoami, _whoami_from_identity_store  # noqa: F401
from loops.commands.ticks import _tick_drill_header, _run_ticks  # noqa: F401
from loops.cli.lens import (  # noqa: F401
    _get_vertex_lens_decl, _exit_lens_not_found, _effective_lens_name,
    _resolve_render_fn, _resolve_lens_fetch,
)
_VERBS = frozenset({"read", "emit", "close", "sync", "cite"})
_DEV_COMMANDS = frozenset({"test", "compile", "validate", "store"})
_SETUP_COMMANDS = frozenset({"init", "whoami", "ls", "add", "rm", "export"})
_COMMANDS = _DEV_COMMANDS | _SETUP_COMMANDS
_VERTEX_OPS = frozenset({"read", "emit", "close", "sync", "store", "cite", "ls", "add", "rm", "export"})


def main(argv: list[str] | None = None) -> int:
    """Entry point — delegates to ``cli.app.main``."""
    from loops.cli.app import main as _cli_main
    try:
        return _cli_main(argv if argv is not None else sys.argv[1:])
    except BrokenPipeError:
        # Downstream pipe reader (head, grep -m) closed early — normal, not an
        # error. Point stdout at devnull so the interpreter's exit-time flush
        # doesn't raise again, and exit with the conventional SIGPIPE status.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass  # stdout isn't a real fd (tests, embedding) — nothing to flush

        return 128 + 13


if __name__ == "__main__":
    sys.exit(main())
