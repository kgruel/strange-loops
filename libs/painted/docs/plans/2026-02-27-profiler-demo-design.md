# Profiler Demo + flame_lens Design

Date: 2026-02-27

## Summary

A patterns-level demo (`demos/patterns/profiler.py`) that profiles a painted
TUI app using `TestSurface` and renders the results through `run_cli` at four
zoom levels. Introduces `flame_lens` as a new library lens type for
proportional hierarchical visualization.

Two phases: Phase A (this design) builds the self-introspection demo and
`flame_lens`. Phase B (future) extends to external profiling data
(py-spy/cProfile).

## Motivation

Discord narrative debugging feedback: "build a profiler that uses painted's
own rendering to show the results." The profiler demonstrates three things:

1. **TestSurface as instrumentation** — not just for testing, but for
   measuring render cost (writes per frame, emission frequency).
2. **Lens composition** — chart_lens for frame cost bars, tree_lens for
   emission timeline, flame_lens for proportional breakdown. All in one view.
3. **Painted introspecting itself** — the library visualizes its own
   performance characteristics. Meta, but compelling.

## Data Model

```python
@dataclass(frozen=True)
class FrameProfile:
    index: int
    label: str           # "initial" | "after 'j'" | etc.
    write_count: int
    is_hot: bool          # > 2x average writes

@dataclass(frozen=True)
class EmissionSummary:
    kind: str
    count: int

@dataclass(frozen=True)
class ProfileData:
    scenario_name: str
    dimensions: str       # "80x24"
    input_count: int
    frame_count: int
    total_writes: int
    avg_writes: float
    max_writes: int
    hot_frame_count: int
    frames: tuple[FrameProfile, ...]
    emission_summary: tuple[EmissionSummary, ...]
    emissions_raw: tuple[tuple[str, dict], ...]
```

Frozen dataclasses, same pattern as `DiskData` in `fidelity.py`.

## Scenario

Self-contained mini list-navigation app profiled through `TestSurface`:

```python
_SCENARIO_INPUTS = ["j", "j", "j", "k", "k", "enter", "escape", "q"]

class _ListApp(Surface):
    # 10-item list, j/k nav, enter pushes confirm layer, escape pops
    # Emits: "list.select" on nav, "list.open"/"list.close" on enter/escape

def _fetch() -> ProfileData:
    app = _ListApp()
    ts = TestSurface(app, width=80, height=24, input_queue=_SCENARIO_INPUTS)
    frames = ts.run_to_completion()
    return _extract_profile("list_nav", ts, frames)
```

`_extract_profile` is a pure function: `(name, TestSurface, frames) -> ProfileData`.

## Zoom Levels

```
profiler -q       # zoom=0: MINIMAL
  "8 frames, 847 writes, avg 106/frame"

profiler          # zoom=1: SUMMARY
  Scenario: list_nav (8 inputs, 80x24)
  Frames:   8
  Writes:   847 total (avg 106, max 312)
  Emissions: 10 (5 list.select, 1 list.open, 1 list.close, 3 ui.key)

profiler -v       # zoom=2: DETAILED
  Per-frame write chart (chart_lens: {label: write_count})
  Emission flame graph (flame_lens: {kind: count})
  Hot frames flagged with Palette.warning

profiler -vv      # zoom=3: FULL
  Frame-by-frame breakdown (each frame as bordered section)
  Emission frequency chart (chart_lens: {kind: count})
  Full emission tree (tree_lens: all raw emissions)
```

## Rendering

Each zoom level is a separate named function for testability:

```python
def render_minimal(data: ProfileData) -> Block: ...
def render_summary(data: ProfileData) -> Block: ...
def render_detailed(data: ProfileData, width: int) -> Block: ...
def render_full(data: ProfileData, width: int) -> Block: ...

def _render(ctx: CliContext, data: ProfileData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:  return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:  return render_summary(data)
    if ctx.zoom == Zoom.FULL:     return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)
```

**Lens delegation at zoom 2+:**
- `chart_lens` for writes-per-frame bar chart
- `flame_lens` for emission proportional breakdown
- `tree_lens` for full emission timeline (zoom 3)
- `join_vertical` + `border` to compose sections

## flame_lens — New Library Lens

### Signature

```python
def flame_lens(data: Any, zoom: int = 1, width: int = 80) -> Block:
```

### Input Shape

Hierarchical dict where leaf values are numbers representing proportional
sizes. Same shape tree_lens accepts, different visual treatment.

```python
{"main": {"render": 45, "diff": 30, "flush": 25}}
```

### Zoom Behavior

- **zoom 0:** Total value as one-liner (`"main: 100"`)
- **zoom 1:** Top-level segments only (one row)
- **zoom 2+:** Expand child depth levels, one row per depth

### Rendering

Each depth level is a row. Each segment fills proportional width:

```
┃ main                                                      ┃
┃ render              ┃ diff           ┃ flush          ┃
```

- Segment: `Block.text(label, Style(reverse=True, fg=color))` padded to
  proportional width
- Rows: `join_horizontal(*segments)`, stack: `join_vertical(*rows)`
- Color: cycle through warm palette (accent + fixed warm colors)
- Rounding: last segment absorbs remainder to fill width exactly

### Location

`src/painted/_lens.py` alongside tree_lens and chart_lens.
Exported from `painted.views`.

### Auto-dispatch

No. Flame graphs are an explicit choice, not shape-based auto-dispatch.
Same hierarchical data could go to tree_lens (structure view) or flame_lens
(proportional view). The caller decides which representation suits their
use case.

## Integration

- **File:** `demos/patterns/profiler.py` (single file, PEP 723)
- **Dispatcher:** Added to `demos/painted-demo`
- **No interactive mode** for Phase A (static only)
- **Demo ladder update:** Entry in `demos/CLAUDE.md`

```python
def main() -> int:
    return run_cli(
        sys.argv[1:], render=_render, fetch=_fetch,
        description=__doc__, prog="profiler.py",
    )
```

## What This Teaches

- **Lens functions as composable building blocks** — chart_lens + tree_lens +
  flame_lens combined in one view, each handling a sub-section
- **TestSurface beyond testing** — instrumentation and profiling, not just
  replay verification
- **The zoom system** — progressively revealing detail about the same data
- **flame_lens** — new lens type for proportional hierarchical visualization

## Deferred: Future Lens Types

The following lens types were considered during design and deferred. They
don't dissolve into existing primitives but aren't needed for Phase A.

### timeline_lens

Horizontal bars on a time axis (Gantt-like). Data shape: events with
start time + duration. Profilers use this for thread activity timelines,
lock contention visualization, and GC pause mapping.

**Why deferred:** Phase A emissions don't have timing data. Phase B
(py-spy with timestamps) would be the natural trigger. chart_lens covers
magnitude comparisons for now.

### heatmap_lens

2D grid of values with color intensity mapping. Data shape: 2D array of
numbers or `{(row, col): value}` sparse matrix. Profilers use this for
emission frequency maps (kind x time bucket), memory access patterns,
and cache hit/miss grids.

**Why deferred:** Requires genuinely new rendering (color matrix). Phase A
emission frequency is 1D (chart_lens covers it). A real use case with 2D
data would justify the complexity.

### flame_lens Phase B Evolution

Phase B extends flame_lens to handle real call stack data:
- py-spy collapsed stack format → flame tree
- cProfile `pstats.Stats` → flame tree
- Interactive drill-down (click/enter to zoom into a stack frame)
- Color by module/package (not just cycling)

The render functions already accept `ProfileData`. Phase B adds a second
`_fetch` that loads external profiling output and converts to `ProfileData`.
The rendering pipeline doesn't change.

## Phase B Sketch (Not Designed Yet)

External profiling data rendered through the same pipeline:

```python
# Phase B: alternate fetch
def _fetch_pstats(path: str) -> ProfileData:
    stats = pstats.Stats(path)
    # Convert cumulative time → flame tree
    # Convert per-function stats → frame-like metrics
    return ProfileData(...)

# Phase B: flame_lens with real call stacks
flame_data = stats_to_flame_tree(stats)
flame_lens(flame_data, zoom=ctx.zoom, width=ctx.width)
```

The profiler demo becomes a general-purpose profiling visualization tool
that happens to use painted for rendering.
