"""End-to-end tests for cardinality auto-zoom on the read/fold view.

Exercises the cli/views/fold.py plumbing: argparse → Operation
(render_context["auto_zoom"]) → dispatch → fold_view. Asserts that
explicit -q / -v / -vv disable auto-zoom and that --plain / --json
do NOT disable it (visibility / format axes are orthogonal).
"""
from __future__ import annotations

import json

import pytest

from loops.cli.context import CliContext
from loops.cli.output import BufferReporter
from loops.cli.views import fold as fold_view_module

from .builders import StorePopulator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _render_text(reporter: BufferReporter) -> str:
    """Join all rendered Block rows into a single text string for assertion."""
    out: list[str] = []
    for block in reporter.blocks:
        for row in block._rows:
            out.append("".join(c.char for c in row).rstrip())
    return "\n".join(out)


def _run_read(argv, vertex_path, *, width=200):
    """Drive the fold view with a BufferReporter; return (rc, reporter)."""
    reporter = BufferReporter(width=width)
    ctx = CliContext(reporter=reporter, vertex_path=vertex_path)
    rc = fold_view_module.run(argv, ctx)
    return rc, reporter


@pytest.fixture
def flooded_vertex(loops_home):
    """A project vertex flooded with >AUTO_ZOOM_MAX_NAV decisions across
    TWO namespaces.

    The two-namespace split (design/ + arch/) is load-bearing: it ensures
    the MINIMAL renderer's namespace-breakdown branch fires (≥2 groups).
    A single-namespace flood would fall through to the key-list branch —
    that path is exercised in test_fold_utils.py's auto-zoom unit tests.

    Also seeds a 1-item ``thread`` and a small ``task`` section so
    multi-section adaptive rendering can be asserted in a single render.
    """
    from engine.builder import fold_by, vertex

    vdir = loops_home / "project"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "data").mkdir(parents=True, exist_ok=True)
    vpath = vdir / "project.vertex"
    (vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .loop("decision", fold_by("topic"))
        .loop("task", fold_by("name"))
        .write(vpath))

    db_path = vdir / "data" / "project.db"
    pop = StorePopulator(db_path)
    # 15 design/ + 10 arch/ = 25 total, multi-namespace breakdown path.
    for i in range(15):
        pop = pop.emit("decision", topic=f"design/d{i}", message=f"body-{i}")
    for i in range(10):
        pop = pop.emit("decision", topic=f"arch/a{i}", message=f"body-a{i}")
    # 5 tasks (in nav band)
    for i in range(5):
        pop = pop.emit("task", name=f"task-{i}", status="open")
    # 1 thread (answer mode)
    pop = pop.emit("thread", name="solo-thread", status="open")
    pop.done()
    return vpath


# ---------------------------------------------------------------------------
# Auto-zoom triggers on default (no loudness flag)
# ---------------------------------------------------------------------------


class TestAutoZoomDefaultPath:
    def test_high_n_section_renders_index_mode(self, flooded_vertex):
        rc, reporter = _run_read(["--kind", "decision"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # Section header present
        assert "Decision" in t
        # Multi-namespace breakdown line present (fixture spans design/ + arch/)
        assert "design/ (15)" in t
        assert "arch/ (10)" in t
        # No item bodies — bodies in flooded fixture are "body-N"
        assert "body-0" not in t
        assert "body-a0" not in t

    def test_single_item_section_bumps_to_detailed(self, flooded_vertex):
        # --kind thread narrows to one section with a single item.
        # Bump SUMMARY → DETAILED → preview renders + extras line surface.
        rc, reporter = _run_read(["--kind", "thread"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # The single thread key appears
        assert "solo-thread" in t

    def test_in_band_section_renders_normally(self, flooded_vertex):
        # task section: 5 items, in the navigation band.
        rc, reporter = _run_read(["--kind", "task"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # At SUMMARY each task key appears
        assert "task-0" in t
        assert "task-4" in t


# ---------------------------------------------------------------------------
# Explicit loudness flags disable auto-zoom (no-breaking-change anchor)
# ---------------------------------------------------------------------------


class TestExplicitFlagsOverride:
    def test_quiet_routes_to_vertex_level_oneliner(self, flooded_vertex):
        # -q is the user-explicit MINIMAL channel — vertex-level one-liner,
        # not per-section ns-count line.
        rc, reporter = _run_read(["--kind", "decision", "-q"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        assert "25 decisions" in t
        # Per-section MINIMAL breakdown does NOT appear under -q
        assert "design/ (15)" not in t
        assert "arch/ (10)" not in t

    def test_verbose_forces_detailed_even_at_high_n(self, flooded_vertex):
        # -v is the user-explicit DETAILED channel — auto-bump-down to
        # MINIMAL-per-section MUST NOT fire when count > threshold.
        rc, reporter = _run_read(["--kind", "decision", "-v"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # DETAILED renders item bodies — preview shows "body-N"
        assert "body-0" in t
        # The auto-zoom ns-count line shape would be "design/ (25)" with no
        # following item rows; DETAILED still shows the group header then
        # item rows. Verify the items rendered (bodies present is enough).

    def test_double_verbose_forces_full(self, flooded_vertex):
        rc, reporter = _run_read(["--kind", "thread", "-vv"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # FULL surfaces metadata lines
        assert "_ts:" in t or "_observer:" in t


# ---------------------------------------------------------------------------
# Orthogonal flags do NOT disable auto-zoom
# ---------------------------------------------------------------------------


class TestOrthogonalFlagsPreserveAutoZoom:
    def test_plain_still_auto_zooms(self, flooded_vertex):
        rc, reporter = _run_read(["--kind", "decision", "--plain"], flooded_vertex)
        assert rc == 0
        t = _render_text(reporter)
        # --plain is color-off, not loudness-off — auto-bump-down still fires
        assert "design/ (15)" in t
        assert "arch/ (10)" in t
        assert "body-0" not in t

    def test_json_short_circuits_before_auto_zoom(self, flooded_vertex):
        # --json bypasses the lens entirely; auto_zoom never runs.
        rc, reporter = _run_read(["--kind", "decision", "--json"], flooded_vertex)
        assert rc == 0
        # JSON output goes through reporter.msg, not print_block
        assert reporter.out_lines
        # Confirm it parses as JSON and contains decision data
        parsed = json.loads(reporter.out_lines[0])
        # Either the raw FoldState dict or its computed dict — both
        # contain section data. Just confirm something decision-shaped.
        text = json.dumps(parsed)
        assert "decision" in text or "design" in text

    def test_facts_disables_auto_zoom(self, flooded_vertex):
        """Anchored 2026-05-18: --facts is the user's explicit ask for more
        per item (compression history, fact lineage). Auto-zoom-DOWN to
        MINIMAL hides items entirely, neutralizing --facts. So --facts
        disables auto-zoom — items render at base SUMMARY. See friction:
        auto-zoom-neutralizes-facts-flag.
        """
        rc, reporter = _run_read(
            ["--kind", "decision", "--facts", "--plain"], flooded_vertex
        )
        assert rc == 0
        t = _render_text(reporter)
        # MINIMAL breakdown line MUST NOT appear — auto-zoom disabled.
        assert "design/ (15)" not in t
        assert "arch/ (10)" not in t
