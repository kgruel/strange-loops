# Demos Handoff

## Current State

Two demo systems exist:

1. **Progressive demos (01-09)**: Educational, print-based output for primitives, interactive for app/components/layer
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
uv run python demos/demo_09_layer.py

# Teaching bench (interactive)
uv run python demos/bench.py
```

## Key Files

| File | Purpose |
|------|---------|
| `demo_01_cell.py` - `demo_08_components.py` | Progressive API introduction |
| `demo_09_layer.py` | Layer primitive demo (modal stacking) |
| `demo_utils.py` | Shared `render_buffer()` helper |
| `bench.py` | Interactive teaching bench |
| `slide_loader.py` | Markdown slide loader (prototype, not integrated) |
| `slides/` | Sample markdown slides (prototype) |
| `RETRO.md` | API friction and patterns discovered |

## Framework Primitives Added

### Layer (`src/cells/layer.py`)

Modal stacking primitive for input handling and rendering. A layer is a **temporary input scope with visual presence**.

```python
# Layer bundles state + handler + renderer
@dataclass(frozen=True)
class Layer(Generic[S]):
    name: str
    state: S
    handle: Callable[[str, S, AppState], tuple[S, AppState, Action]]
    render: Callable[[S, AppState, BufferView], None]

# Actions
Stay()              # remain active
Pop(result=value)   # remove from stack, optionally return result
Push(layer)         # add new layer on top
Quit()              # signal app exit

# Processing
new_state, should_quit, pop_result = process_key(key, state, get_layers, set_layers)
render_layers(state, buffer, get_layers)
```

Key design decisions:
- Layer state is bundled (created on push, gone on pop)
- Follows the component pattern: frozen state + pure functions
- No globals needed for layer-local state
- `Quit()` action replaces magic values for exit signaling
- `Pop(result=...)` enables clean result passing

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

## Documentation

| Doc | Purpose |
|-----|---------|
| `docs/DATA_PATTERNS.md` | Data modeling patterns: frozen state + pure functions |
| `docs/ARCHITECTURE.md` | Data-flow reference: rendering, input, layer stack |

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

### Layer Architecture

The bench uses the Layer primitive for modal UI:

```
┌─────────────────────┐
│   Help Layer        │  ← any key pops
├─────────────────────┤
│   Search Layer      │  ← query input, Enter pops with result
├─────────────────────┤
│   Demo Layer        │  ← widget interaction, Escape pops
├─────────────────────┤
│   Nav Layer         │  ← base: arrow navigation, pushes overlays
└─────────────────────┘
```

Each layer has its own state dataclass:
- `NavLayerState`: slides reference
- `SearchLayerState`: Search primitive + slides reference
- `DemoLayerState`: widget state + handler

## Next Steps

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

Not integrated yet. Could:
1. Wire loader into bench (hybrid: markdown + Python fallback)
2. Migrate slides incrementally

### Stretch

- [ ] Self-documenting slides (show source rendering current slide)
- [ ] Slide table of contents view
- [ ] Layer slide in teaching bench

## Testing

```bash
# Run all tests (94 total)
uv run pytest

# Verify bench imports
uv run python -c "from demos.bench import BenchApp; print('OK')"

# Verify demo_09 imports
uv run python -c "from demos.demo_09_layer import Demo09App; print('OK')"

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
