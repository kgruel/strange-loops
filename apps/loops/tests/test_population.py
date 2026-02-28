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

    def test_import_removed(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["import", "reading"])

    def test_merge_removed(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["merge", "reading", "external.list"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VERTEX_FILE_BACKED = """\
name "reading"
store "./data/reading.db"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
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
        'source "curl"\nkind "{{kind}}"\nobserver "feed"\n'
    )
    return reading


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

    def test_ls_queries_store_when_present(self, tmp_path, monkeypatch, capsys):
        """ls should be a fold over pop facts (not a read of .list rows)."""
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        # Start from an empty list file so bootstrap doesn't seed.
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "emit",
                "reading",
                "pop.add",
                "key=lobsters",
                "feed_url=https://lobste.rs/rss",
            ]
        )
        assert result == 0

        # Corrupt the materialized view; ls should still show store state.
        (reading / "feeds.list").write_text("kind feed_url\n")
        result = main(["ls", "reading"])
        assert result == 0
        captured = capsys.readouterr()
        assert "lobsters" in captured.out

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
            'store "./data/economy.db"\n'
            "sources {\n"
            '  template "./sources/fred.loop" {\n'
            '    from file "./fred.list"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="{{kind}}.complete" }\n'
            "  }\n"
            '  template "./sources/bls.loop" {\n'
            '    from file "./bls.list"\n'
            "    loop { fold { count \"inc\" }\n"
            '      boundary when="{{kind}}.complete" }\n'
            "  }\n"
            "}\n"
            "loops { top { fold { count \"inc\" } } }\n"
        )
        (multi / "fred.list").write_text("kind series\nFEDFUNDS FEDFUNDS\n")
        (multi / "bls.list").write_text("kind series\nCPI CPI\n")
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
        assert "Emitted pop.add danluu" in captured.out

        content = (reading / "feeds.list").read_text()
        assert "danluu" in content

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
        assert "Emitted pop.rm lobsters" in captured.out

        content = (reading / "feeds.list").read_text()
        assert "lobsters" not in content
        assert "danluu" in content

    def test_rm_not_found(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["rm", "reading", "nope"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Emitted pop.rm nope" in captured.out
        # No change to materialized list
        content = (reading / "feeds.list").read_text()
        assert "lobsters" in content


# ---------------------------------------------------------------------------
# export command
# ---------------------------------------------------------------------------


class TestExportCommand:
    def test_export_rematerializes_from_store(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "emit",
                "reading",
                "pop.add",
                "key=lobsters",
                "feed_url=https://lobste.rs/rss",
            ]
        )
        assert result == 0

        # Corrupt view, then export should rebuild it from store.
        (reading / "feeds.list").write_text("kind feed_url\n")
        result = main(["export", "reading"])
        assert result == 0
        content = (reading / "feeds.list").read_text()
        assert "lobsters" in content

    def test_emit_pop_rm_materializes(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        reading = _setup_file_backed(home)
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "emit",
                "reading",
                "pop.add",
                "key=lobsters",
                "feed_url=https://lobste.rs/rss",
            ]
        )
        assert result == 0
        assert "lobsters" in (reading / "feeds.list").read_text()

        result = main(["emit", "reading", "pop.rm", "key=lobsters"])
        assert result == 0
        content = (reading / "feeds.list").read_text()
        assert "lobsters" not in content
