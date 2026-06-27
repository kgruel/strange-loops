"""Population command wiring + row-add error paths.

Post-Phase-3 the population machinery is much narrower: `loops add/rm
<vertex> row K V` writes directly to the .list file via lang.population
helpers — no facts, no fold materialization. Most of the previous test
surface tested the retired pop-fact path; that's now covered by
test_add_declarations.py / test_rm_declarations.py / test_ls_unified.py.

What remains here:
  * Dispatcher wiring smoke checks
  * The error-path cases unique to the row-add direct-write path
"""

from __future__ import annotations

from pathlib import Path



# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------


class TestDispatcherWiring:
    def test_run_ls_is_importable(self):
        from loops.main import _run_ls
        assert callable(_run_ls)

    def test_run_add_is_importable(self):
        from loops.main import _run_add
        assert callable(_run_add)

    def test_run_rm_is_importable(self):
        from loops.main import _run_rm
        assert callable(_run_rm)

    def test_run_export_returns_retirement_message(self, capsys):
        from loops.main import _run_export
        rc = _run_export([])
        assert rc != 0
        err = capsys.readouterr().err
        assert "retired" in err.lower()


# ---------------------------------------------------------------------------
# Row-add direct-write error paths
# ---------------------------------------------------------------------------


def _make_vertex_with_template(home: Path) -> Path:
    """Vertex with a file-backed template population, but no .list yet."""
    reading = home / "reading"
    reading.mkdir(parents=True)
    (reading / "sources").mkdir()
    (reading / "sources" / "feed.loop").write_text(
        'kind "feed"\nobserver "feed"\nsource "curl -s {{feed_url}}"\n'
    )
    (reading / "reading.vertex").write_text(
        'name "reading"\n'
        'store "./data/reading.db"\n'
        'sources {\n'
        '  template "./sources/feed.loop" {\n'
        '    from file "./feeds.list"\n'
        '    loop { fold { items "by" "link" } }\n'
        '  }\n'
        '}\n'
    )
    return reading


def _make_bare_vertex(home: Path) -> None:
    """Vertex with no template sources."""
    bare = home / "bare"
    bare.mkdir(parents=True)
    (bare / "bare.vertex").write_text(
        'name "bare"\n'
        'store "./data/bare.db"\n'
        'loops { thread { fold { items "by" "name" } } }\n'
    )


class TestRowAddErrorPaths:
    def test_add_row_no_template_vertex(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        _make_bare_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_add
        rc = _run_add(["bare", "row", "key", "value"])
        assert rc != 0
        assert "Error" in capsys.readouterr().err

    def test_add_row_no_list_header(
        self, tmp_path, monkeypatch, capsys
    ):
        """Empty .list file (no header) errors cleanly."""
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text("")  # empty, no header
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_add
        rc = _run_add(["reading", "row", "key", "value"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "no .list header" in err

    def test_add_row_wrong_column_count(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_add
        rc = _run_add(["reading", "row", "onlyone"])  # missing feed_url value
        assert rc != 0
        err = capsys.readouterr().err
        assert "expected" in err

    def test_add_row_explicit_subcommand_writes_to_list(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_add
        rc = _run_add(["reading", "row", "lobsters", "https://lobste.rs/rss"])
        assert rc == 0
        content = (reading / "feeds.list").read_text()
        assert "lobsters" in content
        assert "https://lobste.rs/rss" in content

    def test_add_row_bare_positional_backcompat(
        self, tmp_path, monkeypatch, capsys
    ):
        """`loops add reading lobsters URL` (no `row` keyword) — implicit row."""
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text("kind feed_url\n")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_add
        rc = _run_add(["reading", "lobsters", "https://lobste.rs/rss"])
        assert rc == 0
        assert "lobsters" in (reading / "feeds.list").read_text()


class TestRowRmErrorPaths:
    def test_rm_row_missing_key_in_list(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text(
            "kind feed_url\nlobsters https://lobste.rs/rss\n"
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_rm
        rc = _run_rm(["reading", "row", "ghost"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "no row matching" in err

    def test_rm_row_present(
        self, tmp_path, monkeypatch, capsys
    ):
        home = tmp_path / "home"
        home.mkdir()
        reading = _make_vertex_with_template(home)
        (reading / "feeds.list").write_text(
            "kind feed_url\n"
            "lobsters https://lobste.rs/rss\n"
            "danluu https://danluu.com/atom.xml\n"
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))

        from loops.main import _run_rm
        rc = _run_rm(["reading", "row", "lobsters"])
        assert rc == 0
        content = (reading / "feeds.list").read_text()
        assert "lobsters" not in content
        assert "danluu" in content
