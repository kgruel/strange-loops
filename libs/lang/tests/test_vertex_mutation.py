"""Tests for the public vertex-kind mutation API (lang.vertex_mutation).

Covers:
- loop_def_to_kdl serializer: reparse-equivalence for every supported
  declarative feature (fold/boundary/search/preview/edge/lifecycle), plus
  rejection of unrepresentable input. Per-kind parse pipelines are OUTSIDE
  the serializer's domain by contract — it refuses them (see the
  production module docstring).
- add/edit/remove_vertex_kind: absent, single-line, and multiline loops
  blocks; validation-before-return; preservation of unrelated content.
- Corpus oracle: add-then-remove is byte-identical to the original for
  every in-repo .vertex with a multiline loops block; serializer output
  reparses to an equivalent LoopDef for every kind in the corpus.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang import (
    add_vertex_kind,
    edit_vertex_kind,
    loop_def_to_kdl,
    parse_vertex,
    remove_vertex_kind,
)
from lang.ast import (
    BoundaryAfter,
    BoundaryCondition,
    BoundaryEvery,
    BoundaryWhen,
    EdgeDecl,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
    LifecycleDecl,
    LoopDef,
    Split,
)
from lang.population import kdl_find_block

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reparse_def(kind: str, definition: LoopDef) -> LoopDef:
    """Serializer output wrapped in a minimal vertex, reparsed."""
    text = 'name "t"\nloops {\n'
    text += "\n".join(
        "  " + ln for ln in loop_def_to_kdl(kind, definition).splitlines()
    )
    text += "\n}\n"
    vf = parse_vertex(text)
    assert kind in vf.loops
    return vf.loops[kind]


BASIC = LoopDef(folds=(FoldDecl(target="items", op=FoldBy(key_field="topic")),))


# ---------------------------------------------------------------------------
# Serializer — reparse equivalence
# ---------------------------------------------------------------------------


class TestSerializer:
    def test_all_fold_ops_roundtrip(self):
        d = LoopDef(
            folds=(
                FoldDecl("items", FoldBy(key_field="topic")),
                FoldDecl("n", FoldCount()),
                FoldDecl("last", FoldLatest()),
                FoldDecl("total", FoldSum(field="amount")),
                FoldDecl("hi", FoldMax(field="value")),
                FoldDecl("lo", FoldMin(field="value")),
                FoldDecl("mean", FoldAvg(field="value")),
                FoldDecl("recent", FoldCollect(max_items=50)),
                FoldDecl("buf", FoldWindow(field="value", size=5)),
            )
        )
        assert _reparse_def("metrics", d) == d

    def test_boundary_when_with_match_conditions_run(self):
        d = LoopDef(
            folds=BASIC.folds,
            boundary=BoundaryWhen(
                kind="session",
                match=(("status", "closed"), ("mode", "full")),
                conditions=(
                    BoundaryCondition(target="high", op=">=", value=80.0),
                    BoundaryCondition(target="state", op="==", value=2.5),
                ),
                run="scripts/dispatch.sh",
            ),
        )
        assert _reparse_def("session", d) == d

    def test_boundary_after_and_every(self):
        for b in (BoundaryAfter(count=5), BoundaryEvery(count=10, run="do.sh")):
            d = LoopDef(folds=BASIC.folds, boundary=b)
            assert _reparse_def("k", d) == d

    def test_search_preview_edges_lifecycle(self):
        d = LoopDef(
            folds=BASIC.folds,
            search=("message", "topic"),
            preview_fields=("status", "message"),
            edges=(EdgeDecl(field="stakeholder", target="person"),),
            lifecycle=LifecycleDecl(field="status", active=("open", "in-progress")),
        )
        assert _reparse_def("thread", d) == d

    def test_empty_def(self):
        d = LoopDef(folds=())
        assert _reparse_def("bare", d) == d

    def test_string_escaping_in_values(self):
        d = LoopDef(
            folds=(FoldDecl("items", FoldBy(key_field='we"ird\\key')),)
        )
        assert _reparse_def("k", d) == d

    def test_rejects_parse_pipeline(self):
        d = LoopDef(folds=BASIC.folds, parse=(Split(),))
        with pytest.raises(ValueError, match="parse pipelines"):
            loop_def_to_kdl("k", d)

    def test_parse_pipeline_refusal_is_the_documented_contract(self):
        """SOL-R1-05 (arbiter ruling: narrow the claim, not the serializer).

        The serializer's supported domain is the declarative kind surface
        — fold/boundary/search/preview/edge/lifecycle. Per-kind parse
        pipelines are OUTSIDE that domain by contract (zero corpus usage);
        the refusal must name the narrowed contract, and no full-LoopDef
        round-trip is claimed.
        """
        d = LoopDef(folds=BASIC.folds, parse=(Split(),))
        with pytest.raises(
            ValueError,
            match=r"declarative kind surface.*outside its supported domain",
        ):
            loop_def_to_kdl("k", d)
        # The docstring states the domain and disclaims full round-trip.
        doc = loop_def_to_kdl.__doc__
        assert "fold" in doc and "lifecycle" in doc
        assert "no full-LoopDef" in doc.replace("\n", " ").replace("    ", " ")

    def test_rejects_control_chars_in_values(self):
        d = LoopDef(folds=(FoldDecl("items", FoldBy(key_field="a\nb")),))
        with pytest.raises(ValueError, match="control characters"):
            loop_def_to_kdl("k", d)

    def test_rejects_comma_in_lifecycle_active(self):
        d = LoopDef(
            folds=BASIC.folds,
            lifecycle=LifecycleDecl(field="status", active=("a,b",)),
        )
        with pytest.raises(ValueError, match="lifecycle active"):
            loop_def_to_kdl("k", d)

    @pytest.mark.parametrize(
        "bad", ["", "has space", 'quo"te', "1leading", "-lead", "boundary", "a{b"]
    )
    def test_rejects_unsafe_kind_names(self, bad):
        with pytest.raises(ValueError):
            loop_def_to_kdl(bad, BASIC)


# ---------------------------------------------------------------------------
# add / edit / remove
# ---------------------------------------------------------------------------

MULTI = (
    'name "test"\n'
    "// header comment\n"
    "loops {\n"
    "  // decisions matter\n"
    '  decision { fold { items "by" "topic" } }\n'
    "}\n"
    'store "./data/test.db"\n'
)


class TestAddVertexKind:
    def test_add_into_multiline_block(self):
        out = add_vertex_kind(MULTI, "task", LoopDef(folds=(FoldDecl("items", FoldBy("name")),)))
        vf = parse_vertex(out)
        assert set(vf.loops) == {"decision", "task"}
        # Unrelated content preserved.
        assert "// header comment" in out
        assert "// decisions matter" in out
        assert 'store "./data/test.db"' in out

    def test_add_creates_absent_loops_block(self):
        text = 'name "agg"\ndiscover "./instances/**/*.vertex"\n'
        out = add_vertex_kind(text, "disk", BASIC)
        vf = parse_vertex(out)
        assert "disk" in vf.loops
        assert 'discover "./instances/**/*.vertex"' in out
        start, end = kdl_find_block(out, ["loops"])
        assert end > start  # created multiline

    def test_add_expands_single_line_block(self):
        text = 'name "t"\nloops { decision { fold { items "by" "topic" } } }\n'
        out = add_vertex_kind(text, "task", BASIC)
        vf = parse_vertex(out)
        assert set(vf.loops) == {"decision", "task"}

    def test_add_expansion_splits_every_sibling_onto_its_own_line(self):
        # SOL-R1-01 root cause: expansion must not leave siblings sharing
        # one physical line — later line-based edit/remove of one would
        # silently delete the rest.
        text = (
            'name "t"\n'
            'loops { decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } } }\n'
        )
        out = add_vertex_kind(text, "marker", BASIC)
        assert set(parse_vertex(out).loops) == {"decision", "task", "marker"}
        loops_body = out[out.index("loops {") :]
        # Each kind opens on its own physical line.
        for kind in ("decision", "task", "marker"):
            opening_lines = [
                ln for ln in loops_body.splitlines()
                if ln.strip().startswith(kind)
            ]
            assert len(opening_lines) == 1, kind
        # No line carries two kind declarations.
        for ln in loops_body.splitlines():
            assert not ("decision" in ln and "task" in ln), ln

    def test_add_then_edit_then_remove_preserves_unrelated_kinds(self):
        # SOL-R1-01 regression: the full add -> edit -> remove sequence on
        # a multi-child single-line block must never lose unrelated kinds.
        text = (
            'name "t"\n'
            'loops { decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } } }\n'
        )
        out = add_vertex_kind(text, "marker", BASIC)
        out = edit_vertex_kind(
            out,
            "decision",
            LoopDef(
                folds=(FoldDecl("items", FoldBy("topic")),),
                search=("message",),
            ),
        )
        assert set(parse_vertex(out).loops) == {"decision", "task", "marker"}
        out = remove_vertex_kind(out, "decision")
        assert set(parse_vertex(out).loops) == {"task", "marker"}

    def test_add_duplicate_refuses(self):
        with pytest.raises(ValueError, match="already exists"):
            add_vertex_kind(MULTI, "decision", BASIC)

    def test_result_validates(self):
        # A serializable-but-invalid def: duplicate fold targets parse fine
        # but the validator rejects them — so the mutation must refuse.
        d = LoopDef(
            folds=(
                FoldDecl("items", FoldBy("topic")),
                FoldDecl("items", FoldCount()),
            )
        )
        with pytest.raises(ValueError, match="invalid vertex"):
            add_vertex_kind(MULTI, "bad", d)


class TestEditVertexKind:
    def test_edit_in_place_preserves_position_and_context(self):
        new = LoopDef(
            folds=(FoldDecl("items", FoldBy("topic")),),
            search=("message",),
        )
        out = edit_vertex_kind(MULTI, "decision", new)
        vf = parse_vertex(out)
        assert vf.loops["decision"] == new
        assert "// decisions matter" in out
        # decision block still precedes the store line
        assert out.index("decision") < out.index('store "')

    def test_edit_missing_kind_raises(self):
        with pytest.raises(ValueError, match="not found"):
            edit_vertex_kind(MULTI, "ghost", BASIC)

    def test_edit_kind_sharing_a_line_with_siblings_fails_loud(self):
        # SOL-R1-01 fail-loud guard: hand-authored shared line — editing
        # the first kind must refuse, not silently delete its siblings.
        text = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="sibling"):
            edit_vertex_kind(text, "decision", BASIC)

    def test_edit_single_line_loops_block_unsupported(self):
        text = 'name "t"\nloops { decision { fold { items "by" "topic" } } }\n'
        with pytest.raises(ValueError, match="single-line"):
            edit_vertex_kind(text, "decision", BASIC)


class TestRemoveVertexKind:
    def test_remove_kind(self):
        text = add_vertex_kind(MULTI, "task", BASIC)
        out = remove_vertex_kind(text, "task")
        assert out == MULTI  # byte-identical round trip

    def test_remove_missing_kind_raises(self):
        with pytest.raises(ValueError, match="not found"):
            remove_vertex_kind(MULTI, "ghost")

    def test_remove_last_kind_of_loops_only_vertex_refuses(self):
        with pytest.raises(ValueError, match="invalid vertex"):
            remove_vertex_kind(MULTI, "decision")

    def test_remove_kind_sharing_a_line_with_siblings_fails_loud(self):
        # SOL-R1-01 fail-loud property, now held by the parser oracle alone
        # (simplify item 5 — the lexical pre-guard dissolved): removal of a
        # kind whose physical line carries siblings must refuse, not take
        # the siblings with it. Here the splice mangles the text and the
        # post-mutation parse/verify refuses; the original text stands.
        text = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="invalid vertex|preservation"):
            remove_vertex_kind(text, "decision")

    def test_remove_single_line_loops_block_unsupported(self):
        # `decision { } task { }` without a `;` is not valid KDL — since the
        # SOL-R2-01 parser-oracle change, the pre-mutation parse refuses it
        # up front (previously the splice layer's single-line refusal fired).
        text = 'name "t"\nloops { decision { } task { } }\n'
        with pytest.raises(ValueError, match="not a parseable vertex"):
            remove_vertex_kind(text, "decision")
        # The parseable single-line form still refuses without kind loss.
        text = 'name "t"\nloops { decision { }; task { } }\n'
        with pytest.raises(ValueError, match="sibling|single-line"):
            remove_vertex_kind(text, "decision")


# ---------------------------------------------------------------------------
# Corpus oracle
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _corpus_files() -> list[Path]:
    out: list[Path] = []
    for p in _REPO_ROOT.rglob("*.vertex"):
        if any(part.startswith(".git") for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


_MARKER_DEF = LoopDef(folds=(FoldDecl("items", FoldBy("name")),))


@pytest.mark.parametrize(
    "vertex_file",
    _corpus_files(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_corpus_add_remove_roundtrip(vertex_file: Path):
    """add_vertex_kind then remove_vertex_kind over every in-repo .vertex.

    Multiline loops block: byte-identical. Single-line or absent loops
    block: expand-on-insert / block creation is one-way — assert semantic
    equivalence instead.
    """
    original = vertex_file.read_text()
    kind = "__s6_rt_marker__"
    assert kind not in parse_vertex(original).loops

    added = add_vertex_kind(original, kind, _MARKER_DEF)
    vf_added = parse_vertex(added)
    assert vf_added.loops[kind] == _MARKER_DEF

    try:
        start, end = kdl_find_block(original, ["loops"])
        multiline = end > start
    except ValueError:
        multiline = False  # loops block absent — created by add

    if not multiline:
        # One-way expansion/creation: removal must still be semantically
        # clean when validation permits it; otherwise the refusal itself is
        # the contract.
        try:
            removed = remove_vertex_kind(added, kind)
        except ValueError:
            return
        assert set(parse_vertex(removed).loops) == set(parse_vertex(original).loops)
        return

    removed = remove_vertex_kind(added, kind)
    assert removed == original, f"round-trip mismatch on {vertex_file}"


@pytest.mark.parametrize(
    "vertex_file",
    _corpus_files(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_corpus_serializer_reparse_equivalence(vertex_file: Path):
    """loop_def_to_kdl output reparses to an equivalent LoopDef for every
    kind definition in the corpus."""
    vf = parse_vertex(vertex_file.read_text())
    if not vf.loops:
        pytest.skip(f"{vertex_file.name}: no loop kinds")
    for kind, definition in vf.loops.items():
        assert _reparse_def(kind, definition) == definition, (
            f"serializer inequivalence for {kind} in {vertex_file}"
        )


# ---------------------------------------------------------------------------
# Parser-as-oracle postcondition (SOL-R2-01) — lexical evasion classes
# ---------------------------------------------------------------------------

RAW_STRING_DOC = (
    'name "t"\n'
    'loops { decision { boundary after=1 { '
    'run ##"echo "quoted"; } { "# still raw"## } }; '
    'task { fold { items "by" "name" } } }\n'
)
ESCAPED_QUOTE_DOC = (
    'name "t"\n'
    'loops { decision { boundary when="x\\"; } { y" }; '
    'task { fold { items "by" "name" } } }\n'
)


class TestParserOraclePostcondition:
    """No lexical evasion class may silently lose a kind (SOL-R2-01).

    Contract (arbiter ruling): every mutation either succeeds with FULL
    preservation of all untouched kinds (definition-equal under reparse) or
    refuses with ValueError, leaving the caller's original text as the only
    text. The lexical splice layer carries no safety claim — the parser is
    the oracle.
    """

    @staticmethod
    def _assert_preserved_or_refused(op, before_text, expected_kinds):
        before = parse_vertex(before_text)
        try:
            out = op(before_text)
        except ValueError:
            return  # clean refusal — the original text stands
        after = parse_vertex(out)
        assert set(after.loops) == expected_kinds
        for k in (set(before.loops) & expected_kinds) - {"decision"}:
            assert after.loops[k] == before.loops[k], k

    def test_raw_string_doc_parses_with_both_kinds(self):
        assert set(parse_vertex(RAW_STRING_DOC).loops) == {"decision", "task"}

    @pytest.mark.parametrize("doc", [RAW_STRING_DOC, ESCAPED_QUOTE_DOC])
    def test_add_never_loses_a_kind(self, doc):
        self._assert_preserved_or_refused(
            lambda t: add_vertex_kind(t, "marker", BASIC),
            doc,
            {"decision", "task", "marker"},
        )

    @pytest.mark.parametrize("doc", [RAW_STRING_DOC, ESCAPED_QUOTE_DOC])
    def test_edit_never_loses_a_sibling(self, doc):
        # Sol's R2 repro: edit of `decision` silently deleted `task`.
        self._assert_preserved_or_refused(
            lambda t: edit_vertex_kind(t, "decision", BASIC),
            doc,
            {"decision", "task"},
        )

    @pytest.mark.parametrize("doc", [RAW_STRING_DOC, ESCAPED_QUOTE_DOC])
    def test_remove_never_loses_a_sibling(self, doc):
        # Sol's R2 repro: remove of `decision` also removed `task`.
        self._assert_preserved_or_refused(
            lambda t: remove_vertex_kind(t, "decision"),
            doc,
            {"task"},
        )

    @pytest.mark.parametrize("doc", [RAW_STRING_DOC, ESCAPED_QUOTE_DOC])
    def test_full_sequence_never_loses_task(self, doc):
        # add -> edit -> remove; any step may refuse, none may lose `task`.
        text = doc
        for step in (
            lambda t: add_vertex_kind(t, "marker", BASIC),
            lambda t: edit_vertex_kind(t, "decision", BASIC),
            lambda t: remove_vertex_kind(t, "decision"),
        ):
            try:
                text = step(text)
            except ValueError:
                break
        assert "task" in parse_vertex(text).loops

    def test_comment_on_shared_line_never_loses_a_sibling(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } } // trailing } { note\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        self._assert_preserved_or_refused(
            lambda t: remove_vertex_kind(t, "decision"), doc, {"task"}
        )
        self._assert_preserved_or_refused(
            lambda t: edit_vertex_kind(t, "decision", BASIC),
            doc,
            {"decision", "task"},
        )

    def test_single_line_expansion_preserves_trailing_comment(self):
        # SOL-R2-05: expansion of a single-line loops block must keep the
        # complete suffix after the matching close — the trailing comment.
        text = (
            'name "t"\n'
            'loops { decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } } } '
            "// keep this loops comment\n"
        )
        out = add_vertex_kind(text, "marker", BASIC)
        assert set(parse_vertex(out).loops) == {"decision", "task", "marker"}
        assert "// keep this loops comment" in out

    def test_non_kind_content_change_refuses(self):
        # The oracle also covers non-loop vertex content: a splice that
        # altered e.g. the store declaration must refuse. The normal splice
        # path cannot construct that mangle, so exercise _verified directly.
        from lang.vertex_mutation import _verified

        before = parse_vertex(MULTI)
        mangled = MULTI.replace("./data/test.db", "./else.db")
        with pytest.raises(ValueError, match="non-kind vertex content"):
            _verified(before, mangled, "test")
