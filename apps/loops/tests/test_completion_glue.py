"""The completion glue registers every installed entry point.

``[project.scripts]`` installs the CLI as both ``loops`` and ``sl``; the
``aliases`` wiring in ``cli/app.py``'s ``run_app`` call must keep the
generated zsh glue registering both names (multi-name ``#compdef``), or the
alias silently falls back to zsh's default file completion — the exact
regression this locks out (painted fix/compdef-aliases, 2026-07-15).
"""

from loops.cli.app import main


def test_zsh_glue_registers_loops_and_sl(capsys):
    rc = main(["completion", "zsh"])
    assert rc == 0
    first_line = capsys.readouterr().out.splitlines()[0]
    assert first_line == "#compdef loops sl"
