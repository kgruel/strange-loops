"""F3 regression: ``sl cite`` positional refs and ``sl emit ... cite ref=``
must resolve IDENTICALLY for identical input (same vertex, same address).

Diagnosis (this session): the reported divergence — ``cite thread:X`` storing an
unresolved pin while ``emit project cite ref=thread:X`` resolved it — was NOT an
address-parsing difference. Both verbs route through the SAME
``_resolve_entity_refs`` → ``atoms.Address`` path and, for identical input,
resolve identically. The specimen compared *verb-first* ``sl cite`` (which
resolves ``_find_local_vertex()`` — the alphabetically-first ``.vertex`` in
``.loops/``) against *vertex-first* ``sl emit project cite`` (the explicitly
named ``project``): two DIFFERENT vertices, hence two different stores. The
divergence was vertex selection, not ref resolution.

These tests pin the real contract: given ONE resolved vertex context, the cite
view and the emit view resolve the same address to the same ULID (or the same
typed unresolved pin). Covers the canonical colon form, the legacy ``kind/key``
slash form, and the exact failing specimen shape (a long hyphenated key).
"""
import argparse

import pytest

from engine import StoreReader

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import cite as cite_view
from loops.cli.views import emit as emit_view
from loops.commands.emit import cmd_emit


_VERTEX = """\
name "t"
store "./t.db"

loops {
  thread { fold { items "by" "name" } }
  cite { fold { items "collect" 0 } }
}
"""


@pytest.fixture
def vpath(tmp_path, monkeypatch):
    # Isolate LOOPS_HOME so topology widening can't reach the real config.
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    p = tmp_path / "t.vertex"
    p.write_text(_VERTEX)
    return p


def _ctx(vpath):
    return Invocation(
        reporter=BufferReporter(),
        vertex_path=vpath.resolve(),
        vertex_name="t",
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
    store = vpath.parent / "t.db"
    if not store.exists():
        return []  # nothing was ever stored — no store materialized
    with StoreReader(store) as reader:
        return reader.facts_by_kind("cite")


def _resolution(payload):
    """The ref-resolution slice of a cite payload — what parity compares."""
    return (
        payload.get("ref"),
        payload.get("ref_ref"),
        payload.get("_unresolved_refs"),
    )


def _run_both(vpath, ref):
    """Drive the cite view (positional) and the emit view (ref=) against the
    SAME vertex context; return their two stored cite payloads' resolutions."""
    ctx = _ctx(vpath)
    assert cite_view.run([ref], ctx) == 0
    assert emit_view.run(["cite", f"ref={ref}"], ctx) == 0
    facts = _cite_facts(vpath)
    assert len(facts) == 2, facts
    return _resolution(facts[0]["payload"]), _resolution(facts[1]["payload"])


class TestResolvedRefParity:
    def test_colon_form_resolves_identically(self, vpath):
        _seed_thread(vpath, "arc-name")
        cite_res, emit_res = _run_both(vpath, "thread:arc-name")
        assert cite_res == emit_res
        # Both actually resolved (ref_ref is the pinned ULID, no unresolved pin).
        assert cite_res[1] is not None and cite_res[2] is None

    def test_legacy_slash_form_resolves_identically(self, vpath):
        _seed_thread(vpath, "arc-name")
        cite_res, emit_res = _run_both(vpath, "thread/arc-name")
        assert cite_res == emit_res
        assert cite_res[1] is not None and cite_res[2] is None

    def test_specimen_shape_resolves_identically(self, vpath):
        # The exact failing specimen shape: a long hyphenated key.
        _seed_thread(vpath, "090-consumer-evidence-wave")
        cite_res, emit_res = _run_both(vpath, "thread:090-consumer-evidence-wave")
        assert cite_res == emit_res
        assert cite_res[1] is not None and cite_res[2] is None


class TestUnresolvedRefParity:
    def test_all_refs_dropped_refuses_identically(self, vpath):
        # No matching thread seeded → ALL refs drop. Since S4 a cite whose
        # refs all drop is an ERROR (empty attention signal), not a stored
        # pin — and parity means BOTH views refuse identically: nonzero
        # exit, nothing stored.
        ctx = _ctx(vpath)
        assert cite_view.run(["thread:absent-thread"], ctx) != 0
        assert emit_view.run(["cite", "ref=thread:absent-thread"], ctx) != 0
        assert _cite_facts(vpath) == []

    def test_partial_drop_pins_identically(self, vpath):
        # One resolvable + one absent ref → stored (partial information is
        # still information), with the SAME typed pin from both views.
        _seed_thread(vpath, "arc-name")
        ctx = _ctx(vpath)
        assert cite_view.run(["thread:arc-name", "thread:absent-thread"], ctx) == 0
        assert emit_view.run(
            ["cite", "ref=thread:arc-name", "ref=thread:absent-thread"], ctx
        ) == 0
        facts = _cite_facts(vpath)
        assert len(facts) == 2, facts
        cite_res = _resolution(facts[0]["payload"])
        emit_res = _resolution(facts[1]["payload"])
        assert cite_res == emit_res
        assert cite_res[1] is not None  # the resolvable ref resolved
        assert cite_res[2] == [
            {
                "field": "ref",
                "addr": "thread:absent-thread",
                "kind": "thread",
                "key": "absent-thread",
            }
        ]
