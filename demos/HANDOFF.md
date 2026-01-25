# Demos Handoff

## Current State

Two demo systems exist:

1. **Progressive demos (01-08)**: Educational, print-based output for primitives, interactive for app/components
2. **Teaching bench (bench.py)**: Interactive slideshow using cells to teach cells (~1800 lines)

Both are functional and can be run independently.

## Running

```bash
# Progressive demos (non-interactive)
uv run python demos/demo_01_cell.py
uv run python demos/demo_02_buffer.py
# ... through demo_06

# Progressive demos (interactive)
uv run python demos/demo_07_app.py
uv run python demos/demo_08_components.py

# Teaching bench (interactive)
uv run python demos/bench.py
```

## Key Files

| File | Purpose |
|------|---------|
| `demo_01_cell.py` - `demo_08_components.py` | Progressive API introduction |
| `demo_utils.py` | Shared `render_buffer()` helper |
| `bench.py` | Interactive teaching bench |
| `slide_loader.py` | Markdown slide loader (prototype, not integrated) |
| `slides/` | Sample markdown slides (prototype) |
| `RETRO.md` | API friction and patterns discovered |

## Framework Primitives Added

This session added several framework primitives based on patterns discovered in bench development:

### Focus (`src/cells/focus.py`)
```python
Focus(id="sidebar", captured=False)  # immutable state
focus.capture() / focus.release() / focus.toggle_capture()

# Navigation as pure functions
ring_next(items, current)   # wraps at end
ring_prev(items, current)   # wraps at start
linear_next(items, current) # stops at end
linear_prev(items, current) # stops at start
```

### Search (`src/cells/search.py`)
```python
Search(query="", selected=0)  # immutable state
search.type(char) / search.backspace() / search.clear()
search.select_next(match_count) / search.select_prev(match_count)

# Filtering as pure functions
filter_contains(items, query)  # substring match
filter_prefix(items, query)    # prefix match
filter_fuzzy(items, query)     # chars in order (e.g., "fb" matches "FooBar")
```

### Line.to_block (`src/cells/span.py`)
```python
line = Line(spans=(Span("hello", style), ...))
block = line.to_block(width)  # direct conversion, no Buffer round-trip
```

## Teaching Bench Architecture

### Navigation Graph (25 slides)

```
intro → cell → style → span → line → buffer → block → compose → app → focus → search → components
           ↓       ↓      ↓      ↓       ↓       ↓                       ↓        ↓           ↓
       cell/   style/  span/  line/  buffer/ block/               focus/nav  search/   components/
       detail  detail  detail detail  view   detail                          demo      progress
                                                                                           ↓
                                                                                    components/list
                                                                                           ↓
                                                                                    components/text
                                                                                           ↓
                                                                                    components/table
                                                                                           ↓
                                                                                          fin
```

### Key Features
- Arrow key navigation between slides
- `/` for fuzzy search/jump to any slide
- `?` for help overlay
- Tab to focus interactive demos
- Component demos: spinner, progress, list, text input, table
- Focus demo: ring vs linear navigation
- Search demo: contains/prefix/fuzzy filtering

### Current Pain Points (Why Mode Extraction)

The bench has grown to ~1800 lines with repeated patterns:

**Each "mode" (help, search, demo focus) has:**
- State fields scattered in `BenchState`
- Entry/exit logic somewhere in `on_key()`
- Key handling in another block of `on_key()`
- Render logic in `render()` + helper function

These should be bundled as a `Mode` abstraction.

## Next Steps

### Priority: Mode Extraction

Extract the repeated pattern into a `Mode` protocol:

```python
@dataclass
class Mode:
    name: str
    state: Any
    handles_key: Callable[[str, AppState], tuple[bool, AppState]]
    render_overlay: Callable[[AppState, int, int], Block | None]
```

Then refactor:
1. Extract `HelpMode` (simplest, just shows/hides overlay)
2. Extract `SearchMode` (query input, filtering, selection)
3. Extract `DemoFocusMode` (captures keys for widget interaction)
4. Refactor `on_key` to: iterate modes, first handler wins
5. Refactor `render` to: paint base, then paint mode overlays

### Deferred: Content Separation

Prototype exists in `slide_loader.py` for markdown-based slides:

```markdown
---
id: cell
nav:
  left: intro
  right: style
---

# Cell

the atomic unit: one `character` + one `style`

```python
cell = Cell("A", Style(fg="red", bold=True))
```

[demo:spinner]
```

Not integrated yet. After Mode extraction, could:
1. Wire loader into bench (hybrid: markdown + Python fallback)
2. Migrate slides incrementally

### Stretch

- [ ] Self-documenting slides (show source rendering current slide)
- [ ] Slide table of contents view

## Testing

```bash
# Run all tests (71 total)
uv run pytest

# Verify bench imports
uv run python -c "from demos.bench import BenchApp; print('OK')"

# Verify slide graph
uv run python -c "
from demos.bench import build_slides
slides = build_slides()
for sid, s in slides.items():
    for d, t in [('up', s.nav.up), ('down', s.nav.down), ('left', s.nav.left), ('right', s.nav.right)]:
        if t and t not in slides:
            print(f'BROKEN: {sid}.{d} -> {t}')
print(f'{len(slides)} slides, all links valid')
"
```
