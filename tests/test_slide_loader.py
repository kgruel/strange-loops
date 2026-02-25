"""Tests for the slide loader (markdown-based slides with zoom levels)."""

import sys
from pathlib import Path

import pytest

# slide_loader lives in demos/, not in the package
_demos_dir = str(Path(__file__).resolve().parent.parent / "demos")
if _demos_dir not in sys.path:
    sys.path.insert(0, _demos_dir)

from slide_loader import (
    GROUP_ORDER,
    ParsedSlide,
    SlideValidationError,
    build_navigation,
    get_navigation_sequence,
    load_slide_md,
    load_slides_dir,
    parse_body,
    parse_frontmatter,
    parse_simple_yaml,
    parse_styled_text,
    validate_slides,
)


# -- Frontmatter Parsing --


class TestParseFrontmatter:
    """Tests for YAML frontmatter extraction."""

    def test_basic_frontmatter(self):
        """Extracts key-value pairs from YAML frontmatter."""
        content = "---\nid: cell\ntitle: Cell\n---\n\n# Cell\n"
        fm, body = parse_frontmatter(content)
        assert fm["id"] == "cell"
        assert fm["title"] == "Cell"
        assert "# Cell" in body

    def test_no_frontmatter(self):
        """Returns empty dict when no frontmatter present."""
        content = "# No frontmatter\n\nSome text."
        fm, body = parse_frontmatter(content)
        assert fm == {}
        assert body == content

    def test_integer_values(self):
        """Parses numeric values as integers."""
        content = "---\norder: 3\n---\n\nbody"
        fm, _ = parse_frontmatter(content)
        assert fm["order"] == 3
        assert isinstance(fm["order"], int)

    def test_empty_group(self):
        """Empty value after colon is not stored."""
        content = "---\nid: intro\ngroup:\n---\n\nbody"
        fm, _ = parse_frontmatter(content)
        assert fm["id"] == "intro"
        assert "group" not in fm  # empty value not stored

    def test_align_field(self):
        """Align field is parsed as string."""
        content = "---\nid: test\nalign: center\n---\n\nbody"
        fm, _ = parse_frontmatter(content)
        assert fm["align"] == "center"


class TestParseSimpleYaml:
    """Tests for the minimal YAML parser."""

    def test_skips_comments(self):
        """Lines starting with # are ignored."""
        result = parse_simple_yaml("# comment\nkey: value")
        assert result == {"key": "value"}

    def test_skips_blank_lines(self):
        """Empty lines are ignored."""
        result = parse_simple_yaml("a: 1\n\nb: 2")
        assert result == {"a": 1, "b": 2}

    def test_colon_in_value(self):
        """Only first colon splits key from value."""
        result = parse_simple_yaml("title: Cell: the atom")
        assert result["title"] == "Cell: the atom"


# -- Body Parsing --


class TestParseBody:
    """Tests for markdown body parsing into sections."""

    def test_title_extraction(self):
        """First h1 becomes the title."""
        title, _, _, _ = parse_body("# My Title\n\nsome text")
        assert title == "My Title"

    def test_no_title(self):
        """Body without h1 returns empty title."""
        title, _, _, _ = parse_body("some text\n\nmore text")
        assert title == ""

    def test_text_section(self):
        """Plain text becomes a text section."""
        _, common, _, _ = parse_body("# T\n\nsome paragraph text")
        assert len(common) == 1
        assert common[0]["type"] == "text"
        assert common[0]["content"] == "some paragraph text"

    def test_code_section(self):
        """Fenced code block becomes a code section."""
        _, common, _, _ = parse_body("# T\n\n```python\nx = 1\n```")
        assert len(common) == 1
        assert common[0]["type"] == "code"
        assert common[0]["source"] == "x = 1"
        assert common[0]["lang"] == "python"

    def test_demo_section(self):
        """[demo:id] marker becomes a demo section."""
        _, common, _, _ = parse_body("# T\n\n[demo:spinner]")
        assert len(common) == 1
        assert common[0]["type"] == "demo"
        assert common[0]["demo_id"] == "spinner"

    def test_spacer_section(self):
        """[spacer] and [spacer:N] become spacer sections."""
        _, common, _, _ = parse_body("# T\n\n[spacer]\n\n[spacer:3]")
        assert len(common) == 2
        assert common[0]["type"] == "spacer"
        assert common[0]["lines"] == 1
        assert common[1]["type"] == "spacer"
        assert common[1]["lines"] == 3

    def test_centering_default_left(self):
        """Text sections default to center=False."""
        _, common, _, _ = parse_body("# T\n\nhello")
        assert common[0]["center"] is False

    def test_centering_default_center(self):
        """default_align='center' makes text sections centered."""
        _, common, _, _ = parse_body("# T\n\nhello", default_align="center")
        assert common[0]["center"] is True

    def test_align_override_one_shot(self):
        """[align:left] overrides for next section only, then reverts."""
        body = "# T\n\n[align:left]\n\nfirst\n\nsecond"
        _, common, _, _ = parse_body(body, default_align="center")
        assert common[0]["center"] is False  # overridden to left
        assert common[1]["center"] is True  # reverted to center default

    def test_docgen_comments_skipped(self):
        """<!-- docgen:... --> lines are skipped."""
        body = "# T\n\n<!-- docgen:begin py:mod:Cls -->\n\nhello\n\n<!-- docgen:end -->"
        _, common, _, _ = parse_body(body)
        assert len(common) == 1
        assert common[0]["type"] == "text"


# -- Zoom Parsing --


class TestZoomParsing:
    """Tests for zoom level markers and section splitting."""

    def test_common_before_zoom(self):
        """Content before first [zoom:N] is common."""
        body = "# T\n\ncommon text\n\n[zoom:0]\n\nzoom zero"
        _, common, zooms, max_zoom = parse_body(body)
        assert len(common) == 1
        assert common[0]["content"] == "common text"
        assert 0 in zooms
        assert max_zoom == 0

    def test_multiple_zoom_levels(self):
        """Multiple [zoom:N] markers create separate zoom sections."""
        body = "# T\n\n[zoom:0]\n\nlevel 0\n\n[zoom:1]\n\nlevel 1\n\n[zoom:2]\n\nlevel 2"
        _, common, zooms, max_zoom = parse_body(body)
        assert common == []
        assert max_zoom == 2
        assert len(zooms) == 3
        assert zooms[0][0]["content"] == "level 0"
        assert zooms[1][0]["content"] == "level 1"
        assert zooms[2][0]["content"] == "level 2"

    def test_max_zoom_derived(self):
        """max_zoom is the highest zoom level present."""
        body = "# T\n\n[zoom:0]\n\na\n\n[zoom:1]\n\nb"
        _, _, _, max_zoom = parse_body(body)
        assert max_zoom == 1

    def test_zoom_with_code(self):
        """Zoom sections can contain code blocks."""
        body = "# T\n\n[zoom:0]\n\n```python\nx = 1\n```\n\n[zoom:1]\n\n```python\ny = 2\n```"
        _, _, zooms, _ = parse_body(body)
        assert zooms[0][0]["type"] == "code"
        assert zooms[0][0]["source"] == "x = 1"
        assert zooms[1][0]["type"] == "code"
        assert zooms[1][0]["source"] == "y = 2"

    def test_zoom_centering_inherits_default(self):
        """Zoom sections inherit the default_align setting."""
        body = "# T\n\n[zoom:0]\n\ntext"
        _, _, zooms, _ = parse_body(body, default_align="center")
        assert zooms[0][0]["center"] is True


# -- Styled Text Parsing --


class TestParseStyledText:
    """Tests for inline markdown styling to Line conversion."""

    def test_plain_text(self):
        """Text without markup becomes a single plain span."""
        line = parse_styled_text("hello world")
        assert len(line.spans) == 1
        assert line.spans[0].text == "hello world"

    def test_bold(self):
        """**text** becomes bold."""
        line = parse_styled_text("before **bold** after")
        assert len(line.spans) == 3
        assert line.spans[1].text == "bold"
        assert line.spans[1].style.bold is True

    def test_dim(self):
        """*text* becomes dim."""
        line = parse_styled_text("before *dim* after")
        assert len(line.spans) == 3
        assert line.spans[1].text == "dim"
        assert line.spans[1].style.dim is True

    def test_code_keyword(self):
        """`text` becomes keyword style (cyan bold)."""
        line = parse_styled_text("use `arrow keys` now")
        assert len(line.spans) == 3
        assert line.spans[1].text == "arrow keys"
        assert line.spans[1].style.fg == "cyan"
        assert line.spans[1].style.bold is True

    def test_color_syntax(self):
        """{color:text} applies explicit color."""
        line = parse_styled_text("hello {cyan:world}")
        assert len(line.spans) == 2
        assert line.spans[1].text == "world"
        assert line.spans[1].style.fg == "cyan"

    def test_mixed_styles(self):
        """Multiple style types in one line."""
        line = parse_styled_text("`Cell` -> **Block**")
        assert line.spans[0].text == "Cell"
        assert line.spans[0].style.bold is True  # keyword
        assert line.spans[1].text == " -> "
        assert line.spans[2].text == "Block"
        assert line.spans[2].style.bold is True  # emphasis


# -- Validation --


class TestValidation:
    """Tests for slide collection validation."""

    def _make_slide(self, id, group="", order=0, max_zoom=0, zoom_sections=None):
        return ParsedSlide(
            id=id,
            title=id,
            group=group,
            order=order,
            max_zoom=max_zoom,
            zoom_sections=zoom_sections or ({i: [] for i in range(max_zoom + 1)} if max_zoom > 0 else {}),
        )

    def test_valid_slides(self):
        """Valid slide collection passes validation."""
        slides = {
            "intro": self._make_slide("intro"),
            "cell": self._make_slide("cell", "primitives", 1),
            "style": self._make_slide("style", "primitives", 2),
        }
        validate_slides(slides)  # should not raise

    def test_unknown_group(self):
        """Unknown group raises validation error."""
        slides = {"x": self._make_slide("x", group="invalid")}
        with pytest.raises(SlideValidationError, match="unknown group"):
            validate_slides(slides)

    def test_non_contiguous_zoom(self):
        """Gap in zoom levels raises validation error."""
        slide = ParsedSlide(
            id="bad",
            title="bad",
            max_zoom=2,
            zoom_sections={0: [], 2: []},  # missing level 1
        )
        with pytest.raises(SlideValidationError, match="missing zoom level"):
            validate_slides({"bad": slide})

    def test_duplicate_group_order(self):
        """Duplicate (group, order) pair raises validation error."""
        slides = {
            "a": self._make_slide("a", "primitives", 1),
            "b": self._make_slide("b", "primitives", 1),
        }
        with pytest.raises(SlideValidationError, match="duplicate order"):
            validate_slides(slides)

    def test_standalone_no_group_validation(self):
        """Slides with empty group skip group/order duplicate checks."""
        slides = {
            "intro": self._make_slide("intro"),
            "fin": self._make_slide("fin"),
        }
        validate_slides(slides)  # both have order=0, group="" — should not raise


# -- Auto-Navigation --


class TestNavigation:
    """Tests for auto-navigation computation."""

    def _make_slide(self, id, group="", order=0):
        return ParsedSlide(id=id, title=id, group=group, order=order)

    def test_intro_first_fin_last(self):
        """Intro appears first, fin appears last in sequence."""
        slides = {
            "fin": self._make_slide("fin"),
            "cell": self._make_slide("cell", "primitives", 1),
            "intro": self._make_slide("intro"),
        }
        seq = get_navigation_sequence(slides)
        assert seq[0] == "intro"
        assert seq[-1] == "fin"

    def test_group_ordering(self):
        """Slides are ordered by GROUP_ORDER then by order within group."""
        slides = {
            "compose": self._make_slide("compose", "composition", 1),
            "cell": self._make_slide("cell", "primitives", 1),
            "style": self._make_slide("style", "primitives", 2),
            "app": self._make_slide("app", "application", 1),
        }
        seq = get_navigation_sequence(slides)
        assert seq == ["cell", "style", "compose", "app"]

    def test_left_right_navigation(self):
        """Adjacent slides have correct left/right links."""
        slides = {
            "a": self._make_slide("a", "primitives", 1),
            "b": self._make_slide("b", "primitives", 2),
            "c": self._make_slide("c", "primitives", 3),
        }
        nav = build_navigation(slides)
        assert nav["a"]["left"] is None
        assert nav["a"]["right"] == "b"
        assert nav["b"]["left"] == "a"
        assert nav["b"]["right"] == "c"
        assert nav["c"]["left"] == "b"
        assert nav["c"]["right"] is None

    def test_full_sequence_with_groups(self):
        """Complete sequence respects group boundaries."""
        slides = {
            "intro": self._make_slide("intro"),
            "cell": self._make_slide("cell", "primitives", 1),
            "block": self._make_slide("block", "composition", 1),
            "app": self._make_slide("app", "application", 1),
            "spinner": self._make_slide("spinner", "components", 1),
            "fin": self._make_slide("fin"),
        }
        seq = get_navigation_sequence(slides)
        assert seq == ["intro", "cell", "block", "app", "spinner", "fin"]


# -- File Loading --


class TestLoadSlideMd:
    """Tests for loading individual markdown files."""

    def test_load_single_slide(self, tmp_path):
        """Loads a markdown file into a ParsedSlide."""
        md = tmp_path / "test.md"
        md.write_text("---\nid: test\ntitle: Test\ngroup: primitives\norder: 1\n---\n\n# Test\n\nhello world")
        slide = load_slide_md(md)
        assert slide.id == "test"
        assert slide.title == "Test"
        assert slide.group == "primitives"
        assert slide.order == 1
        assert len(slide.common_sections) == 1

    def test_id_fallback_to_stem(self, tmp_path):
        """ID falls back to filename stem when not in frontmatter."""
        md = tmp_path / "myslide.md"
        md.write_text("---\ntitle: Slide\n---\n\n# Slide\n\ntext")
        slide = load_slide_md(md)
        assert slide.id == "myslide"

    def test_title_fallback_to_heading(self, tmp_path):
        """Title falls back to h1 when not in frontmatter."""
        md = tmp_path / "test.md"
        md.write_text("---\nid: test\n---\n\n# Heading Title\n\ntext")
        slide = load_slide_md(md)
        assert slide.title == "Heading Title"

    def test_align_from_frontmatter(self, tmp_path):
        """Align field is read from frontmatter."""
        md = tmp_path / "test.md"
        md.write_text("---\nid: test\nalign: center\n---\n\n# Test\n\ntext")
        slide = load_slide_md(md)
        assert slide.align == "center"
        assert slide.common_sections[0]["center"] is True

    def test_zoom_levels_loaded(self, tmp_path):
        """Zoom markers are parsed into zoom_sections."""
        md = tmp_path / "test.md"
        md.write_text(
            "---\nid: test\n---\n\n# Test\n\n"
            "common\n\n"
            "[zoom:0]\n\nzero\n\n"
            "[zoom:1]\n\none\n"
        )
        slide = load_slide_md(md)
        assert len(slide.common_sections) == 1
        assert slide.max_zoom == 1
        assert 0 in slide.zoom_sections
        assert 1 in slide.zoom_sections


class TestLoadSlidesDir:
    """Tests for loading a directory of slides."""

    def test_loads_recursive(self, tmp_path):
        """Loads slides from subdirectories."""
        sub = tmp_path / "group"
        sub.mkdir()
        (tmp_path / "intro.md").write_text("---\nid: intro\n---\n\n# Intro")
        (sub / "cell.md").write_text("---\nid: cell\n---\n\n# Cell")
        slides = load_slides_dir(tmp_path)
        assert len(slides) == 2
        assert "intro" in slides
        assert "cell" in slides

    def test_duplicate_id_raises(self, tmp_path):
        """Duplicate slide IDs across files raise an error."""
        (tmp_path / "a.md").write_text("---\nid: same\n---\n\n# A")
        (tmp_path / "b.md").write_text("---\nid: same\n---\n\n# B")
        with pytest.raises(SlideValidationError, match="Duplicate slide ID"):
            load_slides_dir(tmp_path)


# -- Integration --


class TestIntegration:
    """Integration tests loading the actual slides directory."""

    SLIDES_DIR = Path(__file__).resolve().parent.parent / "demos" / "slides"

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "demos" / "slides").exists(),
        reason="slides directory not present",
    )
    def test_load_all_slides(self):
        """All slides load, validate, and have connected navigation."""
        slides = load_slides_dir(self.SLIDES_DIR)
        validate_slides(slides)

        assert len(slides) == 17

        nav = build_navigation(slides)
        seq = get_navigation_sequence(slides)

        # First and last
        assert seq[0] == "intro"
        assert seq[-1] == "fin"

        # All slides in sequence
        assert set(seq) == set(slides.keys())

        # Navigation is connected (no orphans)
        for i, sid in enumerate(seq):
            if i > 0:
                assert nav[sid]["left"] == seq[i - 1]
            if i < len(seq) - 1:
                assert nav[sid]["right"] == seq[i + 1]

    @pytest.mark.skipif(
        not (Path(__file__).resolve().parent.parent / "demos" / "slides").exists(),
        reason="slides directory not present",
    )
    def test_group_order_correct(self):
        """Slides are ordered by group, then by order within group."""
        slides = load_slides_dir(self.SLIDES_DIR)
        seq = get_navigation_sequence(slides)

        # After intro, groups should appear in GROUP_ORDER
        # Find first slide of each group in sequence
        group_first_idx = {}
        for i, sid in enumerate(seq):
            g = slides[sid].group
            if g and g not in group_first_idx:
                group_first_idx[g] = i

        group_positions = [group_first_idx.get(g, -1) for g in GROUP_ORDER if g in group_first_idx]
        assert group_positions == sorted(group_positions), "Groups should appear in GROUP_ORDER"
