"""``loops read <typo>`` gets the did-you-mean treatment.

Closes friction:read-vertex-not-found-lacks-suggestion (simplify pass,
item 11 — ruled in-wave): a NAMED vertex that resolves nowhere reports via
``resolve._unknown_vertex_message`` (the miss, close matches, the known
list) on stderr at the existing nonzero exit, instead of the misleading
"No vertex resolved — run `loops init` first." — which stays for the
genuinely-bare case (no name given, nothing local).

Parity: ls's miss path prints the SAME helper's output (byte-parity of the
message content by shared source — both sites call
``_unknown_vertex_message``; only the surrounding channel differs).
"""
import pytest

from loops.main import main


_VERTEX = """\
name "project"
store "./project.db"

loops {
  thread { fold { items "by" "name" } }
}
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    vdir = tmp_path / "home" / "project"
    vdir.mkdir(parents=True)
    (vdir / "project.vertex").write_text(_VERTEX)
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)  # no local vertex layer
    return tmp_path / "home"


def test_read_typo_vertex_suggests_and_exits_nonzero(home, capsys):
    rc = main(["read", "projct"])
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ""
    assert "vertex not found: projct" in captured.err
    assert "Did you mean: project?" in captured.err
    assert "Known vertices: project" in captured.err
    # The bare-case wording must NOT fire for a named miss — it teaches
    # `loops init` when the fix is a spelling.
    assert "No vertex resolved" not in captured.err


def test_read_typo_message_matches_ls_for_the_same_typo(home, capsys):
    from loops.commands.resolve import _unknown_vertex_message

    expected = _unknown_vertex_message("projct")
    assert main(["read", "projct"]) != 0
    read_err = capsys.readouterr().err
    assert main(["ls", "projct"]) != 0
    ls_err = capsys.readouterr().err
    # NOT byte-parity: the formats differ. ls prints the helper's text raw
    # (three lines); read routes through the Reporter, whose painted text
    # block collapses the newlines to spaces. Same source, same content —
    # compare whitespace-normalized.
    normalized = " ".join(expected.split())
    assert normalized in " ".join(read_err.split())
    assert normalized in " ".join(ls_err.split())


def test_bare_read_with_nothing_resolvable_keeps_init_hint(
    tmp_path, monkeypatch, capsys,
):
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "empty-home"))
    monkeypatch.chdir(tmp_path)
    rc = main(["read"])
    captured = capsys.readouterr()
    assert rc != 0
    assert "No vertex resolved" in captured.err
