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

    def test_sync_emits_completion_fact(self, monkeypatch, tmp_path, capsys):
        """Sync stores a sync.complete fact with expected fields."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from engine import load_vertex_program

        program = load_vertex_program(vertex_path)
        program.sync(force=True)

        from engine import StoreReader

        store_path = vertex_path.parent / "data" / "test.db"
        reader = StoreReader(store_path)
        facts = reader.recent_facts("sync.complete", 5)
        assert len(facts) == 1
        f = facts[0]
        assert f["payload"]["status"] == "ok"
        assert f["payload"]["sources_run"] == 1
        assert f["payload"]["sources_skipped"] == 0
        assert f["payload"]["total_facts"] > 0
        assert "duration_ms" in f["payload"]

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

    def test_sync_view_minimal_shows_fact_count(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": ["ping"], "skipped": [], "errors": [], "ticks": [],
                "fact_counts": {"ping": 3}}
        block = sync_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "3 facts" in text

    def test_sync_view_summary_shows_per_source_counts(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": ["ping", "health"], "skipped": [], "errors": [], "ticks": [],
                "fact_counts": {"ping": 3, "health": 1}}
        block = sync_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "ping (3)" in text
        assert "health (1)" in text

    def test_sync_view_summary_children_per_child_breakdown(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {
            "ran": ["child1", "child2"], "skipped": [], "errors": [], "ticks": [],
            "fact_counts": {"child1": 5, "child2": 3},
            "children": [
                {"name": "child1", "ran": ["child1"], "skipped": [], "fact_counts": {"child1": 5}},
                {"name": "child2", "ran": ["child2"], "skipped": [], "fact_counts": {"child2": 3}},
            ],
        }
        block = sync_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "child1: 5 facts" in text
        assert "child2: 3 facts" in text
        assert "Total: 8 facts" in text

    def test_sync_view_children_skipped(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {
            "ran": ["child1"], "skipped": ["child2"], "errors": [], "ticks": [],
            "fact_counts": {"child1": 2},
            "children": [
                {"name": "c1", "ran": ["child1"], "skipped": [], "fact_counts": {"child1": 2}},
                {"name": "c2", "ran": [], "skipped": ["child2"], "fact_counts": {}},
            ],
        }
        block = sync_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "c1: 2 facts" in text
        assert "c2: skipped" in text

    def test_sync_view_minimal_singular_fact(self):
        from loops.lenses.sync import sync_view
        from painted import Zoom

        data = {"ran": ["ping"], "skipped": [], "errors": [], "ticks": [],
                "fact_counts": {"ping": 1}}
        block = sync_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "1 fact" in text
        assert "1 facts" not in text


def _make_aggregation_vertex(tmp_path: Path) -> Path:
    """Create an aggregation vertex that combines two child instance vertices."""
    # Child 1: has its own source
    child1_dir = tmp_path / "child1"
    child1_dir.mkdir()
    (child1_dir / "ping.loop").write_text(
        'source "echo child1-ok"\n'
        'kind "child1"\n'
        'observer "test"\n'
    )
    (child1_dir / "child1.vertex").write_text(
        'name "child1"\n'
        'store "./data/child1.db"\n\n'
        'sources {\n'
        '  path "./ping.loop"\n'
        '}\n\n'
        "loops {\n"
        "  child1 {\n"
        '    fold { count "inc" }\n'
        '    boundary when="child1.complete"\n'
        "  }\n"
        "}\n"
    )

    # Child 2: has its own source
    child2_dir = tmp_path / "child2"
    child2_dir.mkdir()
    (child2_dir / "ping.loop").write_text(
        'source "echo child2-ok"\n'
        'kind "child2"\n'
        'observer "test"\n'
    )
    (child2_dir / "child2.vertex").write_text(
        'name "child2"\n'
        'store "./data/child2.db"\n\n'
        'sources {\n'
        '  path "./ping.loop"\n'
        '}\n\n'
        "loops {\n"
        "  child2 {\n"
        '    fold { count "inc" }\n'
        '    boundary when="child2.complete"\n'
        "  }\n"
        "}\n"
    )

    # Aggregation vertex: no sources, just combine
    agg_dir = tmp_path / "agg"
    agg_dir.mkdir()
    (agg_dir / "agg.vertex").write_text(
        'name "agg"\n\n'
        "combine {\n"
        '  vertex "child1"\n'
        '  vertex "child2"\n'
        "}\n\n"
        "loops {\n"
        "  child1 {\n"
        '    fold { count "inc" }\n'
        "  }\n"
        "  child2 {\n"
        '    fold { count "inc" }\n'
        "  }\n"
        "}\n"
    )

    return agg_dir / "agg.vertex"


def _make_aggregation_no_children(tmp_path: Path) -> Path:
    """Create an aggregation vertex with combine entries that don't resolve."""
    agg_dir = tmp_path / "agg-empty"
    agg_dir.mkdir()
    (agg_dir / "agg-empty.vertex").write_text(
        'name "agg-empty"\n\n'
        "combine {\n"
        '  vertex "nonexistent"\n'
        "}\n\n"
        "loops {\n"
        "  thing {\n"
        '    fold { count "inc" }\n'
        "  }\n"
        "}\n"
    )
    return agg_dir / "agg-empty.vertex"


class TestSyncAggregation:
    """Sync traverses combine children for aggregation vertices."""

    def test_sync_aggregation_syncs_children(self, monkeypatch, tmp_path, capsys):
        """Aggregation vertex with combine children syncs each child."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_aggregation_vertex(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["--force"], vertex_path=vertex_path)
        assert result == 0
        captured = capsys.readouterr()
        assert "children" in captured.err

    def test_sync_aggregation_no_children_errors(self, monkeypatch, tmp_path, capsys):
        """Aggregation vertex whose combine children don't exist errors."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_aggregation_no_children(tmp_path)

        from loops.main import _run_sync

        result = _run_sync([], vertex_path=vertex_path)
        assert result == 1
        captured = capsys.readouterr()
        assert "No sources" in captured.err

    def test_sync_instance_vertex_unchanged(self, monkeypatch, tmp_path, capsys):
        """Instance vertex with own sources still syncs directly."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["--force"], vertex_path=vertex_path)
        assert result == 0
        captured = capsys.readouterr()
        # Should show source count, not children count
        assert "sources" in captured.err
        assert "children" not in captured.err


class TestSyncFactCounts:
    """Sync output includes fact counts from source execution."""

    def test_sync_output_shows_fact_count(self, monkeypatch, tmp_path, capsys):
        """Sync output includes fact count per source."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["--force", "--plain"], vertex_path=vertex_path)
        assert result == 0
        captured = capsys.readouterr()
        # echo produces 1 fact; output should show source name with count
        assert "test" in captured.out  # source kind name
        assert "(1)" in captured.out  # fact count

    def test_sync_output_shows_source_name(self, monkeypatch, tmp_path, capsys):
        """Sync output includes the source kind name."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vertex_path = _make_vertex_with_source(tmp_path)

        from loops.main import _run_sync

        result = _run_sync(["--force", "--plain"], vertex_path=vertex_path)
        assert result == 0
        captured = capsys.readouterr()
        assert "Ran:" in captured.out

    def test_executor_populates_fact_counts(self, tmp_path):
        """Executor.sync() populates fact_counts in SyncResult."""
        from engine import load_vertex_program

        vertex_path = _make_vertex_with_source(tmp_path)
        program = load_vertex_program(vertex_path)
        result = program.sync(force=True)
        assert "test" in result.fact_counts
        assert result.fact_counts["test"] == 1  # echo produces 1 line = 1 fact
