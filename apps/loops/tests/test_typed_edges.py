"""Typed-edges build-1 — read-time edge projection, overlay semantics, promotion.

Covers the settled design (decision:architecture/typed-edges-overlay-default):
declared edges are a READ-TIME projection of declared payload fields, OVERLAY
(last-set wins), retroactive (historical facts light up on declaration), and
walkable. Exercises the real KDL loader + engine fold + surface projection.
"""
from __future__ import annotations

import argparse

import pytest

from engine import vertex_fold
from loops.commands.fetch import fetch_fold
from loops.main import cmd_emit
from loops.surface import project, promotion_candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NO_EDGE = """\
name "t"
store "./t.db"
loops {
  person { fold { items "by" "handle" } }
  team { fold { items "by" "name" } }
  decision { fold { items "by" "topic" } }
  note { fold { items "collect" 100 } }
}
"""

_WITH_EDGE = """\
name "t"
store "./t.db"
loops {
  person { fold { items "by" "handle" } }
  team { fold { items "by" "name" } }
  decision {
    fold { items "by" "topic" }
    edge "stakeholder" targets="person"
  }
  note {
    fold { items "collect" 100 }
    edge "about" targets="person"
  }
}
"""


def _write(path, text):
    path.write_text(text)


def _emit(vpath, kind, **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer="", dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _item(state, kind, key):
    for section in state.sections:
        if section.kind != kind:
            continue
        for it in section.items:
            if str(it.payload.get(section.key_field)) == key:
                return it
    return None


@pytest.fixture
def vpath(tmp_path):
    p = tmp_path / "t.vertex"
    _write(p, _WITH_EDGE)
    return p


# ---------------------------------------------------------------------------
# Declared-edge projection (upsert + collect)
# ---------------------------------------------------------------------------

def test_edge_lifted_on_upsert_kind(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    state = vertex_fold(vpath)
    dec = _item(state, "decision", "design/foo")
    assert [(e.predicate, e.address) for e in dec.edges] == [
        ("stakeholder", "person:acme"),
    ]


def test_edge_lifted_on_collect_kind(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "note", message="hi", about="acme")
    state = vertex_fold(vpath)
    note = next(
        it for s in state.sections if s.kind == "note" for it in s.items
    )
    assert [(e.predicate, e.address) for e in note.edges] == [
        ("about", "person:acme"),
    ]


def test_bare_key_normalized_and_counts_inbound(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    surface = project(vertex_fold(vpath))
    person_row = next(r for r in surface.rows if r.kind == "person")
    # bare `stakeholder=acme` normalized to person:acme → inbound on acme
    assert person_row.inbound == 1
    assert person_row.inbound_predicates == (("stakeholder", 1),)


def test_edge_walkable(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    # Walk from the decision through the typed edge should reach the person.
    state = fetch_fold(vpath, kind="decision", key="design/foo", refs_depth=1)
    walked_kinds = {w.section_kind for w in state.walked}
    assert "person" in walked_kinds


# ---------------------------------------------------------------------------
# Retroactivity — declare the edge AFTER the facts exist
# ---------------------------------------------------------------------------

def test_retroactive_declaration(tmp_path):
    p = tmp_path / "t.vertex"
    _write(p, _NO_EDGE)
    _emit(p, "person", handle="acme", name="Acme")
    _emit(p, "decision", topic="design/foo", stakeholder="acme", message="x")

    # Before declaration: stakeholder is inert (no edge, no inbound).
    before = project(vertex_fold(p))
    person_before = next(r for r in before.rows if r.kind == "person")
    assert person_before.inbound == 0
    dec_before = _item(vertex_fold(p), "decision", "design/foo")
    assert dec_before.edges == ()

    # Declare the edge — no re-emit — historical fact lights up.
    _write(p, _WITH_EDGE)
    after = project(vertex_fold(p))
    person_after = next(r for r in after.rows if r.kind == "person")
    assert person_after.inbound == 1
    assert person_after.inbound_predicates == (("stakeholder", 1),)


# ---------------------------------------------------------------------------
# Overlay correction — re-emit changes the edge target
# ---------------------------------------------------------------------------

def test_overlay_correction_moves_inbound(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "person", handle="globex", name="Globex")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    _emit(vpath, "decision", topic="design/foo", stakeholder="globex")

    surface = project(vertex_fold(vpath))
    acme = next(r for r in surface.rows if r.key == "acme")
    globex = next(r for r in surface.rows if r.key == "globex")
    # Last-set wins: acme loses the inbound edge, globex gains it.
    assert acme.inbound == 0
    assert globex.inbound == 1


def test_sentinel_clear_removes_edge(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    # Explicit clear sentinel — stakeholder= empties the field.
    _emit(vpath, "decision", topic="design/foo", stakeholder="")

    state = vertex_fold(vpath)
    dec = _item(state, "decision", "design/foo")
    assert dec.edges == ()
    surface = project(state)
    acme = next(r for r in surface.rows if r.key == "acme")
    assert acme.inbound == 0


# ---------------------------------------------------------------------------
# Comma multi-value overlay (set literal replaced atomically)
# ---------------------------------------------------------------------------

def test_comma_multi_value_edges(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "person", handle="globex", name="Globex")
    _emit(
        vpath, "decision", topic="design/foo",
        stakeholder="acme,globex", message="x",
    )
    state = vertex_fold(vpath)
    dec = _item(state, "decision", "design/foo")
    assert {e.address for e in dec.edges} == {"person:acme", "person:globex"}
    surface = project(state)
    for handle in ("acme", "globex"):
        row = next(r for r in surface.rows if r.key == handle)
        assert row.inbound == 1


def test_comma_replace_is_atomic(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "person", handle="globex", name="Globex")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme,globex", message="x")
    # Re-emit with a single value — the set is replaced, not unioned.
    _emit(vpath, "decision", topic="design/foo", stakeholder="globex")
    state = vertex_fold(vpath)
    dec = _item(state, "decision", "design/foo")
    assert {e.address for e in dec.edges} == {"person:globex"}


# ---------------------------------------------------------------------------
# Promotion candidates
# ---------------------------------------------------------------------------

def test_promotion_candidate_surfaces_undeclared_field(tmp_path):
    p = tmp_path / "t.vertex"
    _write(p, _NO_EDGE)  # no edges declared
    _emit(p, "person", handle="acme", name="Acme")
    for topic in ("a", "b", "c"):
        _emit(p, "decision", topic=topic, stakeholder="person:acme", message="x")

    cands = promotion_candidates(vertex_fold(p), min_facts=3)
    fields = {c.field for c in cands}
    assert "stakeholder" in fields
    c = next(c for c in cands if c.field == "stakeholder")
    assert c.count == 3
    assert c.target_kinds == ("person",)
    assert c.source_kinds == ("decision",)


def test_declared_edge_not_a_promotion_candidate(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    for topic in ("a", "b", "c"):
        _emit(vpath, "decision", topic=topic, stakeholder="person:acme", message="x")
    # stakeholder is DECLARED as an edge → excluded from candidates.
    cands = promotion_candidates(vertex_fold(vpath), min_facts=3)
    assert "stakeholder" not in {c.field for c in cands}


def test_promotion_below_threshold_excluded(tmp_path):
    p = tmp_path / "t.vertex"
    _write(p, _NO_EDGE)
    _emit(p, "person", handle="acme", name="Acme")
    _emit(p, "decision", topic="a", stakeholder="person:acme", message="x")
    # Only one fact carries it → below the default min_facts=3.
    assert promotion_candidates(vertex_fold(p), min_facts=3) == []


# ---------------------------------------------------------------------------
# Predicate-labeled render — TTY / piped parity
# ---------------------------------------------------------------------------

def _render(state, *, width):
    from painted import Zoom
    from loops.lenses.fold import fold_view
    block = fold_view(state, Zoom.DETAILED, width, visible=frozenset({"refs"}))
    return "\n".join(
        "".join(c.char for c in row).rstrip() for row in block._rows
    )


def test_predicate_label_render_tty_and_piped(vpath):
    _emit(vpath, "person", handle="acme", name="Acme")
    _emit(vpath, "decision", topic="design/foo", stakeholder="acme", message="x")
    state = vertex_fold(vpath)

    tty = _render(state, width=200)
    piped = _render(state, width=None)
    for text in (tty, piped):
        # inbound predicate breakdown + labeled edge expansion + outbound edge
        assert "via stakeholder" in text
        assert "← decision/design/foo via stakeholder" in text
        assert "→ person:acme via stakeholder" in text


def test_receipt_wording_edge_vs_pin(tmp_path, capsys):
    p = tmp_path / "t.vertex"
    _write(p, _WITH_EDGE)
    _emit(p, "person", handle="acme", name="Acme")
    _emit(p, "decision", topic="design/existing", message="prior")
    capsys.readouterr()
    # Declared edge field → "inbound edge via"; undeclared address field → pin.
    ns = argparse.Namespace(
        vertex=None, kind="decision",
        parts=["topic=design/foo", "stakeholder=person:acme",
               "blocks=decision:design/existing", "message=x"],
        observer="", dry_run=False, verbose=1,
    )
    cmd_emit(ns, vertex_path=p)
    err = capsys.readouterr().err
    assert "inbound edge via stakeholder: person:acme" in err
    assert "pinned blocks_ref" in err
