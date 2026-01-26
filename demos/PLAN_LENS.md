# PLAN: LensContext Refactor for Teaching Bench

## Executive Summary

The teaching bench (`demos/bench.py`) currently uses separate slides to represent different zoom levels (cell, cell/detail, cell/source). This plan introduces `LensContext` as the primary rendering pattern, enabling:

1. **Same slide, different zoom** - collapse 36 slides into ~17 by making zoom a rendering parameter
2. **Perspective switching** - minimap as proof of concept for "cool-views"
3. **Cleaner section rendering** - context-first API

## Current Architecture

```
Slide("cell")           →  nav.down="cell/detail"
Slide("cell/detail")    →  nav.down="cell/source"
Slide("cell/source")    →  (terminal)

render_text(section, width) -> Block
render_code(section, width) -> Block
render_demo(section, width, state) -> Block   # state added as afterthought
```

**Problems:**
- 36 slides with redundant structure (12 main + 12 detail + 12 source)
- `render_demo` needed state after initial design, violating uniform signature
- No way to render same content at different zoom levels
- No perspective system for cool-views

## Target Architecture

```
Slide("cell")  with  zoom=[0, 1, 2]
              →  zoom 0: intro text + minimal code
              →  zoom 1: detail + full definition
              →  zoom 2: source from actual file

LensContext(width, zoom, focus, perspective)
text_lens(section, ctx) -> Block
code_lens(section, ctx) -> Block
demo_lens(section, ctx) -> Block
```

---

## Phase 1: Define LensContext

**Goal:** Introduce `LensContext` without breaking existing code.

```python
@dataclass(frozen=True)
class LensContext:
    """Rendering context for all section lenses."""
    width: int
    zoom: int = 0                    # 0=summary, 1=detail, 2=source
    focus: Focus = field(default_factory=lambda: Focus(id="demo"))
    perspective: str = "content"     # "content", "minimap", "source"

    # Component states for Demo sections
    spinner_state: SpinnerState | None = None
    progress_state: ProgressState | None = None
    list_state: ListState | None = None
    text_state: TextInputState | None = None
    table_state: TableState | None = None
    # ...

    @classmethod
    def from_state(cls, state: BenchState, width: int, zoom: int = 0) -> LensContext:
        return cls(width=width, zoom=zoom, focus=state.focus, ...)
```

**Files:** `demos/bench.py`
**Test:** Run bench, verify no behavior change.

---

## Phase 2: Convert render_* to *_lens

**Goal:** Convert section renderers to take `LensContext`.

```python
def text_lens(section: Text, ctx: LensContext) -> Block:
    # zoom 0: single line summary
    # zoom 1: wrapped text (current behavior)
    # zoom 2: with line numbers / source info
    return render_text(section, ctx.width)  # initial passthrough

def section_lens(section: Section, ctx: LensContext) -> Block:
    """Dispatch to appropriate lens."""
    match section:
        case Text(): return text_lens(section, ctx)
        case Code(): return code_lens(section, ctx)
        case Spacer(): return spacer_lens(section, ctx)
        case Demo(): return demo_lens(section, ctx)
```

**Files:** `demos/bench.py`
**Test:** Verify identical behavior (lens functions are pure passthroughs initially).

---

## Phase 3: Collapse Detail/Source Slides

**Goal:** Merge `cell/detail` and `cell/source` into `cell` slide with zoom-based rendering.

1. Add `zoom` to `BenchState`
2. Change navigation:
   - `up` at zoom > 0: decrease zoom (stay on slide)
   - `down` with higher zoom content: increase zoom (stay on slide)
3. Create zoom-aware section types:

```python
@dataclass(frozen=True)
class ZoomText:
    """Text with content per zoom level."""
    levels: tuple[str | Line, ...]  # index = zoom level
    style: Style = field(default_factory=Style)

@dataclass(frozen=True)
class ZoomCode:
    """Code with source per zoom level."""
    levels: tuple[str, ...]  # index = zoom level
    title: str = ""
```

**Migration:** One topic at a time (cell → style → span → ...)

---

## Phase 4: Add Minimap Perspective

**Goal:** Prove perspective switching with a minimap sidebar.

```python
def minimap_lens(slides: dict[str, Slide], current: str, height: int) -> Block:
    """Render slide graph as minimap."""
    nodes = []
    for slide_id, slide in slides.items():
        is_current = slide_id == current
        style = Style(fg="cyan", bold=True) if is_current else Style(dim=True)
        prefix = ">" if is_current else " "
        nodes.append(Block.text(f"{prefix}{slide.title}", style))
    return join_vertical(*nodes[:height])
```

Add perspective toggle:
- `m` key toggles between "content" and "split" (content + minimap sidebar)

---

## Migration Checklist

### Phase 1
- [x] Add `LensContext` dataclass
- [x] Add `from_state()` factory
- [x] Verify bench still runs

### Phase 2
- [x] Add `text_lens`, `code_lens`, `spacer_lens`, `demo_lens`
- [x] Add `section_lens` dispatcher
- [x] Update `_render_nav` to use `section_lens`
- [x] Verify bench still runs

### Phase 3
- [x] Add `zoom` to `BenchState`
- [x] Add `max_zoom` to `Slide`
- [x] Add `ZoomText` and `ZoomCode` section types
- [x] Update navigation for zoom
- [x] Migrate `cell` topic as proof of concept (other topics can be migrated later)

### Phase 4
- [x] Add `show_minimap` to `BenchState`
- [x] Implement `minimap_lens()`
- [x] Add split-view rendering in `_render_nav`
- [x] Add `m` key toggle in `_handle_nav`

---

## Why This Pattern

LensContext addresses:

1. **Section renderer signature evolution** — Context object from start, extensible
2. **Focus management** — Focus state travels with context
3. **Cool-views** — Same content, different perspectives via `perspective` field

Enables from notes.md:
- Minimap: `perspective="minimap"`
- Hierarchy view: `perspective="hierarchy"`
- Types/signatures: `perspective="api"`
