"""Tests for the sync CLI verb."""

from pathlib import Path

from loops.main import main


def _make_vertex_with_source(tmp_path: Path, *, name: str = "test") -> Path:
    """Create a vertex with an echo source that produces output."""
    vertex_dir = tmp_path / name
    vertex_dir.mkdir()

    # Create a .loop file
    loop_file = vertex_dir / "ping.loop"
    loop_file.write_text(
        'source "echo ok"\n'
        f'kind "{name}"\n'
        'observer "test"\n'
    )

    # Create vertex that references the loop via sources block
    (vertex_dir / f"{name}.vertex").write_text(
        f'name "{name}"\n'
        f'store "./data/{name}.db"\n\n'
        'sources {\n'
        '  path "./ping.loop"\n'
        '}\n\n'
        "loops {\n"
        f"  {name} {{\n"
        '    fold {\n'
        '      count "inc"\n'
        "    }\n"
        f'    boundary when="{name}.complete"\n'
        "  }\n"
        "}\n"
    )

    return vertex_dir / f"{name}.vertex"


def _make_vertex_no_sources(tmp_path: Path) -> Path:
    """Create a vertex with no sources."""
    vertex_dir = tmp_path / "empty"
    vertex_dir.mkdir()
    (vertex_dir / "empty.vertex").write_text(
        'name "empty"\n'
        'store "./data/empty.db"\n\n'
        "loops {\n"
        '  thing { fold { count "inc" } }\n'
        "}\n"
    )
    return vertex_dir / "empty.vertex"


def _block_to_text(block) -> str:
    """Extract plain text from a Block."""
    lines = []
    for row_idx in range(block.height):
        line = "".join(cell.char for cell in block.row(row_idx))
        lines.append(line.rstrip())
    return "\n".join(lines)


class TestSyncDispatch:
    """Sync verb dispatches correctly in all tiers."""

    def test_sync_in_verbs(self):
        from loops.main import _VERBS
        assert "sync" in _VERBS

    def test_sync_in_vertex_ops(self):
        from loops.main import _VERTEX_OPS
        assert "sync" in _VERTEX_OPS

    def test_sync_verb_no_vertex_errors(self, monkeypatch, tmp_path):
        """loops sync with no vertex and no local .vertex errors."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        result = main(["sync"])
        assert result == 1

    def test_sync_unknown_vertex_errors(self, monkeypatch, tmp_path):
        """loops sync nonexistent errors."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["sync", "nonexistent"])
        assert result == 1

    def test_sync_no_sources_errors(self, monkeypatch, tmp_path, capsys):
        """loops sync on a vertex with no sources errors."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_no_sources(tmp_path)

        from loops.main import _run_sync

        result = _run_sync([], vertex_path=vertex_path)
        assert result == 1
        captured = capsys.readouterr()
        assert "No sources" in captured.err


class TestSyncExecution:
    """Sync executes sources and renders output."""

    def test_sync_force_runs_all(self, monkeypatch, tmp_path, capsys):
        """loops sync <vertex> --force runs all sources."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["--force"], vertex_path=vertex_path)
        assert result == 0

    def test_sync_default_is_cadence_gated(self, monkeypatch, tmp_path, capsys):
        """Default sync evaluates cadence (first run = always runs)."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync([], vertex_path=vertex_path)
        assert result == 0

    def test_sync_force_flag_short(self, monkeypatch, tmp_path, capsys):
        """-f is shorthand for --force."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["-f"], vertex_path=vertex_path)
        assert result == 0

    def test_sync_stderr_shows_label(self, monkeypatch, tmp_path, capsys):
        """Sync status message shows force vs cadence-gated."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        _run_sync(["--force"], vertex_path=vertex_path)
        captured = capsys.readouterr()
        assert "force" in captured.err

    def test_sync_cadence_gated_label(self, monkeypatch, tmp_path, capsys):
        """Non-force sync shows cadence-gated label."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        _run_sync([], vertex_path=vertex_path)
        captured = capsys.readouterr()
        assert "cadence-gated" in captured.err


class TestSyncVertexResolution:
    """Sync resolves vertices through standard resolution chain."""

    def test_sync_by_name(self, monkeypatch, tmp_path, capsys):
        """loops sync <name> resolves via LOOPS_HOME."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        _make_vertex_with_source(tmp_path)
        result = main(["sync", "test", "--force"])
        assert result == 0

    def test_sync_vertex_first(self, monkeypatch, tmp_path, capsys):
        """loops <vertex> sync routes through _dispatch_observer."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        _make_vertex_with_source(tmp_path, name="myvert")
        result = main(["myvert", "sync", "--force"])
        assert result == 0


class TestSyncHelp:
    """Help text includes sync."""

    def test_main_help_shows_sync(self, capsys):
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "sync" in captured.out
        assert "cadence" in captured.out.lower()


class TestSyncLens:
    """Sync lens renders SyncResult data."""

    def test_sync_view_minimal_ran(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": ["ping"], "skipped": [], "errors": [], "ticks": []}
        block = sync_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "1 ran" in text

    def test_sync_view_with_skipped(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": ["ping"], "skipped": ["health"], "errors": [], "ticks": []}
        block = sync_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "Ran:" in text
        assert "Skipped:" in text

    def test_sync_view_no_sources(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": [], "skipped": [], "errors": [], "ticks": []}
        block = sync_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "No sources" in text

    def test_sync_view_with_errors(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {
            "ran": ["ping"],
            "skipped": [],
            "errors": [{"kind": "source.error", "observer": "test", "payload": {"error": "timeout"}}],
            "ticks": [],
        }
        block = sync_view(data, Zoom.DETAILED, 80)
        text = _block_to_text(block)
        assert "Errors:" in text
        assert "timeout" in text

    def test_sync_view_minimal_nothing(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": [], "skipped": [], "errors": [], "ticks": []}
        block = sync_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "nothing to sync" in text
