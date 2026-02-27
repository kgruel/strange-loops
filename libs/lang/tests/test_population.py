"""Tests for population management."""

from pathlib import Path

import pytest

from lang import parse_vertex, TemplateSource
from lang.population import (
    PopulationRow,
    export_to_file,
    import_from_file,
    kdl_insert_with_row,
    kdl_remove_with_row,
    list_file_add,
    list_file_read,
    list_file_rm,
    list_file_write,
    read_population,
    resolve_template,
    resolve_vertex,
    template_name,
)


# ---------------------------------------------------------------------------
# resolve_vertex
# ---------------------------------------------------------------------------


class TestResolveVertex:
    def test_name_convention(self, tmp_path):
        result = resolve_vertex("reading", tmp_path)
        assert result == tmp_path / "reading" / "reading.vertex"

    def test_explicit_vertex_extension(self):
        result = resolve_vertex("feeds.vertex", Path("/home"))
        assert result == Path("feeds.vertex")

    def test_dotslash_path(self):
        result = resolve_vertex("./my.vertex", Path("/home"))
        assert result == Path("./my.vertex")

    def test_absolute_path(self):
        result = resolve_vertex("/etc/loops/root.vertex", Path("/home"))
        assert result == Path("/etc/loops/root.vertex")

    def test_dotslash_dir(self):
        """Starts with ./ -> treated as path, not name."""
        result = resolve_vertex("./reading", Path("/home"))
        assert result == Path("./reading")


# ---------------------------------------------------------------------------
# resolve_template
# ---------------------------------------------------------------------------


class TestResolveTemplate:
    def _one_template(self):
        return parse_vertex(
            'name "feeds"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    with kind="lobsters" feed_url="https://lobste.rs/rss"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

    def _two_templates(self):
        return parse_vertex(
            'name "economy"\n'
            "sources {\n"
            '  template "./sources/fred.loop" {\n'
            '    with kind="FEDFUNDS"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            '  template "./sources/bls.loop" {\n'
            '    with kind="CPI"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
            "loops {\n"
            "  top { fold { count \"inc\" } }\n"
            "}\n"
        )

    def test_single_no_qualifier(self):
        v = self._one_template()
        t = resolve_template(v, None)
        assert isinstance(t, TemplateSource)
        assert template_name(t) == "feed"

    def test_single_with_qualifier(self):
        v = self._one_template()
        t = resolve_template(v, "feed")
        assert template_name(t) == "feed"

    def test_multi_requires_qualifier(self):
        v = self._two_templates()
        with pytest.raises(ValueError, match="2 templates"):
            resolve_template(v, None)

    def test_multi_with_qualifier(self):
        v = self._two_templates()
        t = resolve_template(v, "fred")
        assert template_name(t) == "fred"

    def test_qualifier_not_found(self):
        v = self._two_templates()
        with pytest.raises(ValueError, match="No template 'nope'"):
            resolve_template(v, "nope")

    def test_no_templates(self):
        v = parse_vertex(
            'name "simple"\n'
            "loops { x { fold { count \"inc\" } } }\n"
        )
        with pytest.raises(ValueError, match="no template sources"):
            resolve_template(v, None)

    def test_duplicate_stem_prefers_file_backed(self):
        """Two templates with same .loop file — prefers the from-file one."""
        v = parse_vertex(
            'name "reading"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    from file "./feeds.list"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete" }\n'
            "  }\n"
            '  template "./sources/feed.loop" {\n'
            '    with kind="rx.hn" feed_url="https://hn.example/rss"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete" }\n'
            "  }\n"
            "}\n"
            "loops { source.error { fold { count \"inc\" } } }\n"
        )
        # No qualifier — resolves to the file-backed template
        t = resolve_template(v, None)
        assert t.from_ is not None

        # Explicit qualifier also works
        t2 = resolve_template(v, "feed")
        assert t2.from_ is not None


# ---------------------------------------------------------------------------
# .list file operations
# ---------------------------------------------------------------------------


class TestListFileOps:
    def test_read(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text(
            "kind feed_url\n"
            "lobsters https://lobste.rs/rss\n"
            "danluu https://danluu.com/atom.xml\n"
        )
        header, rows = list_file_read(f)
        assert header == ["kind", "feed_url"]
        assert len(rows) == 2
        assert rows[0].key == "lobsters"
        assert rows[0].values["feed_url"] == "https://lobste.rs/rss"
        assert rows[1].key == "danluu"

    def test_read_with_comments(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text(
            "# comment\nkind url\n\n# another\nfoo https://foo.com\n"
        )
        header, rows = list_file_read(f)
        assert header == ["kind", "url"]
        assert len(rows) == 1
        assert rows[0].key == "foo"

    def test_read_last_column_remainder(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text("kind url\ntest https://example.com/feed?a=1&b=2\n")
        header, rows = list_file_read(f)
        assert rows[0].values["url"] == "https://example.com/feed?a=1&b=2"

    def test_add_creates_file(self, tmp_path):
        f = tmp_path / "test.list"
        row = PopulationRow(
            key="lobsters",
            values={"kind": "lobsters", "url": "https://lobste.rs/rss"},
        )
        list_file_add(f, ["kind", "url"], row)
        assert f.exists()
        header, rows = list_file_read(f)
        assert header == ["kind", "url"]
        assert len(rows) == 1
        assert rows[0].key == "lobsters"

    def test_add_appends(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text("kind url\nfoo https://foo.com\n")
        row = PopulationRow(
            key="bar", values={"kind": "bar", "url": "https://bar.com"}
        )
        list_file_add(f, ["kind", "url"], row)
        header, rows = list_file_read(f)
        assert len(rows) == 2
        assert rows[1].key == "bar"

    def test_rm_found(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text(
            "kind url\nfoo https://foo.com\nbar https://bar.com\n"
        )
        assert list_file_rm(f, "foo") is True
        header, rows = list_file_read(f)
        assert len(rows) == 1
        assert rows[0].key == "bar"

    def test_rm_not_found(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text("kind url\nfoo https://foo.com\n")
        assert list_file_rm(f, "nope") is False

    def test_rm_preserves_comments(self, tmp_path):
        f = tmp_path / "test.list"
        f.write_text(
            "# feeds\nkind url\nfoo https://foo.com\nbar https://bar.com\n"
        )
        list_file_rm(f, "foo")
        content = f.read_text()
        assert "# feeds" in content
        assert "bar" in content
        assert "foo https://" not in content

    def test_rm_preserves_header(self, tmp_path):
        """Header line is never removed even if first column matches."""
        f = tmp_path / "test.list"
        f.write_text("kind url\nkind_data https://data.com\n")
        list_file_rm(f, "kind_data")
        header, rows = list_file_read(f)
        assert header == ["kind", "url"]
        assert len(rows) == 0

    def test_write(self, tmp_path):
        f = tmp_path / "test.list"
        rows = [
            PopulationRow(
                key="a", values={"kind": "a", "url": "https://a.com"}
            ),
            PopulationRow(
                key="b", values={"kind": "b", "url": "https://b.com"}
            ),
        ]
        list_file_write(f, ["kind", "url"], rows)
        header, read_rows = list_file_read(f)
        assert header == ["kind", "url"]
        assert len(read_rows) == 2

    def test_rm_nonexistent_file(self, tmp_path):
        f = tmp_path / "missing.list"
        assert list_file_rm(f, "foo") is False


# ---------------------------------------------------------------------------
# read_population
# ---------------------------------------------------------------------------


class TestReadPopulation:
    def test_file_only(self, tmp_path):
        list_file = tmp_path / "feeds.list"
        list_file.write_text(
            "kind feed_url\nlobsters https://lobste.rs/rss\n"
        )

        vertex = parse_vertex(
            'name "feeds"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    from file "./feeds.list"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        t = resolve_template(vertex, None)
        pop = read_population(vertex, t, tmp_path)
        assert pop.storage == "file"
        assert len(pop.rows) == 1
        assert pop.rows[0].key == "lobsters"
        assert pop.header == ["kind", "feed_url"]

    def test_inline_only(self, tmp_path):
        vertex = parse_vertex(
            'name "status"\n'
            "sources {\n"
            '  template "stacks/status.loop" {\n'
            '    with kind="infra" host="192.168.1.30"\n'
            '    with kind="media" host="192.168.1.40"\n'
            "    loop {\n"
            '      fold { containers "collect" 50 }\n'
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        t = resolve_template(vertex, None)
        pop = read_population(vertex, t, tmp_path)
        assert pop.storage == "inline"
        assert len(pop.rows) == 2
        assert pop.rows[0].key == "infra"
        assert pop.header == ["kind", "host"]

    def test_both(self, tmp_path):
        list_file = tmp_path / "feeds.list"
        list_file.write_text(
            "kind feed_url\nlobsters https://lobste.rs/rss\n"
        )

        vertex = parse_vertex(
            'name "feeds"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    from file "./feeds.list"\n'
            '    with kind="pinned" feed_url="https://pinned.com/rss"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        t = resolve_template(vertex, None)
        pop = read_population(vertex, t, tmp_path)
        assert pop.storage == "both"
        assert len(pop.rows) == 2
        assert pop.rows[0].key == "lobsters"  # file first
        assert pop.rows[1].key == "pinned"  # inline second

    def test_empty_population(self, tmp_path):
        list_file = tmp_path / "feeds.list"
        list_file.write_text("kind feed_url\n")  # header only

        vertex = parse_vertex(
            'name "feeds"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    from file "./feeds.list"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        t = resolve_template(vertex, None)
        pop = read_population(vertex, t, tmp_path)
        assert pop.storage == "file"
        assert len(pop.rows) == 0
        assert pop.header == ["kind", "feed_url"]


# ---------------------------------------------------------------------------
# KDL text manipulation
# ---------------------------------------------------------------------------


_VERTEX_WITH_INLINE = """\
name "feeds"
store "./data/feeds.db"

sources {
  template "./sources/feed.loop" {
    with kind="lobsters" feed_url="https://lobste.rs/rss"
    with kind="danluu" feed_url="https://danluu.com/atom.xml"
    loop {
      fold {
        items "by" "link"
        count "inc"
      }
      boundary when="${kind}.complete"
    }
  }
}

emit "feeds.digest"
"""


class TestKdlTextOps:
    def test_insert_with_row(self):
        result = kdl_insert_with_row(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            {"kind": "hn", "feed_url": "https://news.ycombinator.com/rss"},
        )
        assert 'with kind="hn"' in result
        # Should appear after existing with rows
        lines = result.splitlines()
        hn_idx = next(i for i, l in enumerate(lines) if 'kind="hn"' in l)
        danluu_idx = next(
            i for i, l in enumerate(lines) if 'kind="danluu"' in l
        )
        assert hn_idx > danluu_idx

    def test_insert_preserves_indentation(self):
        result = kdl_insert_with_row(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            {"kind": "hn", "feed_url": "https://hn.com/rss"},
        )
        lines = result.splitlines()
        hn_line = next(l for l in lines if 'kind="hn"' in l)
        danluu_line = next(l for l in lines if 'kind="danluu"' in l)
        # Same leading whitespace
        assert hn_line[: len(hn_line) - len(hn_line.lstrip())] == danluu_line[
            : len(danluu_line) - len(danluu_line.lstrip())
        ]

    def test_remove_with_row(self):
        result = kdl_remove_with_row(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            "kind",
            "lobsters",
        )
        assert "lobsters" not in result
        assert "danluu" in result

    def test_remove_not_found(self):
        with pytest.raises(ValueError, match="No with row matching"):
            kdl_remove_with_row(
                _VERTEX_WITH_INLINE,
                "./sources/feed.loop",
                "kind",
                "nonexistent",
            )

    def test_insert_preserves_trailing_newline(self):
        result = kdl_insert_with_row(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            {"kind": "test", "feed_url": "https://test.com"},
        )
        assert result.endswith("\n")

    def test_remove_preserves_trailing_newline(self):
        result = kdl_remove_with_row(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            "kind",
            "lobsters",
        )
        assert result.endswith("\n")


# ---------------------------------------------------------------------------
# Export / Import
# ---------------------------------------------------------------------------


class TestExportImport:
    def test_export_removes_with_adds_from(self, tmp_path):
        result = export_to_file(
            _VERTEX_WITH_INLINE,
            "./sources/feed.loop",
            "./feed.list",
        )
        assert 'from file "./feed.list"' in result
        assert "with kind=" not in result
        # Loop spec preserved
        assert 'items "by" "link"' in result
        assert "boundary" in result

    def test_import_removes_from_adds_with(self):
        vertex_text = (
            'name "feeds"\n'
            "sources {\n"
            '  template "./sources/feed.loop" {\n'
            '    from file "./feeds.list"\n'
            "    loop {\n"
            "      fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        rows = [
            PopulationRow(
                key="lobsters",
                values={
                    "kind": "lobsters",
                    "feed_url": "https://lobste.rs/rss",
                },
            ),
            PopulationRow(
                key="danluu",
                values={
                    "kind": "danluu",
                    "feed_url": "https://danluu.com/atom.xml",
                },
            ),
        ]
        result = import_from_file(
            vertex_text, "./sources/feed.loop", rows
        )
        assert "from file" not in result
        assert 'with kind="lobsters"' in result
        assert 'with kind="danluu"' in result
        # Loop spec preserved
        assert "boundary" in result

    def test_roundtrip(self, tmp_path):
        """Export then import recovers original population."""
        vertex_text = _VERTEX_WITH_INLINE

        # Export: inline -> file ref
        exported = export_to_file(
            vertex_text, "./sources/feed.loop", "./feed.list"
        )
        assert "with kind=" not in exported
        assert "from file" in exported

        # Write the .list file (simulating what CLI does)
        list_path = tmp_path / "feed.list"
        rows = [
            PopulationRow(
                key="lobsters",
                values={
                    "kind": "lobsters",
                    "feed_url": "https://lobste.rs/rss",
                },
            ),
            PopulationRow(
                key="danluu",
                values={
                    "kind": "danluu",
                    "feed_url": "https://danluu.com/atom.xml",
                },
            ),
        ]
        list_file_write(list_path, ["kind", "feed_url"], rows)

        # Import: file -> inline
        imported = import_from_file(
            exported, "./sources/feed.loop", rows
        )
        assert "from file" not in imported
        assert 'with kind="lobsters"' in imported
        assert 'with kind="danluu"' in imported

    def test_export_preserves_loop_spec(self):
        vertex_text = (
            'name "test"\n'
            "sources {\n"
            '  template "stacks/status.loop" {\n'
            '    with kind="infra" host="192.168.1.30"\n'
            "    loop {\n"
            '      fold { containers "collect" 50 }\n'
            '      boundary when="${kind}.complete"\n'
            "    }\n"
            "  }\n"
            "}\n"
            'emit "test"\n'
        )
        result = export_to_file(
            vertex_text, "stacks/status.loop", "./status.list"
        )
        assert 'containers "collect" 50' in result
        assert "boundary" in result
        assert 'emit "test"' in result
