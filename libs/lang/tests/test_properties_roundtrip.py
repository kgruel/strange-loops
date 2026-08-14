"""Property-based tests for KDL AST parse/emit roundtrips and vertex mutation preservation.

Validates:
- Emit->parse fixpoint: parse(emit(ast)) == ast for all generated KDL documents.
- Parse->emit stability: emit(parse(t)) is byte-identical to t for generated KDL text.
- Mutation preservation: add/edit/remove vertex kind operations preserve all untouched
  sibling kinds, comments, whitespace, and non-kind sections.
"""

from __future__ import annotations

import ckdl
from hypothesis import given, settings

from lang import (
    add_vertex_kind,
    edit_vertex_kind,
    parse_vertex,
    remove_vertex_kind,
)
from lang.ast import LoopDef

from tests.strategies_kdl import (
    kdl_documents,
    loop_definitions,
    vertex_documents,
)

# =============================================================================
# 1. KDL AST Emit <-> Parse Roundtrip Properties
# =============================================================================


class TestKdlAstRoundtripProperties:
    """Property tests asserting KDL emit/parse fixpoint and stability."""

    @settings(max_examples=200, deadline=None)
    @given(doc=kdl_documents(min_nodes=0, max_nodes=5, max_depth=3))
    def test_kdl_emit_parse_fixpoint(self, doc: ckdl.Document) -> None:
        """For any generated AST, parsing the emitted KDL text yields the original AST."""
        emitted_text = doc.dump()
        parsed_doc = ckdl.parse(emitted_text)
        assert parsed_doc == doc

    @settings(max_examples=200, deadline=None)
    @given(doc=kdl_documents(min_nodes=0, max_nodes=5, max_depth=3))
    def test_kdl_parse_emit_stability(self, doc: ckdl.Document) -> None:
        """For any generated KDL text, re-emitting after parsing is byte-identical (fixpoint)."""
        initial_text = doc.dump()
        reparsed = ckdl.parse(initial_text)
        re_emitted_text = reparsed.dump()
        assert re_emitted_text == initial_text


# =============================================================================
# 2. Vertex Mutation Preservation Properties
# =============================================================================


class TestVertexMutationPreservationProperties:
    """Property tests asserting untouched-region preservation across vertex mutations."""

    @settings(max_examples=100, deadline=None)
    @given(vertex_text=vertex_documents(), new_def=loop_definitions())
    def test_add_vertex_kind_preserves_untouched_regions(
        self,
        vertex_text: str,
        new_def: LoopDef,
    ) -> None:
        """add_vertex_kind preserves all existing sibling kinds, comments, and non-kind content."""
        before = parse_vertex(vertex_text)
        new_kind = "extra_metric"

        added_text = add_vertex_kind(vertex_text, new_kind, new_def)
        after = parse_vertex(added_text)

        # 1. Non-kind text content and comments are preserved
        assert "// Top-level document header" in added_text
        assert "// Declarative loops block" in added_text
        assert "// Observers block" in added_text
        assert 'name "test_vertex"' in added_text
        assert 'store "store.db"' in added_text

        # 2. All pre-existing kinds are definition-equal
        assert set(before.loops).issubset(set(after.loops))
        for kind_name, original_def in before.loops.items():
            assert after.loops[kind_name] == original_def

        # 3. New kind is correctly added
        assert after.loops[new_kind] == new_def

        # 4. Non-kind AST fields (name, store, observers) are identical
        assert after.name == before.name
        assert after.store == before.store
        assert after.observers == before.observers

    @settings(max_examples=100, deadline=None)
    @given(vertex_text=vertex_documents(), replacement_def=loop_definitions())
    def test_edit_vertex_kind_preserves_untouched_regions(
        self,
        vertex_text: str,
        replacement_def: LoopDef,
    ) -> None:
        """edit_vertex_kind preserves untouched sibling kinds, comments, and non-kind sections."""
        before = parse_vertex(vertex_text)
        target_kind = next(iter(before.loops.keys()))

        edited_text = edit_vertex_kind(vertex_text, target_kind, replacement_def)
        after = parse_vertex(edited_text)

        # 1. Comments and outer document sections are preserved
        assert "// Top-level document header" in edited_text
        assert "// Observers block" in edited_text
        assert 'name "test_vertex"' in edited_text
        assert 'store "store.db"' in edited_text

        # 2. Untouched sibling kinds are definition-equal
        for sibling_kind, sibling_def in before.loops.items():
            if sibling_kind != target_kind:
                assert after.loops[sibling_kind] == sibling_def

        # 3. Edited kind has the new definition
        assert after.loops[target_kind] == replacement_def

        # 4. Non-kind AST fields are identical
        assert after.name == before.name
        assert after.store == before.store
        assert after.observers == before.observers

    @settings(max_examples=100, deadline=None)
    @given(vertex_text=vertex_documents())
    def test_remove_vertex_kind_preserves_untouched_regions(
        self,
        vertex_text: str,
    ) -> None:
        """remove_vertex_kind preserves remaining sibling kinds, comments, and document sections."""
        before = parse_vertex(vertex_text)
        target_kind = next(iter(before.loops.keys()))

        removed_text = remove_vertex_kind(vertex_text, target_kind)
        after = parse_vertex(removed_text)

        # 1. Comments and outer document sections are preserved
        assert "// Top-level document header" in removed_text
        assert "// Observers block" in removed_text
        assert 'name "test_vertex"' in removed_text

        # 2. Remaining sibling kinds are definition-equal
        for sibling_kind, sibling_def in before.loops.items():
            if sibling_kind != target_kind:
                assert after.loops[sibling_kind] == sibling_def

        # 3. Target kind is removed
        assert target_kind not in after.loops

        # 4. Non-kind AST fields are identical
        assert after.name == before.name
        assert after.store == before.store
        assert after.observers == before.observers

    @settings(max_examples=100, deadline=None)
    @given(vertex_text=vertex_documents(), new_def=loop_definitions())
    def test_add_then_remove_roundtrip_byte_identity(
        self,
        vertex_text: str,
        new_def: LoopDef,
    ) -> None:
        """Adding a kind then removing it on a multiline loops block yields byte-identical text."""
        temp_kind = "temporary_probe_kind"
        added_text = add_vertex_kind(vertex_text, temp_kind, new_def)
        restored_text = remove_vertex_kind(added_text, temp_kind)
        assert restored_text == vertex_text
