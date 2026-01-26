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

- [x] Self-documenting slides (show source rendering current slide) - via `-vv` mode
- [ ] Slide table of contents view
- [ ] Layer slide in teaching bench

## Verbosity Pattern

Added CLI verbosity flags to bench.py following standard conventions:

```bash
# Default: interactive slideshow
uv run python -m demos.bench

# Quiet: print all slides inline and exit
uv run python -m demos.bench -q

# Verbose: detail slides become primary navigation
uv run python -m demos.bench -v

# Very verbose: add source view (s to toggle panel)
uv run python -m demos.bench -vv
```

Implementation adds:
- `print_block()` in `src/cells/writer.py` - renders Block to stream with ANSI styling
- `invert_navigation_graph()` - transforms detail slides into main flow
- `capture_slide_source()` - extracts source code for -vv mode
- `VerboseBenchApp` - extends BenchApp with verbosity support

See `demos/VERBOSITY.md` for full documentation of the pattern.

## Testing

```bash
# Run all tests (128 total with lens tests)
uv run pytest

# Verify bench imports
uv run python -c "from demos.bench import BenchApp; print('OK')"

# Try lens demo
uv run python demos/demo_10_lens.py
```

---

## Session: Unified Semantic Ecosystem

### The Journey

Started with verbosity flags → Lens primitive → connected to rill's Projection → untangled full ecosystem → grounded vocabulary for all five layers.

### The Five Dimensions

| Dimension | Library | Atom | Question |
|-----------|---------|------|----------|
| **Who** | peers | Peer (name + scope) | Who is acting? What can they see/do? |
| **What** | facts | Fact (kind + ts + data) | What semantic meaning? |
| **When** | ticks | Tick (ts + payload) | When did it happen? How does it flow? |
| **How** | forms | Field (name + type) | What shape? How does it transform? |
| **Where** | cells | Cell (char + style) | Where does it appear? How does it look? |

### Implementation Status

| Library | Repository | Status |
|---------|------------|--------|
| **peers** | TBD | Conceptual - Peer = name + scope, scope cascades |
| **facts** | ~/Code/ev | ✓ Aliases added (Fact, Verdict) |
| **ticks** | ~/Code/rill | ✓ Renamed (rill→ticks, EventStore→Store) |
| **forms** | ~/Code/experiments/forms | ✓ Extracted (Field, Form, Fold) |
| **cells** | ~/Code/cells | ✓ Lens added (shape_lens, zoom levels) |

### Key Insight: Scope Cascades

Peer = name + scope, and scope cascades through everything:
- What facts you can emit/see
- What ticks you can read/write
- What forms you can use
- What cells you can render

### New Artifacts

| File | Purpose |
|------|---------|
| `src/cells/lens.py` | Lens primitive: (state, zoom) → Block |
| `demos/demo_10_lens.py` | JSON inspector with zoom levels |
| `demos/HIERARCHY.md` | cells primitive hierarchy |
| `demos/ECOSYSTEM.md` | Unified ecosystem documentation |
| `demos/VERBOSITY.md` | Verbosity pattern documentation |
| `demos/RETRO_LENS.md` | Lens discovery journey |

### Open Threads for Next Session

1. **peers library** - Peer = name + scope as atomic unit, needs full vocabulary design
2. **Scope semantics** - see/do/ask boundaries, how they cascade
3. **Needs gradient** - Must/Should/May for capability requirements
4. **Feedback loop** - cells emitting facts back into ticks (UI observability)
5. **forms integration** - wire forms into experiments, update imports

### The Ecosystem Flow

```
Peer (scoped identity)
  └─ emits → Fact → Store → Projection → State → Lens → Block
                                          ↑
                                        Form
```

See `ECOSYSTEM.md` for full documentation.
