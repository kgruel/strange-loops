"""Tests for population management CLI commands."""

from pathlib import Path

import pytest

from loops.main import create_parser, main


# ---------------------------------------------------------------------------
# Target parsing
# ---------------------------------------------------------------------------


class TestParseTarget:
    def test_simple_name(self):
        from loops.commands.pop import parse_target

        assert parse_target("reading") == ("reading", None)

    def test_qualified(self):
        from loops.commands.pop import parse_target

        assert parse_target("economy/fred") == ("economy", "fred")

    def test_vertex_extension(self):
        from loops.commands.pop import parse_target

        assert parse_target("feeds.vertex") == ("feeds.vertex", None)

    def test_dotslash_path(self):
        from loops.commands.pop import parse_target

        assert parse_target("./my.vertex") == ("./my.vertex", None)

    def test_absolute_path(self):
        from loops.commands.pop import parse_target

        assert parse_target("/tmp/test.vertex") == ("/tmp/test.vertex", None)


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


class TestParserWiring:
    def test_ls_parser(self):
        parser = create_parser()
        args = parser.parse_args(["ls", "reading"])
        assert args.command == "ls"
        assert args.target == "reading"

    def test_add_parser(self):
        parser = create_parser()
        args = parser.parse_args(
            ["add", "reading", "lobsters", "https://lobste.rs/rss"]
        )
        assert args.command == "add"
        assert args.target == "reading"
        assert args.values == ["lobsters", "https://lobste.rs/rss"]

    def test_rm_parser(self):
        parser = create_parser()
        args = parser.parse_args(["rm", "reading", "lobsters"])
        assert args.command == "rm"
        assert args.target == "reading"
        assert args.key == "lobsters"

    def test_export_parser(self):
        parser = create_parser()
        args = parser.parse_args(["export", "reading"])
        assert args.command == "export"
        assert args.target == "reading"

    def test_export_with_output(self):
        parser = create_parser()
        args = parser.parse_args(["export", "reading", "-o", "my.list"])
        assert args.output == "my.list"

    def test_import_parser(self):
        parser = create_parser()
        args = parser.parse_args(["import", "reading"])
        assert args.command == "import"
        assert args.target == "reading"

    def test_merge_parser(self):
        parser = create_parser()
        args = parser.parse_args(["merge", "reading", "external.list"])
        assert args.command == "merge"
        assert args.file == "external.list"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERTEX_FILE_BACKED = """\
name "reading"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold { count "inc" }
      boundary when="${kind}.complete"
    }
  }
}
"""

_VERTEX_INLINE = """\
name "status"
sources {
  template "stacks/status.loop" {
    with kind="infra" host="192.168.1.30"
    with kind="media" host="192.168.1.40"
    loop {
      fold { containers "collect" 50 }
      boundary when="${kind}.complete"
    }
  }
}
"""


def _setup_file_backed(home: Path) -> Path:
    """Create a file-backed vertex under home/reading/."""
    reading = home / "reading"
    reading.mkdir(parents=True)
    (reading / "reading.vertex").write_text(_VERTEX_FILE_BACKED)
    (reading / "feeds.list").write_text(
        "kind feed_url\nlobsters https://lobste.rs/rss\n"
    )
    (reading / "sources").mkdir()
    (reading / "sources" / "feed.loop").write_text(
        'source "curl"\nkind "${kind}"\nobserver "feed"\n'
    )
    return reading


def _setup_inline(home: Path) -> Path:
    """Create an inline-populated vertex under home/status/."""
    status = home / "status"
    status.mkdir(parents=True)
    (status / "status.vertex").write_text(_VERTEX_INLINE)
    return status


# ---------------------------------------------------------------------------
# ls command
# ---------------------------------------------------------------------------


class TestLsCommand:
    def test_ls_file_backed(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["ls", "reading"])
        assert result == 0
        captured = capsys.readouterr()
        assert "lobsters" in captured.out
        assert "feed_url" in captured.out

    def test_ls_inline(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_inline(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["ls", "status"])
        assert result == 0
        captured = capsys.readouterr()
        assert "infra" in captured.out
        assert "media" in captured.out

    def test_ls_vertex_not_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["ls", "nope"])
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_ls_multi_template_requires_qualifier(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        multi = home / "economy"
        multi.mkdir(parents=True)
        (multi / "economy.vertex").write_text(
            'name "economy"\n'
            "sources {\n"
            '  template "./sources/fred.loop" {\n'
            '    with kind="FEDFUNDS"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete" }\n'
            "  }\n"
            '  template "./sources/bls.loop" {\n'
            '    with kind="CPI"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="${kind}.complete" }\n'
            "  }\n"
            "}\n"
            "loops { top { fold { count \"inc\" } } }\n"
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Without qualifier: error
        result = main(["ls", "economy"])
        assert result == 1
        captured = capsys.readouterr()
        assert "2 templates" in captured.err

        # With qualifier: success
        result = main(["ls", "economy/fred"])
        assert result == 0
        captured = capsys.readouterr()
        assert "FEDFUNDS" in captured.out


# ---------------------------------------------------------------------------
# add command
# ---------------------------------------------------------------------------


class TestAddCommand:
    def test_add_to_list_file(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            ["add", "reading", "danluu", "https://danluu.com/atom.xml"]
        )
        assert result == 0
        captured = capsys.readouterr()
        assert "Added danluu" in captured.out

        content = (reading / "feeds.list").read_text()
        assert "danluu" in content

    def test_add_duplicate(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            ["add", "reading", "lobsters", "https://other.com"]
        )
        assert result == 1
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_add_wrong_column_count(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["add", "reading", "only_key"])
        assert result == 1
        captured = capsys.readouterr()
        assert "expected 2" in captured.err

    def test_add_last_column_remainder(self, tmp_path, monkeypatch, capsys):
        """Extra args get joined into last column."""
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            ["add", "reading", "test", "https://example.com/rss?a=1", "extra"]
        )
        assert result == 0
        content = (reading / "feeds.list").read_text()
        assert "https://example.com/rss?a=1 extra" in content

    def test_add_to_inline(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        status = _setup_inline(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["add", "status", "dev", "192.168.1.50"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Added dev" in captured.out

        content = (status / "status.vertex").read_text()
        assert 'kind="dev"' in content


# ---------------------------------------------------------------------------
# rm command
# ---------------------------------------------------------------------------


class TestRmCommand:
    def test_rm_from_list_file(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        # Add a second feed so we can remove one
        (reading / "feeds.list").write_text(
            "kind feed_url\n"
            "lobsters https://lobste.rs/rss\n"
            "danluu https://danluu.com/atom.xml\n"
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["rm", "reading", "lobsters"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Removed lobsters" in captured.out

        content = (reading / "feeds.list").read_text()
        assert "lobsters" not in content
        assert "danluu" in content

    def test_rm_not_found(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["rm", "reading", "nope"])
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_rm_from_inline(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        status = _setup_inline(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["rm", "status", "infra"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Removed infra" in captured.out

        content = (status / "status.vertex").read_text()
        assert "infra" not in content
        assert "media" in content


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------


class TestExportCommand:
    def test_export_creates_list_file(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        status = _setup_inline(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["export", "status"])
        assert result == 0

        list_path = status / "status.list"
        assert list_path.exists()
        content = list_path.read_text()
        assert "infra" in content
        assert "media" in content

        # Vertex now has from file, no with
        vertex_content = (status / "status.vertex").read_text()
        assert "from file" in vertex_content
        assert "with kind=" not in vertex_content

    def test_export_already_file(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["export", "reading"])
        assert result == 1
        captured = capsys.readouterr()
        assert "Already using" in captured.err


# ---------------------------------------------------------------------------
# import command
# ---------------------------------------------------------------------------


class TestImportCommand:
    def test_import_inlines_rows(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["import", "reading"])
        assert result == 0

        vertex_content = (home / "reading" / "reading.vertex").read_text()
        assert "from file" not in vertex_content
        assert 'with kind="lobsters"' in vertex_content

    def test_import_already_inline(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_inline(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["import", "status"])
        assert result == 1
        captured = capsys.readouterr()
        assert "Already inline" in captured.err


# ---------------------------------------------------------------------------
# merge command
# ---------------------------------------------------------------------------


class TestMergeCommand:
    def test_merge_adds_new_rows(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Create external file
        external = tmp_path / "external.list"
        external.write_text(
            "kind feed_url\n"
            "lobsters https://lobste.rs/rss\n"
            "danluu https://danluu.com/atom.xml\n"
            "hn https://news.ycombinator.com/rss\n"
        )

        result = main(["merge", "reading", str(external)])
        assert result == 0
        captured = capsys.readouterr()
        assert "2 new rows" in captured.out
        assert "1 duplicates skipped" in captured.out

        content = (reading / "feeds.list").read_text()
        assert "danluu" in content
        assert "hn" in content

    def test_merge_file_not_found(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["merge", "reading", "/nonexistent.list"])
        assert result == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err
