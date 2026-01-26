# Demo Development Retrospective

## What We Built

8 progressive demos covering the cells library from primitives to full applications:

| Demo | Concept | Interactive |
|------|---------|-------------|
| 01 | Cell/Style — atomic unit | no |
| 02 | Buffer — 2D canvas | no |
| 03 | BufferView — clipped regions | no |
| 04 | Block — immutable rectangles | no |
| 05 | Compose — join, pad, border, truncate | no |
| 06 | Span/Line — styled text | no |
| 07 | RenderApp — event loop | yes |
| 08 | Components — spinner, progress, list, text input | yes |

Plus `demo_utils.py` extracted when `render_buffer()` repeated.

## API Friction Discovered

### 1. Mutable `FocusRing` vs Immutable Everything Else

All state types are frozen dataclasses with methods returning new instances:
- `SpinnerState.tick() -> SpinnerState`
- `ProgressState.set(v) -> ProgressState`
- `ListState.move_up() -> ListState`
- `TextInputState.insert(ch) -> TextInputState`

But `FocusRing` mutates in place:
- `focus.next()` returns `None`, mutates `self`

**Recommendation**: Make `FocusRing` frozen, return new instance from `.next()/.prev()`.

### 2. State/Data Separation Inconsistency

`ListState` separates state from data:
- State holds `selected`, `scroll_offset`, `item_count`
- Items passed to `list_view(state, items=...)`
- But `item_count` is redundant — could derive from `len(items)`

`SpinnerState` embeds configuration:
- State holds `frame` AND `frames: SpinnerFrames`
- Frames aren't passed to `spinner()`, they're in state

**Question**: Which pattern is correct? Embedding config in state, or passing it at render time?

### 3. Keyboard Key Names Undiscoverable

`KeyboardInput.get_key()` returns named strings like `"up"`, `"down"`, `"backspace"` — good design. But:
- Not obvious from the public API
- Had to read `keyboard.py` source to learn this
- The docstring documents it, but it's buried

**Recommendation**: Export a `KEYS` constant or enum, or document in module docstring.

### 4. Component API Signatures Varied

Each component has slightly different conventions:
- `spinner(state, *, style=...)` — frames in state
- `progress_bar(state, width, *, filled_style=..., empty_style=...)` — two style params
- `list_view(state, items, visible_height, *, selected_style=...)` — items separate
- `text_input(state, width, *, focused=..., style=..., cursor_style=...)` — focused flag

Not necessarily wrong, but easy to get wrong without reading each source file.

## What's Not Yet Demoed

- `table` component
- `Region` (unclear what it's for)
- `Writer` / `ColorDepth` internals
- `diff()` / `clone()` — the efficiency story
- `timer` module

## Process Observation

"Development through demo" surfaced API usability issues quickly. Multiple fix cycles on demo_08 revealed the friction points. If these demos existed before library development, the APIs might have been more consistent.

---

## Teaching Bench Session (bench.py)

### What We Built

Interactive teaching bench — a 2D navigable slideshow that uses cells to teach cells:

| Phase | Deliverable |
|-------|-------------|
| 1 | Navigation infrastructure, slide graph (17 slides) |
| 2 | Content rendering: syntax highlighting, `styled()` helper |
| 3 | Interactive demos: spinner, progress, list, text input |
| 4 | Polish: help overlay, focus indicator, visual hierarchy |

~800 lines, self-contained in `bench.py`.

### New API Friction Discovered

#### 5. Focus Management is a Framework Gap

The nav-vs-widget key conflict appeared again. On slides where ↑/↓ navigate *and* a list needs ↑/↓, there's no way to use the list without explicit focus mode.

**Solution implemented**: `demo_focused: bool` state + Tab to toggle + visual feedback (FOCUS badge, dimmed nav).

**Recommendation**: This pattern should be in the framework. `FocusRing` currently only tracks *which* component is focused, not *whether* focus is in "widget mode" vs "navigation mode". Consider:
- `FocusRing.mode: Literal["nav", "widget"]`
- Or a higher-level `FocusManager` that handles this two-tier focus

#### 6. No Line → Block Conversion

Had to write `line_to_block()` helper because there's no direct way to convert a `Line` to a `Block`. The layers are:
```
Buffer (mutable canvas)
  ↑ paint
Block (immutable rectangle)
  ↑ paint
Line/Span (text description)
```

But sometimes you need to go Line → Block for composition (e.g., centering styled text). Currently requires creating a temporary Buffer, painting, then extracting cells.

**Recommendation**: Add `Line.to_block(width: int) -> Block` or `Block.from_line(line: Line)`.

#### 7. Section Renderer Signature Evolution

Started with `render_section(section, width)`, had to change to `render_section(section, width, state)` when adding Demo sections that need app state.

**Pattern**: When building extensible renderers, pass a context object from the start:
```python
@dataclass
class RenderContext:
    width: int
    state: AppState
    # future: theme, focus_id, etc.
```

### Patterns Worth Extracting

1. **Graph navigation**: `Navigation(up=, down=, left=, right=)` — reusable for wizards, multi-pane UIs
2. **Section dispatch**: Union type + isinstance for heterogeneous content
3. **Focus mode**: `focused: bool` + Tab toggle + Escape exit + visual feedback
4. **Overlay pattern**: Render base, then `if show_overlay: overlay.paint(buf, 0, 0)`
5. **styled() helper**: Inline rich text without verbose Span construction

### Stats

- 4 phases, 1 session
- 17 slides covering full Cell → App stack
- 4 interactive widget demos
- 2 new API friction points identified (#5, #6)

---

## Suggested Next Steps

1. Decide on immutable vs mutable state pattern (recommend: all immutable)
2. Decide on config-in-state vs config-at-render pattern
3. Add type stubs or better docstrings for discoverability
4. Consider a `table` demo (demo_09)
5. Consider documenting the keyboard key names prominently
6. **Add `Line.to_block()` or `Block.from_line()`** — fills a real gap
7. **Extend focus management** — two-tier focus (nav mode vs widget mode) is a recurring need
