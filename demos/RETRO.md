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

## Suggested Next Steps

1. Decide on immutable vs mutable state pattern (recommend: all immutable)
2. Decide on config-in-state vs config-at-render pattern
3. Add type stubs or better docstrings for discoverability
4. Consider a `table` demo (demo_09)
5. Consider documenting the keyboard key names prominently
