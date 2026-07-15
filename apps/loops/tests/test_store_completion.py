"""Tests for store completion (incl. the ``ticks`` subwalk) — feature/completion-store-ls.

Three surfaces:

- ``cli.store_args.STORE_SUBCOMMANDS`` — a parity check against
  ``commands.store._run_store``'s own dispatch chain, so a new subcommand
  landing there doesn't silently go uncompleted (or a removed one keep
  advertising a dead value).
- the ``add_args`` seam (``cli.app._add_args_for("store")`` →
  ``cli.store_args.add_store_args``) — exercised end to end through
  painted's ``complete_app`` producer, the real TAB path.
- the render-free import guarantee — same shape every ``*_args`` module
  asserts.

painted's parser walk has no argparse-subparsers support (verified against
``painted.cli._argwalk``/``complete.py`` — no ``_SubParsersAction`` handling
exists), so ``store``'s per-subcommand flags are NOT mirrored here; only the
two shared positionals are. See ``cli/store_args.py``'s module docstring.
"""

from __future__ import annotations

import inspect
import re
import subprocess
import sys

from loops.cli.store_args import STORE_SUBCOMMANDS


class TestStoreSubcommandsParity:
    def test_matches_run_store_dispatch_chain(self):
        from loops.commands.store import _run_store

        source = inspect.getsource(_run_store)
        dispatched = tuple(re.findall(r'argv\[0\] == "(\w+)"', source))
        assert dispatched == STORE_SUBCOMMANDS

    def test_every_subcommand_actually_dispatches(self, monkeypatch, tmp_path):
        import loops.commands.store as store_mod

        seen = []
        for fn_name in (
            "_run_verify", "_run_rebirth", "_run_reanchor", "_run_absorb",
            "_run_adopt", "_run_store_ticks", "_run_store_stats",
        ):
            monkeypatch.setattr(
                store_mod, fn_name,
                lambda argv, name=fn_name, **kw: seen.append(name) or 0,
            )
        for name in STORE_SUBCOMMANDS:
            store_mod._run_store([name])
        assert len(seen) == len(STORE_SUBCOMMANDS)


# ---------------------------------------------------------------------------
# End to end: the add_args seam via painted's complete_app producer
# ---------------------------------------------------------------------------


class TestStoreAddArgsSeam:
    def test_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.store_args import add_store_args

        assert _add_args_for("store") is add_store_args

    def test_loops_store_offers_subcommand_names(self):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        cmds = _build_commands()
        cands = complete_app(cmds, ["store"], "", prog="loops")
        values = {c.value for c in cands}
        for name in STORE_SUBCOMMANDS:
            assert name in values

    def test_prefix_narrows_subcommand_candidates(self):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        cmds = _build_commands()
        cands = complete_app(cmds, ["store"], "rea", prog="loops")
        assert {c.value for c in cands} == {"reanchor"}

    def test_first_slot_offers_closed_choices_not_files(self):
        """The subcommand slot has static choices -> it is NOT an open
        (file-completing) slot; the seven names are the whole candidate set."""
        from loops.cli.app import _build_commands
        from painted.cli.complete import app_wants_file_completion

        cmds = _build_commands()
        assert not app_wants_file_completion(cmds, ["store"], prog="loops")

    def test_second_slot_is_an_open_file_completion(self):
        """No completer/choices on the ``file`` slot -> once a first token is
        on the line (subcommand or not), the shell's native path completion
        fills the second slot."""
        from loops.cli.app import _build_commands
        from painted.cli.complete import app_wants_file_completion

        cmds = _build_commands()
        assert app_wants_file_completion(cmds, ["store", "ticks"], prog="loops")
        assert app_wants_file_completion(cmds, ["store", "somefile.db"], prog="loops")

    def test_unknown_subcommand_word_is_not_offered(self):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        cmds = _build_commands()
        cands = complete_app(cmds, ["store"], "bogus", prog="loops")
        assert cands == []


class TestRenderFreeImport:
    def test_store_args_import_pulls_no_renderer_or_lens_body(self):
        script = (
            "import sys\n"
            "import loops.cli.store_args\n"
            "renderer = [m for m in sys.modules "
            "if 'painted.core.block' in m or 'painted.core.doc' in m]\n"
            "lenses = [m for m in sys.modules if m.startswith('loops.lenses')]\n"
            "assert not renderer, f'renderer imported: {renderer}'\n"
            "assert not lenses, f'lens body imported: {lenses}'\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"render-free import violated:\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
        assert result.stdout.strip() == "ok"
