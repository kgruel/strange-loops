"""Regression tests for --help routing across all verbs and commands.

Every entry in VERBS + COMMANDS must exit 0 and emit recognisable help text.
Sub-verb paths (add/rm/ls sub-verbs, row bareform) are exercised explicitly
so future regressions are caught here rather than discovered in smoke walks.

Note on exit behaviour: commands that route through painted's ``run_cli``
call ``sys.exit(0)`` on ``--help``; argparse-based commands return 0.
``_help()`` accepts both forms so both surfaces are covered.
"""

from __future__ import annotations

import pytest

from loops.main import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _help(capsys, *argv: str) -> str:
    """Run main() with given argv, assert help exits 0, return stdout.

    Painted's ``run_cli`` calls ``sys.exit(0)`` on ``--help``; stock argparse
    parsers return 0.  Both are valid — catch either.
    """
    try:
        rc = main(list(argv))
    except SystemExit as exc:
        rc = int(exc.code) if exc.code is not None else 1
    assert rc == 0, f"Expected rc=0 for {argv!r}, got {rc}"
    captured = capsys.readouterr()
    return captured.out


def _has_help(out: str) -> bool:
    """True if the output looks like any recognisable help format."""
    lo = out.lower()
    return "usage" in lo or "loops" in lo or "help" in lo


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


class TestTopLevelHelp:
    def test_no_args(self, capsys):
        out = _help(capsys)
        assert "loops" in out
        assert "verbs" in out.lower()

    def test_help_flag(self, capsys):
        out = _help(capsys, "--help")
        assert "loops" in out

    def test_store_not_duplicated(self, capsys):
        out = _help(capsys, "--help")
        # "store" should appear in the verbs line but NOT the commands line.
        lines = out.splitlines()
        verbs_line = next((l for l in lines if l.startswith("verbs:")), "")
        commands_line = next((l for l in lines if l.startswith("commands:")), "")
        assert "store" in verbs_line
        assert "store" not in commands_line


# ---------------------------------------------------------------------------
# Primary verbs
# ---------------------------------------------------------------------------


class TestVerbHelp:
    @pytest.mark.parametrize("verb", ["read", "emit", "close", "sync", "cite", "store"])
    def test_verb_help(self, capsys, verb):
        out = _help(capsys, verb, "--help")
        assert _has_help(out), f"{verb} --help: output didn't look like help: {out!r}"

    def test_read_flag_descriptions(self, capsys):
        out = _help(capsys, "read", "--help")
        assert "--kind" in out
        assert "--facts" in out
        assert "--lens" in out
        # Verify the help= strings we added are present.
        assert "Filter by fact kind" in out
        assert "raw fact stream" in out

    def test_close_help_exits_zero(self, capsys):
        # Blocker: close previously had add_help=False, would error with
        # "arguments are required: kind, name"
        try:
            rc = main(["close", "--help"])
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 1
        assert rc == 0

    def test_sync_help_exits_zero(self, capsys):
        # Blocker: sync previously crashed during vertex resolution
        try:
            rc = main(["sync", "--help"])
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 1
        assert rc == 0


# ---------------------------------------------------------------------------
# Dev/setup commands
# ---------------------------------------------------------------------------


class TestCommandHelp:
    @pytest.mark.parametrize("cmd", ["init", "validate"])
    def test_command_help(self, capsys, cmd):
        out = _help(capsys, cmd, "--help")
        assert _has_help(out), f"{cmd} --help: output didn't look like help: {out!r}"

    def test_ls_help(self, capsys):
        out = _help(capsys, "ls", "--help")
        assert _has_help(out)
        for sv in ("kind", "observer", "combine", "row"):
            assert sv in out

    def test_add_help(self, capsys):
        out = _help(capsys, "add", "--help")
        assert _has_help(out)
        for sv in ("kind", "observer", "combine", "row"):
            assert sv in out

    def test_rm_help(self, capsys):
        out = _help(capsys, "rm", "--help")
        assert _has_help(out)
        for sv in ("kind", "observer", "combine", "row"):
            assert sv in out


# ---------------------------------------------------------------------------
# Vertex-scoped sub-verb help (no real vertex needed — intercept before resolve)
# ---------------------------------------------------------------------------


class TestSubVerbHelp:
    """--help intercept must fire BEFORE vertex resolution for add/rm/ls."""

    @pytest.mark.parametrize("verb,sub", [
        ("add", "kind"),
        ("add", "observer"),
        ("add", "combine"),
        ("add", "row"),
        ("rm", "kind"),
        ("rm", "observer"),
        ("rm", "combine"),
        ("rm", "row"),
    ])
    def test_vertex_sub_verb_help(self, capsys, verb, sub):
        # "project" vertex does not exist — help must fire before resolution
        out = _help(capsys, verb, "project", sub, "--help")
        assert _has_help(out), f"{verb} project {sub} --help: output: {out!r}"

    def test_add_vertex_help(self, capsys):
        # sl add project --help: intercept before vertex resolution
        out = _help(capsys, "add", "project", "--help")
        assert _has_help(out)

    def test_rm_vertex_help(self, capsys):
        out = _help(capsys, "rm", "project", "--help")
        assert _has_help(out)

    def test_ls_vertex_help(self, capsys):
        out = _help(capsys, "ls", "project", "--help")
        assert _has_help(out)

    def test_add_row_bareform_help(self, capsys):
        # sl add project row --help: row bareform must NOT swallow --help
        out = _help(capsys, "add", "project", "row", "--help")
        assert _has_help(out)

    def test_rm_row_bareform_help(self, capsys):
        # sl rm project row --help: same guarantee
        out = _help(capsys, "rm", "project", "row", "--help")
        assert _has_help(out)
