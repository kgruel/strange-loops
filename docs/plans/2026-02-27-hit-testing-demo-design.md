# Hit Testing Demo Design

Date: 2026-02-27

## What the Demo Teaches

The full round-trip of mouse picking in painted:

```
assign id -> compose -> paint -> hit(x, y) -> get id back
```

Specifically:

1. **Block.id** -- the semantic identifier attached at creation time
2. **Composition propagation** -- how ids flow through `join_horizontal`,
   `join_vertical`, `pad`, `border`, `truncate`, `vslice`
3. **Buffer._ids lazy allocation** -- the provenance grid only exists when
   `put_id` is first called (zero cost when unused)
4. **Buffer.hit(x, y)** / **Surface.hit(x, y)** -- resolving a screen
   coordinate back to its semantic origin
5. **MouseEvent + hit = mouse picking** -- the connection between click
   coordinates and application-level meaning

## Demo Scenario: Service Dashboard with Clickable Panels

A deployment dashboard with four service panels arranged in a 2x2 grid.
Each panel has an `id` matching its service name. The demo constructs the
dashboard, paints it into a Buffer, then probes specific coordinates to
show which panel owns which pixel.

This is a CLI demo (not interactive TUI), because the teaching point is
the data flow, not the interaction loop. TestSurface is used to exercise
the full paint cycle and prove hit results against a real Buffer.

### Why this scenario

- Multiple named regions in a single composed layout -- realistic
- 2x2 grid exercises both `join_horizontal` and `join_vertical`
- Borders with `id` overrides show the two-layer id system (border cell
  vs inner content)
- Padding adds dead zones (None ids) between regions
- The probe results tell the full composition story visually

### Sample data

```python
SERVICES = {
    "api-gateway":  {"status": "healthy",  "replicas": "3/3", "latency_ms": 12},
    "auth-service": {"status": "degraded", "replicas": "2/3", "latency_ms": 2100},
    "worker":       {"status": "healthy",  "replicas": "5/5", "latency_ms": 8},
    "scheduler":    {"status": "failing",  "replicas": "0/1", "latency_ms": 0},
}
```

## The Composition Story

### Step 1: Assign ids at creation

Each service panel is a bordered Block with `id` set:

```python
def _service_panel(name: str, info: dict, width: int) -> Block:
    status_style = ...  # green/yellow/red based on status
    content = join_vertical(
        Block.text(f" {name}", Style(bold=True)),
        Block.text(f"   {info['replicas']} replicas", Style()),
        Block.text(f"   {info['latency_ms']}ms", Style(dim=True)),
    )
    return border(pad(content, left=1, right=max(0, width - content.width - 2)),
                  chars=ROUNDED, style=status_style, id=name)
```

The `border(... id=name)` assigns the border cells to `name`. Inner
content inherits `name` because each inner Block has no id of its own.
This means: every pixel in the bordered panel resolves to `name`.

### Step 2: Compose into a grid

```python
top_row = join_horizontal(panels[0], panels[1], gap=1)
bot_row = join_horizontal(panels[2], panels[3], gap=1)
grid = join_vertical(top_row, bot_row, gap=1)
```

What happens to ids at each join:

- **join_horizontal**: Each block's id fills its width. Gap cells get `None`.
  The result Block has `_ids` (per-cell matrix), not a single `.id`.
- **join_vertical**: Same. Width-padding cells on narrower rows get `None`.
  Gap rows get `None`.

Result: a single composed Block where `cell_id(x, y)` returns the service
name or `None` (for gaps/padding).

### Step 3: Paint into Buffer

```python
buf = Buffer(grid.width, grid.height)
grid.paint(buf, 0, 0)
```

`Block.paint` detects the `_ids` matrix and calls `buf.put_id()` for each
cell that has an id. The Buffer lazily allocates `_ids` on the first
`put_id` call (`_ensure_ids`).

### Step 4: Hit test

```python
buf.hit(0, 0)   # -> "api-gateway" (top-left border corner)
buf.hit(5, 2)   # -> "api-gateway" (inside content)
buf.hit(panel_width, 0)  # -> None (gap) or "auth-service"
```

The demo probes a set of coordinates and renders the results as a visual
map showing which id owns each cell.

## Zoom Level Rendering

```
hit_testing -q       # zoom=0: MINIMAL
  "4 panels, 3 with ids, grid 62x15, 930 cells total, 868 with ids"

hit_testing          # zoom=1: SUMMARY
  Dashboard grid rendered as Block output.
  Below it: a probe table showing (x, y) -> id for key coordinates:
    corners of each panel, gap cells, border cells, inner content.

hit_testing -v       # zoom=2: DETAILED
  Dashboard grid + probe table (as above).
  Plus: id provenance map -- a character grid where each cell is replaced
  by a colored marker showing its id. Same grid dimensions as the
  dashboard, but the content shows the id layer, not the visual layer.
  Think: the dashboard is the "what you see", the provenance map is
  "what hit() sees".

hit_testing -vv      # zoom=3: FULL
  All of the above, bordered.
  Plus: composition trace -- shows the id state at each composition step:
    1. Individual panels (each with uniform id)
    2. After join_horizontal (per-cell ids with None gaps)
    3. After join_vertical (full grid with None gaps)
  Each step rendered as a small provenance map.
  Plus: lazy allocation note -- Buffer._ids is None until first put_id.
```

## Data Model

```python
@dataclass(frozen=True)
class ProbeResult:
    """A single hit test probe."""
    x: int
    y: int
    id: str | None
    label: str  # "top-left corner", "gap", "inner content", etc.

@dataclass(frozen=True)
class HitTestData:
    """Complete hit testing results."""
    grid: Block           # the composed dashboard
    grid_width: int
    grid_height: int
    total_cells: int
    cells_with_id: int
    unique_ids: tuple[str, ...]
    probes: tuple[ProbeResult, ...]
    # For zoom 3: intermediate composition steps
    panels: tuple[tuple[str, Block], ...]  # (name, panel_block)
    row_blocks: tuple[Block, ...]          # after join_horizontal
```

## Code Sketch

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Hit testing -- Block.id propagation through composition to Buffer.hit().

Builds a service dashboard with named panels, composes them into a grid,
paints into a Buffer, and probes coordinates to show how ids survive
composition and enable mouse picking.

    uv run demos/patterns/hit_testing.py -q        # cell/id counts
    uv run demos/patterns/hit_testing.py           # dashboard + probe table
    uv run demos/patterns/hit_testing.py -v        # + id provenance map
    uv run demos/patterns/hit_testing.py -vv       # + composition trace
"""

import sys
from dataclasses import dataclass

from painted import (
    Block, CliContext, Style, Zoom,
    border, join_horizontal, join_vertical, pad,
    run_cli, ROUNDED,
)
from painted.palette import current_palette
from painted.tui import Buffer


# --- Sample data ---

SERVICES = { ... }


# --- Panel construction (Step 1: assign ids) ---

def _service_panel(name: str, info: dict, width: int) -> Block:
    ...
    return border(pad(content, ...), chars=ROUNDED, id=name)


# --- Grid composition (Step 2: compose) ---

def _build_grid(panel_width: int) -> tuple[Block, list[tuple[str, Block]], list[Block]]:
    panels = [(name, _service_panel(name, info, panel_width)) for name, info in SERVICES.items()]
    names = [n for n, _ in panels]
    blocks = [b for _, b in panels]
    top_row = join_horizontal(blocks[0], blocks[1], gap=1)
    bot_row = join_horizontal(blocks[2], blocks[3], gap=1)
    grid = join_vertical(top_row, bot_row, gap=1)
    return grid, panels, [top_row, bot_row]


# --- Hit probing (Steps 3-4: paint + hit) ---

def _probe_grid(grid: Block) -> HitTestData:
    buf = Buffer(grid.width, grid.height)
    grid.paint(buf, 0, 0)

    # Probe key coordinates
    probes = []
    probes.append(ProbeResult(0, 0, buf.hit(0, 0), "top-left border"))
    probes.append(ProbeResult(2, 1, buf.hit(2, 1), "api-gateway content"))
    # ... gap probes, each panel corner, center of each panel ...

    # Count ids
    total = grid.width * grid.height
    with_id = sum(1 for y in range(grid.height) for x in range(grid.width) if buf.hit(x, y) is not None)
    unique = tuple(sorted(set(buf.hit(x, y) for y in range(grid.height) for x in range(grid.width) if buf.hit(x, y) is not None)))

    return HitTestData(grid=grid, ..., probes=tuple(probes), ...)


# --- Provenance map (zoom 2+) ---

def _provenance_map(grid: Block, width: int) -> Block:
    """Render the id layer: each cell colored by its owner id."""
    buf = Buffer(grid.width, grid.height)
    grid.paint(buf, 0, 0)
    colors = {"api-gateway": "green", "auth-service": "yellow", "worker": "cyan", "scheduler": "red"}
    rows = []
    for y in range(grid.height):
        row_cells = []
        for x in range(grid.width):
            cell_id = buf.hit(x, y)
            if cell_id and cell_id in colors:
                row_cells.append(Block.text("█", Style(fg=colors[cell_id])))
            else:
                row_cells.append(Block.text("·", Style(dim=True)))
        rows.append(join_horizontal(*row_cells))
    return join_vertical(*rows)


# --- Zoom renderers ---

def render_minimal(data: HitTestData) -> Block: ...
def render_summary(data: HitTestData) -> Block: ...
def render_detailed(data: HitTestData, width: int) -> Block: ...
def render_full(data: HitTestData, width: int) -> Block: ...

def _render(ctx: CliContext, data: HitTestData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:   return render_minimal(data)
    if ctx.zoom == Zoom.SUMMARY:   return render_summary(data)
    if ctx.zoom == Zoom.FULL:      return render_full(data, ctx.width)
    return render_detailed(data, ctx.width)

def _fetch() -> HitTestData:
    return _probe_grid(_build_grid(panel_width=28)[0])

def main() -> int:
    return run_cli(sys.argv[1:], render=_render, fetch=_fetch,
                   description=__doc__, prog="hit_testing.py")

if __name__ == "__main__":
    sys.exit(main())
```

## Key Insights (The "Aha" Moments)

### 1. Lazy provenance -- zero cost when unused

`Buffer._ids` starts as `None`. The `_ensure_ids()` method allocates the
provenance grid only on the first `put_id()` call. Every existing painted
app that doesn't use `Block.id` pays zero memory and zero runtime for hit
testing. The demo should make this visible at zoom 3 by showing a Buffer
before and after id-bearing paint.

### 2. Two id representations that unify

- `Block.id` (uniform): every cell in the block has the same id. Cheap to
  store (one string), cheap to propagate through `pad()` and `border()`.
- `Block._ids` (per-cell matrix): each cell has its own id. Created
  automatically by composition functions when blocks with different ids
  are joined.

The user never creates `_ids` directly. They assign `Block.id` at leaf
level, and composition functions (`join_horizontal`, `join_vertical`,
`border(id=...)`) produce `_ids` as needed. The two representations are
an internal optimization, transparent to the caller.

### 3. Composition propagation rules

| Operation | Block.id | Block._ids | Notes |
|-----------|----------|------------|-------|
| `Block.text(id="x")` | "x" | None | Uniform |
| `join_horizontal(a, b)` where a.id or b.id | None | matrix | Gap cells -> None |
| `join_vertical(a, b)` | None | matrix | Width-padding -> None |
| `pad(b)` where b.id, no _ids | b.id | None | Uniform preserved |
| `pad(b)` where b._ids | None | padded matrix | Padding cells -> None |
| `border(b)` where b.id, no border id | b.id | None | Uniform preserved |
| `border(b, id="frame")` | None | matrix | Border cells -> "frame", inner -> b.id |
| `truncate(b)` | b.id or None | sliced matrix | Ellipsis cell inherits neighbor id |
| `vslice(b)` | b.id or None | sliced matrix | Row subset preserves ids |

The pattern: uniform ids stay uniform as long as no mixing happens. The
moment two different ids coexist (join, border with explicit id), the
result switches to per-cell `_ids`.

### 4. The round-trip completes at Surface.hit()

In a real TUI app, the usage is:

```python
def on_mouse(self, event: MouseEvent) -> None:
    panel_id = self.hit(event.x, event.y)
    if panel_id:
        self.emit("dashboard.click", panel=panel_id)
```

`Surface.hit()` delegates to `Buffer.hit()` on `self._buf`. No coordinate
translation needed at the Surface level -- the buffer coordinates ARE the
screen coordinates. `BufferView.hit()` handles translation for sub-regions.

The demo doesn't need to be interactive to teach this. The probe table at
zoom 1 shows the exact same lookup that `on_mouse` would perform, just
statically.

## Probe Coordinate Selection

The probes should be carefully chosen to illustrate the composition story:

```
(0, 0)                    -> "api-gateway"    # border corner
(2, 1)                    -> "api-gateway"    # inner content
(panel_width, 0)          -> None             # horizontal gap
(panel_width + 1, 0)      -> "auth-service"   # second panel border
(0, panel_height)         -> None             # vertical gap
(0, panel_height + 1)     -> "worker"         # third panel border
(panel_width, panel_height) -> None           # cross-gap (both gaps)
```

This set covers: border cells, content cells, horizontal gaps, vertical
gaps, and the cross-gap where both gaps intersect. Each tells a different
part of the composition story.

## Demo Ladder Update

```
patterns/
  ...existing...
  hit_testing.py   Hit testing: Block.id -> composition -> Buffer.hit()   (new)
```

## What This Does NOT Cover

- **Interactive mouse handling** -- the `demos/apps/mouse.py` drawing
  canvas already covers live mouse interaction. This demo is about the
  data flow underneath.
- **TestSurface mouse injection** -- TestSurface already supports
  `MouseEvent` in its input queue (verified in `testing.py` source). A
  future demo could combine hit testing with TestSurface mouse replay,
  but that's a separate teaching point.
- **Performance profiling of hit testing** -- the profiler demo already
  covers write-count analysis. Hit testing cost is dominated by the
  `_ensure_ids` allocation, which is a one-time cost.

## Design Rationale

**Why CLI, not TUI?** The teaching point is the data flow, not the
interaction. A TUI would obscure the mechanism by wrapping it in an event
loop. The CLI demo lets the user see the input (Block.id assignments),
the transformation (composition), and the output (hit results) in a single
static rendering. The provenance map at zoom 2 is the visual payoff --
it shows the "invisible" id layer that makes mouse picking work.

**Why probes, not a full id dump?** A full dump of every cell's id would
be noise. The carefully chosen probe coordinates tell a story: "here's a
border cell, here's content, here's a gap, here's the other panel." Each
probe demonstrates a specific composition rule.

**Why not use lens functions?** The dashboard is hand-built from
primitives to show how ids are assigned. Using `shape_lens` or
`tree_lens` would hide the id assignment, which is the whole point of the
demo. The provenance map is also hand-built because it's visualizing the
id layer, not data.
