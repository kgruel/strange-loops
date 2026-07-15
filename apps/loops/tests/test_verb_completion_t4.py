"""Tests for cite/seal/close/sync completion wiring (shell completion T4).

All four verbs share the same domain completer (``complete_vertex``,
already covered by ``test_vertex_completion.py`` /
``test_completion_review_remediation.py``) — this file exercises the
``add_args`` seam itself: ``cli.app._add_args_for`` wiring, the
render-free-import guarantee for each new ``*_args`` module, and the
end-to-end walk through painted's ``complete_app`` producer (the same
path a shell TAB actually drives).

``cite`` never takes a vertex positional (see ``cli/cite_args.py``), so
it gets no vertex-completion coverage here — only the render-free-import
and seam-wiring checks apply.
"""

import subprocess
import sys
from pathlib import Path

import pytest


def _write_instance(directory: Path, name: str, *, kinds: tuple[str, ...] = ("thing",)) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    blocks = "".join(f'  {k} {{ fold {{ count "inc" }} }}\n' for k in kinds)
    (directory / f"{name}.vertex").write_text(
        f'name "{name}"\n'
        f'store "./data/{name}.db"\n\n'
        "loops {\n"
        f"{blocks}"
        "}\n",
        encoding="utf-8",
    )


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Isolate cwd and LOOPS_HOME — same shape as ``test_vertex_completion.py``."""
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir()
    home.mkdir()
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: cwd))
    monkeypatch.setenv("LOOPS_HOME", str(home))
    return tmp_path


def _render_free_import_check(module: str) -> None:
    script = (
        "import sys\n"
        f"import {module}\n"
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
        f"render-free import violated for {module}:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert result.stdout.strip() == "ok"


class TestRenderFreeImport:
    @pytest.mark.parametrize("module", [
        "loops.cli.cite_args",
        "loops.cli.seal_args",
        "loops.cli.close_args",
        "loops.cli.sync_args",
    ])
    def test_args_module_import_pulls_no_renderer_or_lens_body(self, module):
        _render_free_import_check(module)


class TestAddArgsSeamWiring:
    def test_cite_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.cite_args import add_cite_args

        assert _add_args_for("cite") is add_cite_args

    def test_seal_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.seal_args import add_seal_args

        assert _add_args_for("seal") is add_seal_args

    def test_close_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.close_args import add_close_args

        assert _add_args_for("close") is add_close_args

    def test_sync_wired_into_add_args_for(self):
        from loops.cli.app import _add_args_for
        from loops.cli.sync_args import add_sync_args

        assert _add_args_for("sync") is add_sync_args


class TestSealCompletionEndToEnd:
    def test_loops_seal_offers_vertex_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["seal"], "", prog="loops")
        assert "project" in {c.value for c in cands}


class TestCloseCompletionEndToEnd:
    def test_loops_close_offers_vertex_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["close"], "", prog="loops")
        assert "project" in {c.value for c in cands}


class TestSyncCompletionEndToEnd:
    def test_loops_sync_offers_vertex_names(self, isolated):
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["sync"], "", prog="loops")
        assert "project" in {c.value for c in cands}


class TestCiteHasNoVertexPositional:
    def test_loops_cite_offers_no_vertex_candidates(self, isolated):
        # cite always resolves the local/vertex-first vertex — verb-first
        # `sl cite <TAB>` completes the first ref, not a vertex name.
        from loops.cli.app import _build_commands
        from painted.cli import complete_app

        _write_instance(Path.cwd() / ".loops", "project")
        cmds = _build_commands()
        cands = complete_app(cmds, ["cite"], "", prog="loops")
        assert "project" not in {c.value for c in cands}


class TestAdvertisedFlagsAreAccepted:
    """Pattern A (single-source) modules can't drift, but this guards the
    seam against a future edit that duplicates instead of shares."""

    def _advertised(self, add_args) -> set[str]:
        from painted.cli import build_parser

        parser = build_parser(prog="x", add_args=add_args)
        return {
            opt
            for a in parser._actions
            for opt in a.option_strings
            if opt not in ("-h", "--help")
        }

    def test_cite_flags_present(self):
        from loops.cli.cite_args import add_cite_args

        assert {"--context", "-m", "--message", "--dry-run"} <= self._advertised(
            add_cite_args
        )

    def test_seal_flags_present(self):
        from loops.cli.seal_args import add_seal_args

        # -q/--quiet is intentionally omitted from the render-free walk —
        # it collides with painted's framework zoom -q (see seal_args.py's
        # docstring) — so it is not asserted here.
        assert {
            "-m", "--message", "--observer", "--dry-run",
        } <= self._advertised(add_seal_args)

    def test_close_flags_present(self):
        from loops.cli.close_args import add_close_args

        assert {"--dry-run"} <= self._advertised(add_close_args)

    def test_sync_flags_present(self):
        from loops.cli.sync_args import add_sync_args

        assert {"--force", "-f", "--var"} <= self._advertised(add_sync_args)


class TestIncludeVertexConditional:
    """``include_vertex=False`` (vertex-first dispatch shape) drops the
    positional entirely — mirrors the runtime's own conditional."""

    def test_seal_omits_vertex_positional(self):
        import argparse

        from loops.cli.seal_args import add_seal_args

        parser = argparse.ArgumentParser()
        add_seal_args(parser, include_vertex=False)
        positionals = [a.dest for a in parser._actions if not a.option_strings]
        assert "vertex" not in positionals

    def test_close_omits_vertex_positional(self):
        import argparse

        from loops.cli.close_args import add_close_args

        parser = argparse.ArgumentParser()
        add_close_args(parser, include_vertex=False)
        positionals = [a.dest for a in parser._actions if not a.option_strings]
        assert "vertex" not in positionals
        assert positionals == ["kind", "name", "message"]

    def test_sync_omits_vertex_positional(self):
        import argparse

        from loops.cli.sync_args import add_sync_args

        parser = argparse.ArgumentParser()
        add_sync_args(parser, include_vertex=False)
        positionals = [a.dest for a in parser._actions if not a.option_strings]
        assert "vertex" not in positionals
