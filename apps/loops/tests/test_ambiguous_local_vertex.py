"""Verb-first forms that name no vertex must REFUSE when the local tier holds
more than one instance vertex.

``_find_local_vertex`` breaks the tie alphabetically, so in a repo carrying
``agent-attestation.vertex`` and ``project.vertex`` a bare ``sl cite REF``
wrote to agent-attestation while ``sl emit project cite ref=REF`` wrote to
project — same input, two stores, no signal
(friction:find-local-vertex-alphabetical-pick).

Pinned here: the refusal (rc 2 + teaching message naming the candidates and
the explicit form), the single-vertex happy path (unchanged), and that an
explicitly named vertex bypasses the check entirely.
"""
from __future__ import annotations

import pytest

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import cite as cite_view
from loops.cli.views import fold as read_view
from loops.cli.views import seal as seal_view
from loops.commands.emit import _run_emit


_VERTEX = """\
name "{name}"
store "./{name}.db"

loops {{
  thread {{ fold {{ items "by" "name" }} }}
  cite {{ fold {{ items "collect" 0 }} }}
  decision {{ fold {{ items "by" "topic" }} }}
}}
"""

_AGGREGATION = """\
name "all"

combine {
  vertex "one"
}
"""


def _write(loops_dir, name, text=None):
    loops_dir.mkdir(parents=True, exist_ok=True)
    p = loops_dir / f"{name}.vertex"
    p.write_text(text or _VERTEX.format(name=name))
    return p


@pytest.fixture
def multi(tmp_path, monkeypatch):
    """cwd holding .loops/ with two instance vertices."""
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    loops_dir = tmp_path / ".loops"
    _write(loops_dir, "agent-attestation")
    project = _write(loops_dir, "project")
    monkeypatch.chdir(tmp_path)
    return project


@pytest.fixture
def single(tmp_path, monkeypatch):
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    loops_dir = tmp_path / ".loops"
    project = _write(loops_dir, "project")
    monkeypatch.chdir(tmp_path)
    return project


def _ctx(reporter=None, vertex_path=None):
    return Invocation(
        reporter=reporter or BufferReporter(),
        vertex_path=vertex_path,
        vertex_name=None if vertex_path is None else vertex_path.stem,
        observer="tester",
    )


class TestRefusal:
    def test_cite_refuses(self, multi):
        reporter = BufferReporter()
        rc = cite_view.run(["thread:some-arc", "-m", "x"], _ctx(reporter))
        assert rc == 2
        assert "refusing to guess" in reporter.err_text
        assert "agent-attestation" in reporter.err_text
        assert "project" in reporter.err_text
        assert "sl cite <vertex> REF ..." in reporter.err_text

    def test_read_refuses(self, multi):
        reporter = BufferReporter()
        rc = read_view.run([], _ctx(reporter))
        assert rc == 2
        assert "sl read <vertex> ..." in reporter.err_text

    def test_seal_refuses(self, multi):
        reporter = BufferReporter()
        rc = seal_view.run([], _ctx(reporter))
        assert rc == 2
        assert "sl seal <vertex>" in reporter.err_text

    def test_emit_refuses(self, multi, capsys):
        rc = _run_emit(["decision", "topic=t/x", "message=m"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refusing to guess" in captured.out + captured.err

    def test_no_store_written(self, multi, capsys):
        # The refusal must land BEFORE any store is opened or created.
        _run_emit(["decision", "topic=t/x", "message=m"])
        assert not list(multi.parent.glob("*.db"))

    def test_dotvertex_wins_outright(self, tmp_path, monkeypatch):
        # An explicit .loops/.vertex is the workspace-root convention — it is
        # the named choice, so siblings are not an ambiguity.
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        loops_dir = tmp_path / ".loops"
        _write(loops_dir, "agent-attestation")
        _write(loops_dir, "project")
        (loops_dir / ".vertex").write_text(_VERTEX.format(name="root"))
        monkeypatch.chdir(tmp_path)
        from loops.commands.resolve import ambiguous_local_vertex_refusal

        assert ambiguous_local_vertex_refusal("cite", "f") is None

    def test_aggregation_sibling_is_not_ambiguity(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        loops_dir = tmp_path / ".loops"
        _write(loops_dir, "one")
        _write(loops_dir, "all", _AGGREGATION)
        monkeypatch.chdir(tmp_path)
        from loops.commands.resolve import ambiguous_local_vertex_refusal

        assert ambiguous_local_vertex_refusal("cite", "f") is None


class TestSharedChokepoint:
    """Verbs that reach the local tier through ``resolve_local_vertex``.

    The first pass gated four call sites by hand and asserted these were
    "gated upstream at their own verbs" — wrong: sol reproduced a wrong-store
    write with `sl close thread x` (P1-b). The chokepoint now refuses by
    default and each verb translates the refusal.
    """

    def test_the_primitive_itself_refuses(self, multi):
        """sol P1-b round 2: gating callers left `_find_local_vertex` itself
        importable as a bypass. The refusal lives in the primitive now, so the
        default path is safe no matter who calls it."""
        from loops.commands.resolve import _find_local_vertex
        from loops.errors import AmbiguousLocalVertex

        with pytest.raises(AmbiguousLocalVertex):
            _find_local_vertex()

    def test_explicit_opt_out_still_picks(self, multi):
        """The declared escape works — and is the ONLY way past the refusal,
        which is what makes the Rule 9 enumeration meaningful."""
        from loops.commands.resolve import _find_local_vertex

        assert _find_local_vertex(allow_ambiguous=True) is not None

    @pytest.mark.parametrize("value", [1, "yes", [1], object()])
    def test_truthy_non_true_still_refuses(self, multi, value):
        """sol round 3: the runtime honored any truthy value while the ratchet
        recognized only a literal True — so `allow_ambiguous=1` opted out AND
        was recorded as safe. Only the literal opts out now, which is exactly
        what Rule 9 can see."""
        from loops.commands.resolve import _find_local_vertex
        from loops.errors import AmbiguousLocalVertex

        with pytest.raises(AmbiguousLocalVertex):
            _find_local_vertex(allow_ambiguous=value)

    def test_falsey_values_refuse_too(self, multi):
        from loops.commands.resolve import _find_local_vertex
        from loops.errors import AmbiguousLocalVertex

        for value in (False, 0, None, ""):
            with pytest.raises(AmbiguousLocalVertex):
                _find_local_vertex(allow_ambiguous=value)

    def test_resolve_local_vertex_raises(self, multi):
        from loops.commands.identity import resolve_local_vertex
        from loops.errors import AmbiguousLocalVertex

        with pytest.raises(AmbiguousLocalVertex) as exc:
            resolve_local_vertex()
        assert len(exc.value.candidates) == 2

    def test_close_refuses(self, multi, capsys):
        # sol's repro: `sl close thread x` wrote its resolution fact into
        # whichever store sorted first.
        from loops.commands.emit import _run_close

        rc = _run_close(["thread", "x"])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refusing to guess" in captured.out + captured.err
        assert not list(multi.parent.glob("*.db"))

    def test_facts_stream_refuses(self, multi, capsys):
        from loops.commands.stream import _run_stream

        rc = _run_stream([])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refusing to guess" in captured.out + captured.err

    def test_ticks_refuses(self, multi, capsys):
        from loops.commands.ticks import _run_ticks

        rc = _run_ticks([])
        assert rc == 2
        captured = capsys.readouterr()
        assert "refusing to guess" in captured.out + captured.err

    def test_orient_refuses(self, multi):
        from loops.cli.views import orient as orient_view

        reporter = BufferReporter()
        rc = orient_view.run([], _ctx(reporter))
        assert rc == 2
        assert "sl orient <vertex>" in reporter.err_text


class TestUnchangedPaths:
    def test_single_vertex_cite_still_resolves(self, single):
        # Seed the referent — since S4 a cite whose refs ALL drop refuses,
        # and this test's subject is vertex resolution, not ref semantics.
        assert _run_emit(["thread", "name=some-arc", "status=open"]) == 0
        reporter = BufferReporter()
        rc = cite_view.run(["thread:some-arc", "-m", "x", "--dry-run"], _ctx(reporter))
        assert rc == 0

    def test_single_vertex_read_still_folds(self, single):
        reporter = BufferReporter()
        assert read_view.run([], _ctx(reporter)) == 0

    def test_single_vertex_close_still_resolves(self, single):
        from loops.commands.identity import resolve_local_vertex

        assert resolve_local_vertex() == single

    def test_explicit_vertex_bypasses(self, multi):
        # Naming the vertex removes the ambiguity — the write lands.
        assert _run_emit(["project", "decision", "topic=t/x", "message=m"]) == 0

    def test_vertex_first_dispatch_bypasses(self, multi):
        # ctx.vertex_path set by vertex-first dispatch: never consults the tier.
        # Referent seeded — since S4 a cite whose refs ALL drop refuses.
        assert _run_emit(["project", "thread", "name=some-arc", "status=open"]) == 0
        reporter = BufferReporter()
        rc = cite_view.run(
            ["thread:some-arc", "-m", "x", "--dry-run"],
            _ctx(reporter, vertex_path=multi.resolve()),
        )
        assert rc == 0
