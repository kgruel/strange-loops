# Responsive Layout Demo Design

Date: 2026-02-27

## Summary

A patterns-level demo (`demos/patterns/responsive.py`) that teaches
width-aware layout using `join_responsive`, `truncate`, `Wrap`, and
explicit width-based rendering decisions. The demo renders a deploy
status dashboard that visibly adapts as terminal width changes, and
composes that adaptation with the zoom axis to show two orthogonal
dimensions of output control.

## Motivation

`join_responsive` exists in the library, is exported from `painted`,
has test coverage, and is used by `theme_carnival.py` -- but no
patterns-level demo teaches the responsive layout workflow. The
existing primitives demo (`demos/primitives/compose.py`) shows
`join_horizontal`, `join_vertical`, `truncate`, and `Wrap` statically.
It never demonstrates width-driven layout adaptation.

CLI tools run in varied environments: full-width terminals, tmux split
panes (40-60 columns), piped through `less`, embedded in CI logs.
A tool that assumes 80+ columns breaks visually in all but one of
those contexts. This demo teaches the pattern for handling that.

## What the Demo Teaches

1. **`join_responsive`** -- the single-function responsive primitive:
   horizontal when blocks fit, vertical when they don't
2. **Width-aware render functions** -- accepting `width` from
   `CliContext` and threading it through layout decisions
3. **Truncation strategies** -- `truncate()` for hard cuts,
   `Wrap.ELLIPSIS` for inline hints, `Wrap.WORD` for reflowed text
4. **Zoom x width orthogonality** -- zoom controls *what data* to
   show, width controls *how to arrange it*. They compose, they don't
   conflict.
5. **Width simulation** -- `COLUMNS=40 uv run ...` as a testing
   technique

## Demo Scenario: Deploy Pipeline Status

A deploy pipeline with stages, services, and health checks. Real-ish
data that has both wide content (hostnames, timestamps, multi-column
tables) and narrow-friendly summaries.

```python
@dataclass(frozen=True)
class ServiceStatus:
    name: str
    host: str
    stage: str          # "build" | "test" | "deploy" | "verify"
    status: str         # "running" | "passed" | "failed" | "pending"
    duration_s: float
    commit: str         # short SHA
    branch: str
    message: str        # commit message (can be long)

@dataclass(frozen=True)
class PipelineData:
    pipeline_id: str
    started: str        # ISO timestamp
    services: tuple[ServiceStatus, ...]
    overall: str        # "running" | "passed" | "failed"
```

Sample data: 5-6 services (api, worker, scheduler, database, cache,
frontend) at various pipeline stages. Long enough commit messages
and hostnames to trigger truncation at narrow widths.

## Width Breakpoints

The demo uses three layout strategies based on available width.
These are explicit `if/elif` checks in the render function, not
automatic -- the composition layer decides, following the principle
from `ZOOM_PATTERNS.md`.

### Narrow (< 50 columns)

Vertical stacking only. No side-by-side panels. Service names
truncated. Commit messages hidden or ellipsized. Timestamps
shortened to time-only (no date).

```
  deploy #a1b2 running
  ──────────────────────────

  api       deploy  running
  worker    test    passed
  scheduler build   running
  database  deploy  passed
  cache     pending
  frontend  pending

  3/6 complete  2m 14s
```

### Medium (50-99 columns)

Status icons inline with names. Commit SHA visible. Two-column
layout for summary stats using `join_responsive` (which will choose
horizontal at this width).

```
  deploy #a1b2c3d running                        3/6 complete
  ─────────────────────────────────────────────────────────────

  + api         deploy-1.prod    deploy  running   45s  a1b2c3d
  + worker      worker-3.prod    test    passed    22s  a1b2c3d
  * scheduler   cron-1.prod      build   running   18s  a1b2c3d
  + database    db-1.prod        deploy  passed    31s  a1b2c3d
    cache       cache-1.prod     pending
    frontend    cdn-1.prod       pending

  passed: 2  running: 2  pending: 2    elapsed: 2m 14s
```

### Wide (100+ columns)

Full detail. Service table with all columns visible. Commit
messages shown (truncated with ellipsis if needed). Side-by-side
summary panels. Bordered sections.

```
  deploy #a1b2c3d running                              elapsed: 2m 14s
  ╭─ Pipeline ──────────────────────────────────────────────────────────────────╮
  │  + api         deploy-1.prod:8443  deploy  running   45s  a1b2c3d  fix … │
  │  + worker      worker-3.prod:9090  test    passed    22s  a1b2c3d  add … │
  │  * scheduler   cron-1.prod:8080    build   running   18s  a1b2c3d  ref … │
  │  + database    db-1.prod:5432      deploy  passed    31s  a1b2c3d  mig … │
  │    cache       cache-1.prod:6379   pending                                │
  │    frontend    cdn-1.prod:443      pending                                │
  ╰─────────────────────────────────────────────────────────────────────────────╯
  ╭─ Summary ──────────╮  ╭─ Stages ──────────────────╮
  │  passed:  2        │  │  build:    1 running       │
  │  running: 2        │  │  test:     1 passed        │
  │  pending: 2        │  │  deploy:   2 (1 pass/1 go) │
  │  failed:  0        │  │  verify:   0               │
  ╰────────────────────╯  ╰───────────────────────────╯
```

## Zoom Interaction

Zoom and width are orthogonal axes. Zoom controls *detail depth*
(how much data). Width controls *spatial arrangement* (how data is
laid out). The demo shows all four zoom levels, and at each zoom
level the width adaptation applies independently.

### Zoom 0: MINIMAL (-q)

One line regardless of width. Width only affects truncation.

```
# Wide:
deploy #a1b2c3d running  3/6 complete  2m 14s

# Narrow:
deploy #a1b2 running 3/6 2m14s
```

### Zoom 1: SUMMARY (default)

Service list with status. Width determines whether columns appear
side-by-side or stack.

- Narrow: name + stage + status only, vertical layout
- Medium: adds host column, inline stats
- Wide: adds commit SHA, bordered table

### Zoom 2: DETAILED (-v)

Full service table plus summary breakdown. Width determines:

- Whether summary panels sit beside the table (wide) or below it
  (narrow) -- via `join_responsive`
- Whether commit messages appear (wide) or are hidden (narrow)
- Whether borders are used (wide) or skipped (narrow, to save 2
  columns of border overhead)

### Zoom 3: FULL (-vv)

Everything. Stage-by-stage breakdown with timing. Width determines:

- Per-stage sections side-by-side (wide) vs stacked (narrow)
- Full commit messages (word-wrapped at wide widths)
- Duration bars (bar width scales with available space)

## Code Sketch

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Responsive layout — same data, three terminal widths.

The dashboard adapts to terminal width. Resize your terminal
or use COLUMNS to see the layout change.

    COLUMNS=40 uv run demos/patterns/responsive.py        # narrow
    uv run demos/patterns/responsive.py                    # medium (default)
    COLUMNS=120 uv run demos/patterns/responsive.py       # wide
    uv run demos/patterns/responsive.py -v                 # detailed
    COLUMNS=40 uv run demos/patterns/responsive.py -v     # detailed + narrow
"""

from painted import (
    Block, Style, Zoom, CliContext,
    border, join_horizontal, join_responsive, join_vertical,
    pad, truncate, run_cli, ROUNDED,
)

# --- Data model (frozen dataclasses) ---
# ... PipelineData, ServiceStatus ...

# --- Sample data ---
SAMPLE_PIPELINE = PipelineData(...)

# --- Width categories ---

def _is_narrow(width: int) -> bool:
    return width < 50

def _is_wide(width: int) -> bool:
    return width >= 100

# --- Render helpers ---

def _service_row(svc: ServiceStatus, width: int) -> Block:
    """One service row, adapted to width."""
    # Always: icon + name + status
    # Medium: + host + duration + SHA
    # Wide: + commit message (truncated)
    ...

def _summary_panel(data: PipelineData) -> Block:
    """Status counts panel."""
    ...

def _stage_panel(data: PipelineData) -> Block:
    """Per-stage breakdown panel."""
    ...

# --- Zoom renderers ---

def _render_minimal(data: PipelineData, width: int) -> Block:
    """One line, truncated to width."""
    ...

def _render_summary(data: PipelineData, width: int) -> Block:
    """Service list. Width controls column visibility."""
    rows = [_service_row(svc, width) for svc in data.services]
    table = join_vertical(*rows)

    # Responsive footer: horizontal if room, vertical if not
    footer = join_responsive(
        _summary_panel(data),
        _stage_panel(data),
        available_width=width,
        gap=2,
    )
    return join_vertical(table, Block.text("", Style()), footer)

def _render_detailed(data: PipelineData, width: int) -> Block:
    """Full table + panels. Width controls layout mode."""
    rows = [_service_row(svc, width) for svc in data.services]
    table = join_vertical(*rows)

    if _is_wide(width):
        table = border(table, title="Pipeline", chars=ROUNDED)

    panels = join_responsive(
        _summary_panel(data),
        _stage_panel(data),
        available_width=width,
        gap=2,
    )

    if _is_wide(width):
        panels = join_responsive(
            border(pad(_summary_panel(data), left=1, right=1),
                   title="Summary", chars=ROUNDED),
            border(pad(_stage_panel(data), left=1, right=1),
                   title="Stages", chars=ROUNDED),
            available_width=width,
            gap=2,
        )

    return join_vertical(table, Block.text("", Style()), panels)

# --- Dispatch ---

def _render(ctx: CliContext, data: PipelineData) -> Block:
    if ctx.zoom == Zoom.MINIMAL:
        return _render_minimal(data, ctx.width)
    if ctx.zoom == Zoom.SUMMARY:
        return _render_summary(data, ctx.width)
    if ctx.zoom == Zoom.FULL:
        return _render_full(data, ctx.width)
    return _render_detailed(data, ctx.width)

def main() -> int:
    return run_cli(
        sys.argv[1:],
        render=_render,
        fetch=lambda: SAMPLE_PIPELINE,
        description=__doc__,
        prog="responsive.py",
    )
```

## Key Responsive Patterns

### Pattern 1: `join_responsive` for panel layout

The core primitive. Horizontal when panels fit, vertical when they
don't. No breakpoint logic needed for simple cases.

```python
output = join_responsive(
    panel_a, panel_b,
    available_width=width,
    gap=2,
)
```

### Pattern 2: Column visibility by width

Some columns are only useful at wide widths. The render function
decides which columns to include based on available width.

```python
parts = [icon, name_block, status_block]
if not _is_narrow(width):
    parts.append(host_block)
    parts.append(duration_block)
if _is_wide(width):
    parts.append(commit_block)
row = join_horizontal(*parts, gap=1)
```

### Pattern 3: Truncation with `truncate()` and `Wrap.ELLIPSIS`

For content that might exceed its allocated space. `truncate()`
operates on Blocks; `Wrap.ELLIPSIS` operates at `Block.text()`
creation time.

```python
# Block-level truncation
row = truncate(full_row, width=available)

# Text-level truncation
msg = Block.text(commit_msg, Style(dim=True),
                 width=msg_width, wrap=Wrap.ELLIPSIS)
```

### Pattern 4: Border elision at narrow widths

Borders cost 2 columns (left + right). At narrow widths, dropping
borders reclaims space for content. This is an explicit design
decision, not automatic.

```python
if _is_wide(width):
    section = border(pad(content, left=1, right=1),
                     title="Pipeline", chars=ROUNDED)
else:
    section = content
```

### Pattern 5: Width threading from CliContext

Width originates from `shutil.get_terminal_size()` (which reads the
`COLUMNS` env var or queries the terminal). It flows through
`CliContext.width` into render functions. Every render function that
does layout accepts `width` as a parameter.

```
Terminal/COLUMNS
    |
    v
shutil.get_terminal_size()
    |
    v
detect_context() -> CliContext(width=N)
    |
    v
render(ctx, data) -> uses ctx.width for layout
```

## Comparison: Same Data at Three Widths

The demo's docstring shows the invocation pattern that makes
adaptation visible:

```bash
# The three-width comparison:
COLUMNS=40 uv run demos/patterns/responsive.py
COLUMNS=80 uv run demos/patterns/responsive.py
COLUMNS=120 uv run demos/patterns/responsive.py

# Zoom x width matrix (the teaching moment):
COLUMNS=40 uv run demos/patterns/responsive.py -v
COLUMNS=120 uv run demos/patterns/responsive.py -v
```

Running these side by side (or in sequence) makes the adaptation
visible. The same data, the same zoom level, different spatial
arrangement.

## Key Insight

Width-awareness matters because CLI tools are not web pages -- they
run in terminals that vary from 40 to 200+ columns, and the same
tool may be invoked directly, in a tmux pane, through a pipe, or in
a CI log viewer. A tool that assumes one width breaks in all other
contexts.

painted's approach: width and zoom are two orthogonal dimensions of
output control.

- **Zoom** = what to show (detail depth, controlled by `-q`/`-v`)
- **Width** = how to arrange it (spatial layout, controlled by
  terminal size)

They compose: narrow + verbose gives full detail in stacked layout.
Wide + quiet gives minimal info with unused space. The render
function handles both axes independently.

This mirrors the three-axis fidelity model (zoom x mode x format)
with width as a fourth, implicit axis that the render function
manages rather than the CLI harness.

## Integration

- **File:** `demos/patterns/responsive.py` (single file, PEP 723)
- **Demo ladder update:** Add entry to `demos/CLAUDE.md` patterns
  section:
  ```
  responsive.py   Responsive layout: width adaptation, COLUMNS=40/80/120
  ```
- **No interactive mode** -- this teaches static layout adaptation.
  Interactive resize is a different (future) pattern.
- **No `--live`** -- data is static. `run_cli` with `fetch` only.

## What This Does Not Cover

- **Dynamic resize handling** -- that's a TUI concern (Surface
  `layout()` callback). This demo is CLI-level.
- **Automatic zoom reduction** -- per `ZOOM_PATTERNS.md`, zoom and
  width stay orthogonal. The demo does not auto-reduce zoom at
  narrow widths. Truncation with ellipsis signals lost information
  instead.
- **Viewport scrolling** -- horizontal scroll for wide content in
  narrow terminals is a separate pattern.
