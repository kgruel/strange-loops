# Profiler Demo + flame_lens Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `flame_lens` as a new library lens type, then a patterns-level profiler demo that uses TestSurface to profile a mini TUI app and renders the results through `run_cli` at four zoom levels — including flame_lens for proportional breakdown.

**Architecture:** Two deliverables: (1) `flame_lens` added to `_lens.py` with the same `(data, zoom, width) -> Block` contract as tree_lens/chart_lens. (2) `demos/patterns/profiler.py` following the same shape as `fidelity.py` — frozen data model, separate render functions per zoom, `run_cli` integration. The profiler runs a self-contained mini list-navigation app through TestSurface, extracts frame/emission metrics, and renders them using chart_lens + tree_lens + flame_lens.

**Tech Stack:** Python 3.11+, painted primitives (Block, Style, join_horizontal, join_vertical, border, pad), painted views (chart_lens, tree_lens), TestSurface, run_cli.

---

### Task 1: flame_lens — Failing Tests

**Files:**
- Create: `tests/test_flame_lens.py`

**Step 1: Write the failing tests**

```python
"""Tests for flame_lens — proportional hierarchical visualization."""

import pytest

from painted.views import flame_lens


def _block_to_text(block) -> str:
    """Extract text content from a block for testing."""
    result = []
    for y in range(block.height):
        row = block.row(y)
        line = "".join(cell.char for cell in row)
        result.append(line)
    return "\n".join(result)


class TestFlameLensZoom:
    """Tests for flame_lens at each zoom level."""

    def test_zoom_0_shows_total(self):
        """At zoom 0, flame shows root label + total value."""
        data = {"render": 45, "diff": 30, "flush": 25}
        block = flame_lens(data, 0, 40)
        text = _block_to_text(block)
        assert "100" in text  # total of 45+30+25

    def test_zoom_1_shows_single_row(self):
        """At zoom 1, flame shows top-level segments in one row."""
        data = {"render": 45, "diff": 30, "flush": 25}
        block = flame_lens(data, 1, 60)
        text = _block_to_text(block)
        assert "render" in text
        assert "diff" in text
        assert "flush" in text
        assert block.height == 1

    def test_zoom_2_expands_children(self):
        """At zoom 2+, flame expands child segments into additional rows."""
        data = {"main": {"render": 45, "diff": 30, "flush": 25}}
        block = flame_lens(data, 2, 60)
        text = _block_to_text(block)
        assert "main" in text
        assert "render" in text
        assert block.height >= 2


class TestFlameLensProportions:
    """Tests for proportional width allocation."""

    def test_segments_fill_width(self):
        """All segments together fill the available width."""
        data = {"a": 50, "b": 50}
        block = flame_lens(data, 1, 40)
        # Row should be exactly the requested width
        assert block.width == 40

    def test_larger_segment_gets_more_width(self):
        """Segment with larger value gets proportionally more characters."""
        data = {"big": 90, "small": 10}
        block = flame_lens(data, 1, 40)
        text = _block_to_text(block)
        # "big" segment should have more characters than "small"
        row = block.row(0)
        row_text = "".join(c.char for c in row)
        # Find where labels appear to verify proportionality
        assert row_text.index("big") < row_text.index("small")

    def test_single_segment_fills_width(self):
        """A single segment fills the entire width."""
        data = {"only": 100}
        block = flame_lens(data, 1, 30)
        assert block.width == 30


class TestFlameLensEdgeCases:
    """Tests for edge cases."""

    def test_empty_data(self):
        """Empty dict produces valid output."""
        block = flame_lens({}, 1, 40)
        text = _block_to_text(block)
        assert "no data" in text.lower() or block.height >= 1

    def test_zero_width_returns_empty(self):
        """Zero width returns empty block."""
        block = flame_lens({"a": 1}, 1, 0)
        assert block.width == 0

    def test_nested_three_levels(self):
        """Three-level nesting at high zoom."""
        data = {"top": {"mid": {"leaf": 100}}}
        block = flame_lens(data, 3, 60)
        text = _block_to_text(block)
        assert "top" in text
        assert "mid" in text
        assert "leaf" in text

    def test_zero_values_handled(self):
        """Zero-valued segments don't cause division errors."""
        data = {"active": 100, "idle": 0}
        block = flame_lens(data, 1, 40)
        text = _block_to_text(block)
        assert "active" in text

    def test_width_respected(self):
        """Output block respects width constraint."""
        data = {"a": 30, "b": 70}
        block = flame_lens(data, 1, 50)
        assert block.width == 50
```

**Step 2: Run tests to verify they fail**

Run: `uv run --package painted pytest tests/test_flame_lens.py -v`
Expected: ImportError — `flame_lens` doesn't exist yet.

**Step 3: Commit**

```bash
git add tests/test_flame_lens.py
git commit -m "test: add failing tests for flame_lens"
```

---

### Task 2: flame_lens — Implementation

**Files:**
- Modify: `src/painted/_lens.py` (add after chart_lens section, ~line 730)
- Modify: `src/painted/views/__init__.py` (add flame_lens export)

**Step 1: Implement flame_lens in `_lens.py`**

Add after the chart_lens section (after line 729):

```python
# ---------------------------------------------------------------------------
# Flame Lens — proportional hierarchical visualization
# ---------------------------------------------------------------------------


def flame_lens(data: Any, zoom: int, width: int) -> Block:
    """Render hierarchical data as proportional horizontal segments (flame graph).

    Each depth level is a row where segments fill proportional width based on
    their numeric values. Unlike tree_lens (which shows structure with
    indentation), flame_lens shows proportional size relationships.

    Supports:
    - Dict {label: number}: flat segments (one row)
    - Dict {label: {sublabel: number}}: nested segments (multiple rows)
    - Nested dicts to arbitrary depth

    Zoom levels:
    - 0: Root label + total value
    - 1: Top-level segments only (one row)
    - 2+: Expand child segments, one row per depth level

    Args:
        data: Hierarchical data with numeric leaves.
        zoom: Zoom level (0+).
        width: Available width in characters.

    Returns:
        Block with rendered flame graph.
    """
    if width <= 0:
        return Block.empty(0, 1)

    segments = _flame_extract(data)
    if not segments:
        return Block.text("(no data)", Style(dim=True), width=width)

    total = _flame_total(segments)

    if zoom <= 0:
        label = _flame_root_label(data)
        text = f"{label}: {total:.4g}" if total != int(total) else f"{label}: {int(total)}"
        if display_width(text) > width:
            text = truncate_ellipsis(text, width)
        return Block.text(text, Style(), width=width)

    # Build rows: one row per depth level
    rows: list[Block] = []
    _flame_render_row(segments, total, width, zoom, rows, 0)

    if not rows:
        return Block.empty(width, 1)

    return join_vertical(*rows)


# Warm color cycle for flame segments
_FLAME_COLORS = ("red", "yellow", "208", "202", "166", "214")


def _flame_extract(data: Any) -> list[tuple[str, Any]]:
    """Extract [(label, value_or_children)] from data."""
    if isinstance(data, dict):
        return [(str(k), v) for k, v in data.items()]
    return []


def _flame_total(segments: list[tuple[str, Any]]) -> float:
    """Sum numeric values, recursing into dicts."""
    total = 0.0
    for _, value in segments:
        if isinstance(value, (int, float)):
            total += float(value)
        elif isinstance(value, dict):
            children = [(str(k), v) for k, v in value.items()]
            total += _flame_total(children)
    return total


def _flame_root_label(data: Any) -> str:
    """Get a label for the root."""
    if isinstance(data, dict) and len(data) == 1:
        return str(next(iter(data.keys())))
    return "total"


def _flame_render_row(
    segments: list[tuple[str, Any]],
    row_total: float,
    width: int,
    remaining_zoom: int,
    rows: list[Block],
    depth: int,
) -> None:
    """Render one row of proportional segments, then recurse into children."""
    if not segments or width <= 0 or remaining_zoom <= 0:
        return

    # Build this row's blocks
    row_blocks: list[Block] = []
    child_groups: list[tuple[list[tuple[str, Any]], float, int]] = []
    remaining_width = width

    for i, (label, value) in enumerate(segments):
        # Calculate this segment's value
        if isinstance(value, (int, float)):
            seg_value = float(value)
        elif isinstance(value, dict):
            children = [(str(k), v) for k, v in value.items()]
            seg_value = _flame_total(children)
        else:
            seg_value = 0.0

        # Calculate proportional width
        is_last = i == len(segments) - 1
        if is_last:
            seg_width = remaining_width  # absorb rounding remainder
        elif row_total > 0:
            seg_width = max(1, int(seg_value / row_total * width))
            seg_width = min(seg_width, remaining_width)
        else:
            seg_width = max(1, remaining_width // (len(segments) - i))

        if seg_width <= 0:
            continue

        # Render segment block
        color = _FLAME_COLORS[depth % len(_FLAME_COLORS)]
        seg_text = truncate(label, seg_width) if display_width(label) > seg_width else label
        seg_text = seg_text.ljust(seg_width)[:seg_width]
        seg_block = Block.text(seg_text, Style(fg=color, reverse=True), width=seg_width)
        row_blocks.append(seg_block)

        # Track children for next row
        if isinstance(value, dict) and remaining_zoom > 1:
            children = [(str(k), v) for k, v in value.items()]
            if children:
                child_groups.append((children, seg_value, seg_width))

        remaining_width -= seg_width

    if row_blocks:
        row = join_horizontal(*row_blocks)
        # Ensure exact width
        if row.width < width:
            from .compose import pad as pad_fn
            row = pad_fn(row, right=width - row.width)
        rows.append(row)

    # Recurse into children (expand to fill parent width)
    if child_groups:
        all_children: list[tuple[str, Any]] = []
        child_total = 0.0
        for children, seg_val, seg_w in child_groups:
            all_children.extend(children)
            child_total += seg_val
        _flame_render_row(all_children, child_total, width, remaining_zoom - 1, rows, depth + 1)
```

**Step 2: Add export to `views/__init__.py`**

In `src/painted/views/__init__.py`, add `flame_lens` to the import from `painted._lens`:

```python
from painted._lens import (  # noqa: F401
    NodeRenderer,
    shape_lens,
    tree_lens,
    chart_lens,
    flame_lens,
)
```

And add `"flame_lens"` to `__all__` after `"chart_lens"`.

**Step 3: Run tests to verify they pass**

Run: `uv run --package painted pytest tests/test_flame_lens.py -v`
Expected: All tests PASS.

**Step 4: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All existing tests still pass, plus new flame_lens tests.

**Step 5: Commit**

```bash
git add src/painted/_lens.py src/painted/views/__init__.py
git commit -m "feat: add flame_lens for proportional hierarchical visualization"
```

---

### Task 3: Profiler Demo — Data Model + Fetch

**Files:**
- Create: `demos/patterns/profiler.py`

**Step 1: Write the data model and fetch function**

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Self-profiling — painted introspects its own rendering performance.

TestSurface profiles a mini TUI app, then renders the results at every
zoom level through run_cli. Demonstrates lens composition: chart_lens
for frame cost bars, tree_lens for emission timeline, flame_lens for
proportional breakdown.

    uv run demos/patterns/profiler.py -q        # summary stats
    uv run demos/patterns/profiler.py           # emission traces
    uv run demos/patterns/profiler.py -v        # frame chart + flame graph
    uv run demos/patterns/profiler.py -vv       # frame-by-frame detail
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from painted import (
    Block,
    CliContext,
    Style,
    Zoom,
    border,
    join_horizontal,
    join_vertical,
    pad,
    run_cli,
    ROUNDED,
)
from painted.views import chart_lens, flame_lens, tree_lens
from painted.palette import current_palette
from painted.tui import Layer, Pop, Push, Quit, Stay, Surface, TestSurface, render_layers


# --- Data model ---


@dataclass(frozen=True)
class FrameProfile:
    """Performance metrics for a single rendered frame."""
    index: int
    label: str
    write_count: int
    is_hot: bool


@dataclass(frozen=True)
class EmissionSummary:
    """Aggregate count for one emission kind."""
    kind: str
    count: int


@dataclass(frozen=True)
class ProfileData:
    """Complete profiling results from a TestSurface run."""
    scenario_name: str
    dimensions: str
    input_count: int
    frame_count: int
    total_writes: int
    avg_writes: float
    max_writes: int
    hot_frame_count: int
    frames: tuple[FrameProfile, ...]
    emission_summary: tuple[EmissionSummary, ...]
    emissions_raw: tuple[tuple[str, dict], ...]


# --- Mini app under test ---


_ITEMS = (
    "api-gateway", "auth-service", "worker", "scheduler",
    "metrics", "logger", "cache", "queue", "storage", "monitor",
)

_SCENARIO_INPUTS = ["j", "j", "j", "k", "k", "enter", "escape", "q"]


def _get_layers(state: dict) -> tuple[Layer, ...]:
    return state["layers"]


def _set_layers(state: dict, layers: tuple[Layer, ...]) -> dict:
    return {**state, "layers": layers}


def _base_layer() -> Layer:
    def handle(key: str, ls: int, app_state: dict):
        if key == "j":
            return min(ls + 1, len(_ITEMS) - 1), app_state, Stay()
        if key == "k":
            return max(ls - 1, 0), app_state, Stay()
        if key == "enter":
            return ls, app_state, Push(layer=_detail_layer(_ITEMS[ls]))
        if key == "q":
            return ls, app_state, Quit()
        return ls, app_state, Stay()

    def render(ls: int, app_state: dict, view):
        for i, item in enumerate(_ITEMS):
            marker = ">" if i == ls else " "
            view.put_text(0, i, f"{marker} {item}", Style(bold=(i == ls)))

    return Layer(name="list", state=0, handle=handle, render=render)


def _detail_layer(name: str) -> Layer:
    def handle(key: str, ls: str, app_state: dict):
        if key in ("escape", "q"):
            return ls, app_state, Pop(result=None)
        return ls, app_state, Stay()

    def render(ls: str, app_state: dict, view):
        view.put_text(0, 0, f"Detail: {ls}", Style(bold=True))
        view.put_text(0, 1, "Press escape to go back", Style(dim=True))

    return Layer(name="detail", state=name, handle=handle, render=render)


class _ProfileApp(Surface):
    def __init__(self):
        super().__init__()
        self.state: dict = {"layers": (_base_layer(),)}

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        render_layers(self.state, self._buf, _get_layers)

    def on_key(self, key: str) -> None:
        new_state, should_quit, pop_result = self.handle_key(
            key, self.state, _get_layers, _set_layers,
        )
        self.state = new_state
        layers = _get_layers(new_state)
        base = layers[0]
        selected = base.state

        if key in ("j", "k") and len(layers) == 1:
            self.emit("list.select", service=_ITEMS[selected], index=selected)
        if key == "enter" and len(layers) > 1:
            self.emit("list.open", service=_ITEMS[selected])
        if pop_result is None and key == "escape":
            self.emit("list.close", service=_ITEMS[selected])
        if should_quit:
            self.quit()


# --- Profile extraction ---


def _extract_profile(name: str, harness: TestSurface, frames: list) -> ProfileData:
    """Pure function: extract ProfileData from a completed TestSurface run."""
    write_counts = [len(f.writes) for f in frames]
    avg = sum(write_counts) / len(write_counts) if write_counts else 0.0
    threshold = avg * 2

    frame_profiles = tuple(
        FrameProfile(
            index=i,
            label="initial" if i == 0 else f"after '{_SCENARIO_INPUTS[i - 1]}'",
            write_count=wc,
            is_hot=wc > threshold,
        )
        for i, wc in enumerate(write_counts)
    )

    # Aggregate emissions by kind
    kind_counts: dict[str, int] = {}
    for kind, _ in harness.emissions:
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    emission_summary = tuple(
        EmissionSummary(kind=k, count=c)
        for k, c in sorted(kind_counts.items(), key=lambda x: -x[1])
    )

    return ProfileData(
        scenario_name=name,
        dimensions=f"{harness.width}x{harness.height}",
        input_count=len(_SCENARIO_INPUTS),
        frame_count=len(frames),
        total_writes=sum(write_counts),
        avg_writes=round(avg, 1),
        max_writes=max(write_counts) if write_counts else 0,
        hot_frame_count=sum(1 for f in frame_profiles if f.is_hot),
        frames=frame_profiles,
        emission_summary=emission_summary,
        emissions_raw=tuple((k, d) for k, d in harness.emissions),
    )


def _fetch() -> ProfileData:
    """Run the scenario and extract profiling data."""
    app = _ProfileApp()
    harness = TestSurface(app, width=80, height=24, input_queue=_SCENARIO_INPUTS)
    frames = harness.run_to_completion()
    return _extract_profile("list_nav", harness, frames)
```

This is just the data model, mini app, extraction, and fetch. Render functions come next.

**Step 2: Verify the file is syntactically valid**

Run: `uv run --package painted python -c "import ast; ast.parse(open('demos/patterns/profiler.py').read()); print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add demos/patterns/profiler.py
git commit -m "feat(demo): add profiler data model, mini app, and fetch"
```

---

### Task 4: Profiler Demo — Render Functions

**Files:**
- Modify: `demos/patterns/profiler.py` (append render functions + main)

**Step 1: Add render functions and main**

Append after `_fetch()`:

```python
# --- Zoom 0: one-line summary ---


def render_minimal(data: ProfileData) -> Block:
    """Single-line profiling summary."""
    return Block.text(
        f"{data.frame_count} frames, {data.total_writes} writes, "
        f"avg {data.avg_writes:.0f}/frame",
        Style(),
    )


# --- Zoom 1: emission traces ---


def render_summary(data: ProfileData) -> Block:
    """Scenario overview with emission counts."""
    p = current_palette()
    rows: list[Block] = [
        Block.text(f"Scenario: {data.scenario_name}", Style(bold=True)),
        Block.text(f"  {data.input_count} inputs, {data.dimensions}", Style(dim=True)),
        Block.text("", Style()),
        Block.text(f"Frames:    {data.frame_count}", Style()),
        Block.text(
            f"Writes:    {data.total_writes} total "
            f"(avg {data.avg_writes:.0f}, max {data.max_writes})",
            Style(),
        ),
    ]

    if data.hot_frame_count:
        rows.append(Block.text(
            f"Hot frames: {data.hot_frame_count} (>2x avg)", p.warning,
        ))

    rows.append(Block.text("", Style()))
    rows.append(Block.text("Emissions:", Style(dim=True)))
    for es in data.emission_summary:
        style = p.accent if not es.kind.startswith("ui.") else Style(dim=True)
        rows.append(Block.text(f"  {es.count:>3}x  {es.kind}", style))

    return join_vertical(*rows)


# --- Zoom 2: frame chart + flame graph ---


def render_detailed(data: ProfileData, width: int) -> Block:
    """Per-frame write chart and emission flame graph."""
    p = current_palette()
    sections: list[Block] = []

    # Frame write counts as bar chart
    frame_data = {f.label: f.write_count for f in data.frames}
    chart_block = chart_lens(frame_data, 3, min(width - 4, 70))
    sections.append(border(chart_block, title="Writes per Frame", chars=ROUNDED))
    sections.append(Block.text("", Style()))

    # Hot frame callouts
    hot_frames = [f for f in data.frames if f.is_hot]
    if hot_frames:
        hot_rows = [Block.text("Hot frames (>2x average):", p.warning)]
        for f in hot_frames:
            hot_rows.append(Block.text(
                f"  Frame {f.index} ({f.label}): {f.write_count} writes", p.warning,
            ))
        sections.append(join_vertical(*hot_rows))
        sections.append(Block.text("", Style()))

    # Emission proportions as flame graph
    emission_data = {es.kind: es.count for es in data.emission_summary}
    if emission_data:
        flame_block = flame_lens(emission_data, 1, min(width - 4, 70))
        sections.append(border(flame_block, title="Emission Proportions", chars=ROUNDED))

    return join_vertical(*sections)


# --- Zoom 3: frame-by-frame breakdown ---


def render_full(data: ProfileData, width: int) -> Block:
    """Frame-by-frame detail with full emission tree."""
    p = current_palette()
    sections: list[Block] = []

    # Per-frame detail
    for frame in data.frames:
        style = p.warning if frame.is_hot else Style()
        hot_marker = " HOT" if frame.is_hot else ""
        header = Block.text(
            f"Frame {frame.index}: {frame.write_count} writes{hot_marker}",
            style,
        )
        label_line = Block.text(f"  {frame.label}", Style(dim=True))
        inner = join_vertical(header, label_line)
        sections.append(border(
            pad(inner, right=max(0, min(50, width - 4) - inner.width)),
            title=f"Frame {frame.index}",
            chars=ROUNDED,
        ))

    sections.append(Block.text("", Style()))

    # Emission frequency chart
    emission_data = {es.kind: es.count for es in data.emission_summary}
    if emission_data:
        chart_block = chart_lens(emission_data, 3, min(width - 4, 70))
        sections.append(border(chart_block, title="Emission Frequency", chars=ROUNDED))
        sections.append(Block.text("", Style()))

    # Full emission tree
    emission_tree = {}
    for kind, data_dict in data.emissions_raw:
        category = kind.split(".")[0] if "." in kind else kind
        if category not in emission_tree:
            emission_tree[category] = {}
        detail = " ".join(f"{k}={v}" for k, v in data_dict.items())
        entry = f"{kind}: {detail}" if detail else kind
        count = emission_tree[category].get(entry, 0)
        emission_tree[category][entry] = count + 1

    if emission_tree:
        tree_block = tree_lens(emission_tree, 2, min(width - 4, 70))
        sections.append(border(tree_block, title="Emission Timeline", chars=ROUNDED))

    return join_vertical(*sections)


# --- run_cli integration ---


def _render(ctx: CliContext, data: ProfileData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:
        return render_summary(data)
    if ctx.zoom == Zoom.FULL:
        return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)


def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=_fetch,
        description=__doc__,
        prog="profiler.py",
    )


if __name__ == "__main__":
    sys.exit(main())
```

**Step 2: Run the demo at all zoom levels to verify**

Run each:
```bash
uv run --package painted python demos/patterns/profiler.py -q
uv run --package painted python demos/patterns/profiler.py
uv run --package painted python demos/patterns/profiler.py -v
uv run --package painted python demos/patterns/profiler.py -vv
```

Expected: Each produces styled output at its zoom level. No crashes.

**Step 3: Commit**

```bash
git add demos/patterns/profiler.py
git commit -m "feat(demo): add profiler render functions and run_cli integration"
```

---

### Task 5: Profiler Demo — Integration + Docs

**Files:**
- Modify: `demos/painted-demo` (add `profiler` entry)
- Modify: `demos/CLAUDE.md` (add profiler to ladder)

**Step 1: Add dispatcher entry**

In `demos/painted-demo`, add inside the `case` block after `live)`:

```bash
  profiler)    exec uv run python demos/patterns/profiler.py "$@" ;;
```

Update the `*)` fallback Available list to include `profiler`.

**Step 2: Update demo ladder in CLAUDE.md**

In `demos/CLAUDE.md`, add after the `testing.py` entry:

```
  profiler.py     Self-profiling: frame cost, emission timeline, flame graph
```

**Step 3: Verify dispatcher works**

Run: `demos/painted-demo profiler -q`
Expected: One-line profiling summary.

**Step 4: Commit**

```bash
git add demos/painted-demo demos/CLAUDE.md
git commit -m "docs: add profiler to demo dispatcher and demo ladder"
```

---

### Task 6: Update CLAUDE.md and HANDOFF.md

**Files:**
- Modify: `CLAUDE.md` (add flame_lens to views table)
- Modify: `HANDOFF.md` (add session entry)

**Step 1: Update CLAUDE.md**

In the Stateless views section under `shape_lens`, add:

```
from painted.views import flame_lens                               # Proportional viz
```

In the Key Types > Composition table or a similar section, add `flame_lens` description.

**Step 2: Update HANDOFF.md**

Add to Completed section:
```
- **flame_lens** — New lens type for proportional hierarchical visualization
  (flame graph style). Horizontal segments proportional to numeric values,
  warm color cycling, multi-depth rows. Not auto-dispatched — explicit
  choice alongside tree_lens.
- **Profiler demo** — `demos/patterns/profiler.py`: TestSurface profiles
  a mini list-navigation app, renders results at 4 zoom levels using
  chart_lens + tree_lens + flame_lens composition. Same run_cli pattern
  as fidelity.py.
```

Add to Open Threads:
```
- **Deferred lens types** — timeline_lens (events on time axis),
  heatmap_lens (2D frequency grid), flame_lens Phase B (py-spy/cProfile
  integration). Design doc: `docs/plans/2026-02-27-profiler-demo-design.md`.
```

**Step 3: Commit**

```bash
git add CLAUDE.md HANDOFF.md
git commit -m "docs: update CLAUDE.md and HANDOFF.md for flame_lens + profiler"
```

---

### Task 7: Final Verification

**Step 1: Run full test suite**

Run: `uv run --package painted pytest tests/ -q`
Expected: All tests pass (624 existing + new flame_lens tests).

**Step 2: Run all demo zoom levels**

```bash
uv run --package painted python demos/patterns/profiler.py -q
uv run --package painted python demos/patterns/profiler.py
uv run --package painted python demos/patterns/profiler.py -v
uv run --package painted python demos/patterns/profiler.py -vv
uv run --package painted python demos/patterns/profiler.py --json
uv run --package painted python demos/patterns/profiler.py --plain
```

Expected: Each mode produces appropriate output. `--json` produces valid JSON. `--plain` has no ANSI escapes.

**Step 3: Verify no lint/import issues**

Run: `uv run --package painted python -c "from painted.views import flame_lens; print('OK')"`
Expected: `OK`
