"""S4 (cli-honesty-wave): verb-first ``sl cite`` gains a vertex slot.

Contract (design/implementation/cli-honesty-wave, S4):
  * ``sl cite <vertex> REF...`` targets the named vertex — parity with
    emit's verb-first grammar (``sl <cmd> <vertex-if-required>``).
  * The first positional is the vertex ONLY when it resolves as one
    (``_resolve_vertex_for_dispatch``); emit's bare-"/" heuristic is NOT
    copied because a legacy slash-form ref (``thread/arc-name``) is a
    legal cite positional.
  * A named vertex bypasses the ambiguous-local-vertex refusal; the
    no-vertex form keeps emit-parity local resolution (.loops/-aware,
    refuses on ambiguity).
  * A cite whose refs ALL drop is an ERROR (nonzero, stderr, nothing
    stored) — not a WARN + empty attention signal. Partial drops keep
    the WARN + typed-pin behavior.

Driving friction: friction:cite-verb-first-lacks-vertex-slot.
"""
import argparse

import pytest

from engine import StoreReader

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import cite as cite_view
from loops.commands.emit import cmd_emit


_VERTEX_TMPL = """\
name "{name}"
store "./{name}.db"

loops {{
  thread {{ fold {{ items "by" "name" }} }}
  cite {{ fold {{ items "collect" 0 }} }}
}}
"""


def _write_vertex(dirpath, name):
    p = dirpath / f"{name}.vertex"
    p.write_text(_VERTEX_TMPL.format(name=name))
    return p


def _ctx(vertex_path=None, vertex_name=None):
    return Invocation(
        reporter=BufferReporter(),
        vertex_path=vertex_path,
        vertex_name=vertex_name,
        observer="tester",
    )


def _seed_thread(vpath, name):
    ns = argparse.Namespace(
        vertex=None, kind="thread",
        parts=[f"name={name}", "status=open", "message=referent"],
        observer="tester", dry_run=False,
    )
    assert cmd_emit(ns, vertex_path=vpath) == 0


def _cite_facts(vpath):
    store = vpath.parent / f"{vpath.stem}.db"
    if not store.exists():
        return []  # nothing was ever stored — no store materialized
    with StoreReader(store) as reader:
        return reader.facts_by_kind("cite")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    # Isolate LOOPS_HOME (no config-level vertices) and run from tmp_path.
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestVertexSlot:
    def test_cite_lands_in_named_vertex(self, sandbox):
        vpath = _write_vertex(sandbox, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["t", "thread:arc"], ctx) == 0
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None

    def test_vertex_named_but_no_refs_errors(self, sandbox):
        _write_vertex(sandbox, "t")
        ctx = _ctx()
        assert cite_view.run(["t"], ctx) == 2
        assert any("requires at least one ref" in l for l in ctx.reporter.err_lines)

    def test_named_vertex_bypasses_ambiguity_refusal(self, sandbox):
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        a = _write_vertex(loops_dir, "a")
        _write_vertex(loops_dir, "b")
        _seed_thread(a, "arc")
        ctx = _ctx()
        assert cite_view.run(["a", "thread:arc"], ctx) == 0
        assert len(_cite_facts(a)) == 1

    def test_no_vertex_with_ambiguous_local_refuses(self, sandbox):
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        a = _write_vertex(loops_dir, "a")
        _write_vertex(loops_dir, "b")
        _seed_thread(a, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 2
        assert any("refusing to guess" in l for l in ctx.reporter.err_lines)
        assert _cite_facts(a) == []

    def test_no_vertex_resolves_dot_loops_local(self, sandbox):
        # Emit-parity backward compatibility: the no-vertex form resolves
        # the local vertex .loops/-first, same as emit's no-vertex path.
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        vpath = _write_vertex(loops_dir, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 0
        assert len(_cite_facts(vpath)) == 1

    def test_no_vertex_no_local_errors(self, sandbox):
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 1
        assert any("no local vertex found" in l for l in ctx.reporter.err_lines)

    def test_vertex_first_dispatch_does_not_peel(self, sandbox):
        # With ctx.vertex_path already resolved (sl <vertex> cite ...), the
        # first positional is a REF even when it happens to resolve as a
        # vertex name — no peel runs.
        vpath = _write_vertex(sandbox, "t")
        decoy = _write_vertex(sandbox, "decoy")
        _seed_thread(vpath, "arc")
        ctx = _ctx(vertex_path=vpath.resolve(), vertex_name="t")
        # "decoy" resolves as a vertex name, but vertex-first dispatch already
        # fixed the vertex — so it must stay a (inert, non-address) ref and
        # the cite must land in t, never in decoy.
        rc = cite_view.run(["decoy", "thread:arc"], ctx)
        assert rc == 0
        assert len(_cite_facts(vpath)) == 1
        assert _cite_facts(decoy) == []

    def test_legacy_slash_ref_not_mistaken_for_vertex(self, sandbox):
        # A slash-form ref must stay a ref (emit's bare-"/" vertex rule is
        # deliberately not copied): thread/arc resolves against the local
        # vertex, not as a vertex named "thread/arc".
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        vpath = _write_vertex(loops_dir, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread/arc"], ctx) == 0
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None


class TestAllRefsDropError:
    def test_all_refs_drop_errors_and_stores_nothing(self, sandbox, capsys):
        vpath = _write_vertex(sandbox, "t")
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent"], ctx)
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "thread:absent" in err
        assert _cite_facts(vpath) == []

    def test_all_refs_drop_dry_run_also_refuses(self, sandbox, capsys):
        vpath = _write_vertex(sandbox, "t")
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent", "--dry-run"], ctx)
        assert rc == 2
        assert "ERROR" in capsys.readouterr().err
        assert _cite_facts(vpath) == []

    def test_partial_drop_stores_with_warning(self, sandbox, capsys):
        vpath = _write_vertex(sandbox, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:arc", "thread:absent"], ctx)
        assert rc == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "thread:absent" in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None

    def test_emit_path_gets_same_refusal(self, sandbox, capsys):
        # The refusal is kind-level (lives in cmd_emit), so the raw emit
        # spelling of a cite refuses identically.
        vpath = _write_vertex(sandbox, "t")
        ns = argparse.Namespace(
            vertex=None, kind="cite", parts=["ref=thread:absent"],
            observer="tester", dry_run=False,
        )
        assert cmd_emit(ns, vertex_path=vpath) == 2
        assert "ERROR" in capsys.readouterr().err
        assert _cite_facts(vpath) == []
