"""Tests for the path-parametric KDL splice library.

Covers:
- kdl_find_block path semantics (bare-name, quoted-key, nested, single-line)
- kdl_insert_child placement rules (sibling grouping, end-of-block fallback)
- kdl_remove_child match modes (name only / + positional key / + property)
- Corpus round-trip: insert + remove on every in-repo .vertex must be
  byte-identical to the original.
- Mutation correctness: re-parse after insert/remove yields the expected AST.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lang import parse_vertex
from lang.population import (
    kdl_find_block,
    kdl_insert_child,
    kdl_remove_child,
)

# ---------------------------------------------------------------------------
# kdl_find_block — path semantics
# ---------------------------------------------------------------------------


class TestKdlFindBlock:
    def test_bare_name_top_level(self):
        text = 'name "x"\nloops {\n  decision { fold { items "by" "topic" } }\n}\n'
        start, end = kdl_find_block(text, ["loops"])
        assert start == 1
        assert end == 3

    def test_nested_bare_name(self):
        text = 'name "x"\nloops {\n  decision {\n    fold { items "by" "topic" }\n  }\n}\n'
        start, end = kdl_find_block(text, ["loops", "decision"])
        assert start == 2
        assert end == 4

    def test_quoted_positional_key(self):
        text = 'name "x"\ntemplate "feed.loop" {\n  with kind="rss"\n}\n'
        start, end = kdl_find_block(text, ['template "feed.loop"'])
        assert start == 1
        assert end == 3

    def test_quoted_key_path_normalization(self):
        """./feed.loop should match feed.loop (Path() equality)."""
        text = 'template "./feed.loop" {\n  with kind="rss"\n}\n'
        start, end = kdl_find_block(text, ['template "feed.loop"'])
        assert start == 0
        assert end == 2

    def test_template_inside_sources(self):
        text = (
            'name "x"\n'
            "sources {\n"
            '  template "feed.loop" {\n'
            '    with kind="rss"\n'
            "  }\n"
            "}\n"
        )
        start, end = kdl_find_block(text, ["sources", 'template "feed.loop"'])
        assert start == 2
        assert end == 4

    def test_single_line_block(self):
        text = 'decision { fold { items "by" "topic" } }\n'
        start, end = kdl_find_block(text, ["decision"])
        assert start == 0
        assert end == 0

    def test_nested_into_single_line(self):
        """Path can drill into a single-line block — start==end at outer level
        means the inner block lives entirely on that one line. Searching
        further is degenerate; we expect not-found for the inner segment."""
        text = 'decision { fold { items "by" "topic" } }\n'
        # No way to drill in via line-based splice when the parent is single-line.
        with pytest.raises(ValueError):
            kdl_find_block(text, ["decision", "fold"])

    def test_block_not_found(self):
        text = 'name "x"\nloops {}\n'
        with pytest.raises(ValueError, match="Block not found"):
            kdl_find_block(text, ["missing"])

    def test_empty_path_raises(self):
        with pytest.raises(ValueError, match="at least one segment"):
            kdl_find_block("x {}", [])

    def test_unclosed_block_raises(self):
        text = 'loops {\n  decision {\n    fold {\n'
        with pytest.raises(ValueError, match="Unclosed"):
            kdl_find_block(text, ["loops"])

    def test_skips_nested_homonym(self):
        """`loops` inside another block must not be matched at outer scope."""
        text = (
            "wrapper {\n"
            "  loops { decision { fold { } } }\n"
            "}\n"
            "loops {\n"
            "  thread { }\n"
            "}\n"
        )
        # Outer scan: the FIRST `loops` is inside `wrapper`. My scanner skips
        # over the wrapper block's body, so the next match should be the
        # top-level loops at line 3.
        start, end = kdl_find_block(text, ["loops"])
        assert start == 3
        # The matched block should be the multi-line one (lines 3..5).
        assert end == 5


# ---------------------------------------------------------------------------
# kdl_insert_child
# ---------------------------------------------------------------------------


class TestKdlInsertChild:
    def test_insert_into_empty_block(self):
        text = "loops {\n}\n"
        result = kdl_insert_child(text, ["loops"], 'decision { fold { items "by" "topic" } }')
        assert 'decision { fold { items "by" "topic" } }' in result
        assert result.endswith("\n")

    def test_insert_after_last_sibling_of_same_name(self):
        text = (
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  thread { fold { items "by" "name" } }\n'
            "  boundary when=\"session\"\n"
            "}\n"
        )
        result = kdl_insert_child(
            text, ["loops"], 'task { fold { items "by" "name" } }'
        )
        lines = result.splitlines()
        task_idx = next(i for i, ln in enumerate(lines) if "task {" in ln)
        boundary_idx = next(i for i, ln in enumerate(lines) if "boundary" in ln)
        # task is NOT a sibling of "thread" (different first token), so it
        # should land before the closing brace, after boundary.
        assert task_idx > boundary_idx

    def test_insert_groups_with_same_first_token(self):
        text = (
            "combine {\n"
            '  vertex "./a.vertex"\n'
            '  vertex "./b.vertex"\n'
            "}\n"
        )
        result = kdl_insert_child(text, ["combine"], 'vertex "./c.vertex"')
        lines = result.splitlines()
        a_idx = next(i for i, ln in enumerate(lines) if "a.vertex" in ln)
        b_idx = next(i for i, ln in enumerate(lines) if "b.vertex" in ln)
        c_idx = next(i for i, ln in enumerate(lines) if "c.vertex" in ln)
        assert a_idx < b_idx < c_idx

    def test_insert_into_single_line_parent_expands(self):
        text = 'loops { decision { fold { items "by" "topic" } } }\n'
        result = kdl_insert_child(text, ["loops"], 'thread { fold { items "by" "name" } }')
        # The single-line block should have been split across lines.
        assert "\n" in result.rstrip("\n")
        assert "decision" in result
        assert "thread" in result

    def test_insert_indents_to_match_existing_children(self):
        text = (
            "loops {\n"
            "    decision { fold { items \"by\" \"topic\" } }\n"
            "}\n"
        )
        result = kdl_insert_child(
            text, ["loops"], 'task { fold { items "by" "name" } }'
        )
        # New line should have 4-space indent (matches existing).
        new_line = next(ln for ln in result.splitlines() if "task {" in ln)
        assert new_line.startswith("    ")

    def test_insert_empty_child_raises(self):
        with pytest.raises(ValueError):
            kdl_insert_child("loops {}\n", ["loops"], "   \n")

    def test_insert_multiline_block(self):
        text = "loops {\n}\n"
        child = "decision {\n  fold {\n    items \"by\" \"topic\"\n  }\n}"
        result = kdl_insert_child(text, ["loops"], child)
        lines = result.splitlines()
        # Should preserve internal relative indentation of child.
        decision_idx = next(
            i for i, ln in enumerate(lines) if ln.strip() == "decision {"
        )
        fold_line = lines[decision_idx + 1]
        items_line = lines[decision_idx + 2]
        fold_indent_len = len(fold_line) - len(fold_line.lstrip())
        assert items_line.startswith(fold_line[:fold_indent_len] + "  ")


# ---------------------------------------------------------------------------
# kdl_remove_child
# ---------------------------------------------------------------------------


class TestKdlRemoveChild:
    def test_remove_by_name_only(self):
        text = (
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  thread { fold { items "by" "name" } }\n'
            "}\n"
        )
        result = kdl_remove_child(text, ["loops"], "decision")
        assert "decision" not in result
        assert "thread" in result

    def test_remove_by_positional_key(self):
        text = (
            "combine {\n"
            '  vertex "./a.vertex"\n'
            '  vertex "./b.vertex"\n'
            "}\n"
        )
        result = kdl_remove_child(text, ["combine"], "vertex", "./a.vertex")
        assert "a.vertex" not in result
        assert "b.vertex" in result

    def test_remove_by_property(self):
        text = (
            'template "feed.loop" {\n'
            '  with kind="rss" url="https://a"\n'
            '  with kind="atom" url="https://b"\n'
            "}\n"
        )
        result = kdl_remove_child(
            text,
            ['template "feed.loop"'],
            "with",
            "rss",
            key_field="kind",
        )
        assert "rss" not in result
        assert "atom" in result

    def test_remove_multiline_block_child(self):
        text = (
            "loops {\n"
            "  decision {\n"
            "    fold {\n"
            '      items "by" "topic"\n'
            "    }\n"
            "  }\n"
            "  thread { }\n"
            "}\n"
        )
        result = kdl_remove_child(text, ["loops"], "decision")
        assert "decision" not in result
        assert "fold" not in result  # nested fold removed with parent
        assert "thread" in result

    def test_remove_not_found_raises(self):
        text = "loops {\n  decision {}\n}\n"
        with pytest.raises(ValueError, match="No matching child"):
            kdl_remove_child(text, ["loops"], "thread")

    def test_remove_from_single_line_parent_unsupported(self):
        """Single-line parent blocks have no child lines to scan — removal
        raises. Documented limitation; insert expands first if needed."""
        text = "loops { decision { fold { items \"by\" \"topic\" } } }\n"
        with pytest.raises(ValueError, match="No matching child"):
            kdl_remove_child(text, ["loops"], "decision")


# ---------------------------------------------------------------------------
# Single-line parent: insert expands (one-way), result stays parseable
# ---------------------------------------------------------------------------


class TestSingleLineParent:
    def test_insert_then_remove_is_not_identity(self):
        """Inserting into a single-line parent expands it across lines.
        Removing the inserted child does NOT collapse back to single-line.
        Documented one-way behavior."""
        original = (
            'name "test"\n'
            'loops { decision { fold { items "by" "topic" } } }\n'
        )
        inserted = kdl_insert_child(
            original, ["loops"], '__rt__ "marker"'
        )
        restored = kdl_remove_child(inserted, ["loops"], "__rt__", "marker")
        # Expansion is irreversible — restored has parent now multi-line.
        assert restored != original
        # But the file must remain valid KDL.
        vf = parse_vertex(restored)
        assert "decision" in vf.loops
        assert "__rt__" not in vf.loops


# ---------------------------------------------------------------------------
# Corpus round-trip — the regression bar
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _corpus_files() -> list[Path]:
    """All in-repo .vertex files. Environment-independent."""
    out: list[Path] = []
    for p in _REPO_ROOT.rglob("*.vertex"):
        # Skip anything inside a hidden state dir we don't author.
        if any(part.startswith(".git") for part in p.parts):
            continue
        out.append(p)
    return sorted(out)


def _candidate_parents(text: str) -> list[list[str]]:
    """Return parent paths that actually exist in `text`."""
    candidates: list[list[str]] = []
    for parent in (["loops"], ["observers"], ["combine"], ["sources"]):
        try:
            kdl_find_block(text, parent)
            candidates.append(parent)
        except ValueError:
            continue
    return candidates


@pytest.mark.parametrize(
    "vertex_file",
    _corpus_files(),
    ids=lambda p: str(p.relative_to(_REPO_ROOT)),
)
def test_corpus_roundtrip_insert_remove_is_identity(vertex_file: Path):
    """For every in-repo .vertex, insert + remove of a marker child must
    round-trip to byte-identical text."""
    original = vertex_file.read_text()
    parents = _candidate_parents(original)
    if not parents:
        pytest.skip(f"{vertex_file.name}: no known parent block to test")
    for parent in parents:
        marker = '__rt__ "marker"'
        inserted = kdl_insert_child(original, parent, marker)
        assert inserted != original, f"insert no-op on {vertex_file}/{parent}"
        restored = kdl_remove_child(inserted, parent, "__rt__", "marker")
        assert restored == original, (
            f"round-trip mismatch on {vertex_file}/{parent}\n"
            f"--- original ---\n{original}\n--- after rt ---\n{restored}"
        )


# ---------------------------------------------------------------------------
# Mutation correctness — parse the result, verify AST changed as expected
# ---------------------------------------------------------------------------


class TestMutationCorrectness:
    def test_add_loop_kind(self):
        original = (
            'name "test"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        mutated = kdl_insert_child(
            original, ["loops"], 'task { fold { items "by" "name" } }'
        )
        vf = parse_vertex(mutated)
        assert "decision" in vf.loops
        assert "task" in vf.loops

    def test_remove_loop_kind(self):
        original = (
            'name "test"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        mutated = kdl_remove_child(original, ["loops"], "task")
        vf = parse_vertex(mutated)
        assert "decision" in vf.loops
        assert "task" not in vf.loops

    def test_add_observer(self):
        original = (
            'name "test"\n'
            "loops { decision { fold { items \"by\" \"topic\" } } }\n"
            "observers {\n"
            "  kyle { }\n"
            "}\n"
        )
        mutated = kdl_insert_child(original, ["observers"], "loops-claude { }")
        vf = parse_vertex(mutated)
        names = {o.name for o in (vf.observers or ())}
        assert "kyle" in names
        assert "loops-claude" in names

    def test_remove_observer(self):
        original = (
            'name "test"\n'
            "loops { decision { fold { items \"by\" \"topic\" } } }\n"
            "observers {\n"
            "  kyle { }\n"
            "  loops-claude { }\n"
            "}\n"
        )
        mutated = kdl_remove_child(original, ["observers"], "loops-claude")
        vf = parse_vertex(mutated)
        names = {o.name for o in (vf.observers or ())}
        assert "kyle" in names
        assert "loops-claude" not in names

    def test_add_combine_entry(self):
        original = (
            'name "root"\n'
            "combine {\n"
            '  vertex "./a.vertex"\n'
            "}\n"
        )
        mutated = kdl_insert_child(original, ["combine"], 'vertex "./b.vertex"')
        vf = parse_vertex(mutated)
        names = {e.name for e in (vf.combine or ())}
        assert "./a.vertex" in names
        assert "./b.vertex" in names

    def test_remove_combine_entry(self):
        original = (
            'name "root"\n'
            "combine {\n"
            '  vertex "./a.vertex"\n'
            '  vertex "./b.vertex"\n'
            "}\n"
        )
        mutated = kdl_remove_child(original, ["combine"], "vertex", "./a.vertex")
        vf = parse_vertex(mutated)
        names = {e.name for e in (vf.combine or ())}
        assert "./a.vertex" not in names
        assert "./b.vertex" in names
