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

    def test_duplicate_sibling_kind_rejected_on_remove(self):
        # SOL-R3-01 repro 1: removing `decision` from a line also carrying
        # `task`, with an identical duplicate `task` later, used to succeed —
        # the physical task declarations fell 2 -> 1 while the parses stayed
        # definition-equal (last-wins collapse blinded the oracle). Duplicate
        # loop-kind nodes are now a typed pre-condition refusal.
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }; '
            'task { fold { items "by" "name" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="duplicate"):
            remove_vertex_kind(doc, "decision")

    def test_duplicate_target_kind_rejected_on_edit(self):
        # SOL-R3-01 repro 2: with duplicate `decision` declarations, edit
        # changed the SHADOWED one and reported success while
        # after.loops["decision"] != requested. Duplicates refuse up front.
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  decision { fold { items "by" "name" } }\n'
            "}\n"
        )
        new = LoopDef(folds=(FoldDecl("items", FoldBy("status")),))
        with pytest.raises(ValueError, match="duplicate"):
            edit_vertex_kind(doc, "decision", new)
        with pytest.raises(ValueError, match="duplicate"):
            add_vertex_kind(doc, "marker", BASIC)

    def test_edit_preserves_trailing_comment(self):
        # SOL-R3-01 repro 3: editing a declaration followed by a trailing
        # comment silently removed the comment. The suffix after the block's
        # closing brace must survive the splice.
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } } '
            "// KEEP: operational rationale\n"
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        new = LoopDef(folds=(FoldDecl("items", FoldBy("status")),))
        out = edit_vertex_kind(doc, "decision", new)
        assert "// KEEP: operational rationale" in out
        assert parse_vertex(out).loops["decision"] == new

    def test_edit_refuses_rather_than_drop_interior_comment(self):
        # A comment INSIDE the replaced span cannot be carried through the
        # regenerated block — the honest answer is a typed refusal, never a
        # silent drop (_verified claims preservation, so it must be honest).
        doc = (
            'name "t"\n'
            "loops {\n"
            "  decision {\n"
            "    // KEEP: interior rationale\n"
            '    fold { items "by" "topic" }\n'
            "  }\n"
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="comment"):
            edit_vertex_kind(doc, "decision", BASIC)

    def test_verified_asserts_target_equals_requested_definition(self):
        # SOL-R3-01 part (b), belt-and-braces under the duplicate refusal:
        # the post-mutation parse of the target kind must EQUAL the requested
        # LoopDef, or _verified refuses.
        from lang.vertex_mutation import _verified

        before = parse_vertex(MULTI)
        requested = LoopDef(folds=(FoldDecl("items", FoldBy("status")),))
        # MULTI unchanged: decision still folds by topic, not the requested.
        with pytest.raises(ValueError, match="requested definition"):
            _verified(
                before, MULTI, "test", edited="decision", definition=requested
            )

    def test_non_kind_content_change_refuses(self):
        # The oracle also covers non-loop vertex content: a splice that
        # altered e.g. the store declaration must refuse. The normal splice
        # path cannot construct that mangle, so exercise _verified directly.
        from lang.vertex_mutation import _verified

        before = parse_vertex(MULTI)
        mangled = MULTI.replace("./data/test.db", "./else.db")
        with pytest.raises(ValueError, match="non-kind vertex content"):
            _verified(before, mangled, "test")


class TestScannerProvableDomain:
    """SOL-R4-01 arbiter ruling: end the lexical arms race with refusal.

    KDL raw strings (``#"…"#`` / ``##"…"##``) are outside the quote-aware
    scanner's PROVABLE DOMAIN. Mutations over vertex text containing
    raw-string syntax must REFUSE with a typed, actionable ValueError —
    never succeed with silent lexical loss.
    """

    # Sol's r4 repro 1: a raw string hides the same-line `task` sibling
    # from _loops_block_child_names; with a second identical `task` later,
    # edit/remove succeeded while the physical count fell 2 -> 1.
    DUP_HIDDEN_BY_RAW = (
        'name "t"\n'
        "loops {\n"
        '  decision { boundary after=1 { run #"echo " quoted"# } }; '
        'task { fold { items "by" "name" } }\n'
        '  task { fold { items "by" "name" } }\n'
        "}\n"
    )

    # Sol's r4 repro 2: `run #"echo " quoted"#` followed by `// KEEP` —
    # _has_comment_outside_strings returned False and the edit silently
    # deleted the comment.
    COMMENT_AFTER_RAW = (
        'name "t"\n'
        "loops {\n"
        "  decision {\n"
        '    boundary after=1 { run #"echo " quoted"# } // KEEP\n'
        "  }\n"
        '  task { fold { items "by" "name" } }\n'
        "}\n"
    )

    def test_repro_docs_parse(self):
        assert set(parse_vertex(self.DUP_HIDDEN_BY_RAW).loops) >= {
            "decision", "task",
        }
        assert set(parse_vertex(self.COMMENT_AFTER_RAW).loops) == {
            "decision", "task",
        }

    @pytest.mark.parametrize(
        "doc", [DUP_HIDDEN_BY_RAW, COMMENT_AFTER_RAW],
        ids=["dup-hidden-by-raw", "comment-after-raw"],
    )
    def test_edit_refuses_outside_provable_domain(self, doc):
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    @pytest.mark.parametrize(
        "doc", [DUP_HIDDEN_BY_RAW, COMMENT_AFTER_RAW],
        ids=["dup-hidden-by-raw", "comment-after-raw"],
    )
    def test_remove_refuses_outside_provable_domain(self, doc):
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_add_refuses_outside_provable_domain(self):
        # add's duplicate-multiplicity precondition rides the same blind
        # scanner, so add refuses over raw-string syntax too.
        with pytest.raises(ValueError, match="cannot prove safe"):
            add_vertex_kind(self.DUP_HIDDEN_BY_RAW, "marker", BASIC)

    def test_no_raw_string_happy_path_unchanged(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = edit_vertex_kind(doc, "decision", BASIC)
        assert set(parse_vertex(out).loops) == {"decision", "task"}
        out2 = remove_vertex_kind(doc, "decision")
        assert set(parse_vertex(out2).loops) == {"task"}


class TestScannerProvableDomainR5:
    """Sol r5: two parser-accepted spellings evaded the r4 refused set —
    the zero-hash raw-string opener ``r"…"`` and a plain string containing
    a LITERAL NEWLINE. Both are outside the provable domain and must
    refuse. Multi-hash raw strings stay pinned refused; plain strings that
    merely END in the letter r ("system-monitor") stay allowed."""

    ZERO_HASH_RAW_DOC = (
        'name "t"\n'
        "loops {\n"
        '  decision { boundary after=1 { run r"echo \\" } }; '
        'task { fold { items "by" "name" } }\n'
        '  task { fold { items "by" "name" } }\n'
        "}\n"
    )

    NEWLINE_IN_STRING_DOC = (
        'name "t"\n'
        "loops {\n"
        '  decision { boundary after=1 { run "echo\n'
        ' quoted" } }; task { fold { items "by" "name" } }\n'
        '  task { fold { items "by" "name" } }\n'
        "}\n"
    )

    @pytest.mark.parametrize(
        "doc", [ZERO_HASH_RAW_DOC, NEWLINE_IN_STRING_DOC],
        ids=["zero-hash-raw", "newline-in-string"],
    )
    def test_repro_docs_parse(self, doc):
        assert "task" in parse_vertex(doc).loops

    @pytest.mark.parametrize(
        "doc", [ZERO_HASH_RAW_DOC, NEWLINE_IN_STRING_DOC],
        ids=["zero-hash-raw", "newline-in-string"],
    )
    def test_edit_refuses(self, doc):
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    @pytest.mark.parametrize(
        "doc", [ZERO_HASH_RAW_DOC, NEWLINE_IN_STRING_DOC],
        ids=["zero-hash-raw", "newline-in-string"],
    )
    def test_remove_refuses(self, doc):
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    @pytest.mark.parametrize(
        "doc", [ZERO_HASH_RAW_DOC, NEWLINE_IN_STRING_DOC],
        ids=["zero-hash-raw", "newline-in-string"],
    )
    def test_add_refuses(self, doc):
        with pytest.raises(ValueError, match="cannot prove safe"):
            add_vertex_kind(doc, "marker", BASIC)

    @pytest.mark.parametrize("hashes", list(range(1, 9)))
    def test_multi_hash_raw_strings_stay_refused(self, hashes):
        h = "#" * hashes
        doc = (
            'name "t"\n'
            "loops {\n"
            f'  decision {{ boundary after=1 {{ run {h}"echo"{h} }} }}\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    def test_string_ending_in_letter_r_stays_allowed(self):
        # "system-monitor" contains the two characters r" at its closing
        # quote — the in-string spelling is real corpus content and must
        # NOT refuse; only the OUT-of-string r" (raw opener) is refused.
        doc = (
            'name "system-monitor"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = edit_vertex_kind(doc, "decision", BASIC)
        assert set(parse_vertex(out).loops) == {"decision", "task"}
        out2 = remove_vertex_kind(doc, "decision")
        assert set(parse_vertex(out2).loops) == {"task"}


class TestScannerProvableDomainR6:
    """Sol r6 + arbiter ruling: the domain check inverts from a blacklist
    of refused substrings to a WHITELIST enforced by a three-state machine
    (code / plain_string / line_comment). Refused here: non-LF newline
    characters anywhere (R6-01 — they desync line accounting), and block
    comment / slashdash openers in code state (R6-02 — a quote inside
    /* " */ poisoned the flat quote tracker, letting a following r"
    masquerade as a closing quote). Quotes inside // comments are inert;
    /* inside a plain string stays legal (glob patterns)."""

    NON_LF_NEWLINES = ["\r", "\f", "\u0085", "\u2028", "\u2029"]

    @pytest.mark.parametrize(
        "ch", NON_LF_NEWLINES,
        ids=["CR", "FF", "NEL", "LS", "PS"],
    )
    def test_non_lf_newline_refuses(self, ch):
        # R6-01: a non-LF newline INSIDE a string evaded the literal-newline
        # refusal (which matched only \n).
        doc = (
            'name "t"\n'
            "loops {\n"
            f'  decision {{ boundary after=1 {{ run "echo{ch} quoted" }} }}\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    def test_block_comment_quote_concealment_refuses(self):
        # R6-02: the quote inside /* " */ flipped the flat tracker's in_str,
        # so the following r" read as a closing quote instead of a raw
        # opener. Block comments in code state now refuse outright.
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { boundary after=1 { run r"echo \\" } } /* " */ ; '
            'task { fold { items "by" "name" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    def test_plain_block_comment_refuses(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } } /* note */\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_slashdash_refuses(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  /-retired { fold { items "by" "name" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_glob_pattern_inside_string_stays_allowed(self):
        # /* INSIDE a plain string is legal corpus content — the reason
        # this is a state machine, not substring search.
        doc = (
            'name "t"\n'
            'discover "./**/*.loop"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = edit_vertex_kind(doc, "decision", BASIC)
        assert set(parse_vertex(out).loops) == {"decision", "task"}

    def test_quote_inside_line_comment_is_inert(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  // a stray " quote in a line comment must not poison tracking\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = remove_vertex_kind(doc, "decision")
        assert set(parse_vertex(out).loops) == {"task"}


class TestScannerWhitelistAddendum:
    """Arbiter addendum to the whitelist ruling: (a) only \\\\ and \\"
    escapes are whitelisted inside plain strings — every other escape
    form refuses (0 backslashes of ANY kind in the .vertex corpus);
    (b) non-ASCII and control characters in CODE state refuse wholesale
    (BOM, unicode quote lookalikes), while staying legal inside strings."""

    @pytest.mark.parametrize(
        "escape", ["\\n", "\\t", "\\u{0041}", "\\s"],
        ids=["esc-n", "esc-t", "esc-unicode", "esc-space"],
    )
    def test_non_whitelisted_escape_refuses(self, escape):
        doc = (
            'name "t"\n'
            "loops {\n"
            f'  decision {{ boundary after=1 {{ run "echo{escape}x" }} }}\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            edit_vertex_kind(doc, "decision", BASIC)

    def test_whitelisted_escapes_stay_allowed(self):
        doc = (
            'name "t"\n'
            "loops {\n"
            '  decision { boundary when="a\\\\b \\"q\\"" }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = remove_vertex_kind(doc, "decision")
        assert set(parse_vertex(out).loops) == {"task"}

    @pytest.mark.parametrize(
        "ch", ["﻿", "“", "”", " ", "\x00", "\x0b"],
        ids=["BOM", "left-curly-quote", "right-curly-quote", "nbsp",
             "NUL", "VT"],
    )
    def test_non_ascii_or_control_in_code_refuses(self, ch):
        doc = (
            f'{ch}name "t"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_vt_inside_plain_string_refuses(self):
        """SOL-R7-01: KDL counts VT (U+000B) as a newline; a VT inside a
        plain string must refuse like any other in-string newline."""
        doc = (
            'name "be\x0bfore"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_vt_inside_line_comment_refuses(self):
        """SOL-R7-01: VT is a KDL newline, so it would END a // comment for
        the parser while the scanner's line_comment state would swallow the
        rest of the physical line — refuse it."""
        doc = (
            "name \"t\"\n"
            "// comment\x0b decision-lookalike\n"
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        with pytest.raises(ValueError, match="cannot prove safe"):
            remove_vertex_kind(doc, "decision")

    def test_non_ascii_inside_string_stays_allowed(self):
        doc = (
            'name "té“st"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        out = remove_vertex_kind(doc, "decision")
        assert set(parse_vertex(out).loops) == {"task"}
