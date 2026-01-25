# Demos Handoff

## Current State

Two demo systems exist:

1. **Progressive demos (01-08)**: Educational, print-based output for primitives, interactive for app/components
2. **Teaching bench (bench.py)**: Interactive slideshow using cells to teach cells

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
| `bench.py` | Interactive teaching bench (~800 lines) |
| `DEMO_ROADMAP.md` | Phased implementation plan for bench |
| `RETRO.md` | API friction and patterns discovered |

## Teaching Bench Architecture

### Data Model

```python
Slide(id, title, sections, nav, on_key)
Navigation(up, down, left, right)  # graph links
Section = Text | Code | Spacer | Demo

BenchState(current_slide, demo_focused, show_help, ...component_states...)
```

### Navigation Graph

```
intro → cell → style → span → line → buffer → block → compose → app → components
           ↓        ↓                    ↓                              ↓
       cell/detail  style/detail    buffer/view               components/progress
                                                                        ↓
                                                              components/list
                                                                        ↓
                                                              components/text
                                                                        ↓
                                                                       fin
```

Horizontal (←→) = peer concepts. Vertical (↑↓) = depth on same concept.

### Key Patterns Used

**1. Section Dispatch**
```python
def render_section(section: Section, width: int, state: BenchState) -> Block:
    if isinstance(section, Text): return render_text(...)
    elif isinstance(section, Code): return render_code(...)
    # ...
```

**2. Focus Mode**
```python
# State
demo_focused: bool = False

# Toggle
if key == "tab": state = replace(state, demo_focused=not focused)

# Visual feedback
if state.demo_focused:
    parts.append(Block.text(" FOCUS ", Style(fg="black", bg="cyan", bold=True)))
```

**3. Overlay Pattern**
```python
def render(self):
    # ... render slide content ...
    if self._state.show_help:
        help_overlay = render_help(width, height)
        help_overlay.paint(self._buf, 0, 0)  # on top
```

**4. styled() Helper**
```python
def styled(*parts: str | tuple[str, Style]) -> Line:
    # styled("a ", ("Cell", KEYWORD), " is one character")
```

## Known Issues / Gaps

### Framework Level

1. **FocusRing is mutable** — inconsistent with other state types
2. **No Line → Block conversion** — `line_to_block()` helper in bench.py fills this gap
3. **Focus mode not in framework** — nav-vs-widget two-tier focus is app-level code

### Bench Specific

1. **No self-documenting slides** — would be nice to show "this slide is rendered by this code"
2. **State is global** — all component states persist across slides (intentional for demo, might not be desired)

## Extending the Bench

### Adding a Slide

```python
"new-topic": Slide(
    id="new-topic",
    title="New Topic",
    sections=(
        Text("explanation", SUBTITLE_STYLE, center=True),
        Code(source="code_here()", title="example"),
        Demo(demo_id="spinner"),  # if interactive
    ),
    nav=Navigation(left="previous", right="next", down="new-topic/detail"),
),
```

### Adding a Section Type

1. Add dataclass in Data Model section
2. Add to `Section` union type
3. Add `render_X()` function
4. Add case to `render_section()` dispatch

### Adding a Demo Widget

1. Add state field to `BenchState`
2. Add case to `render_demo()`
3. Add key handling in `on_key()` under `if focused and demo_id == "X":`
4. If animated, add tick in `update()`

## Next Steps (Suggested)

### Quick Wins

- [ ] Add `table` demo slide (component exists, not demoed)
- [ ] Add depth slides for Span, Line, Block (currently only Cell, Style, Buffer have depth)

### Framework Improvements

- [ ] `Line.to_block()` method
- [ ] Immutable `FocusRing`
- [ ] Two-tier focus manager

### Stretch

- [ ] Self-documenting slides (show source that renders current slide)
- [ ] External slide definitions (YAML/TOML instead of Python)
- [ ] Slide search/jump (/ to search by title)

## Testing

No automated tests for demos — they're manual verification of the library.

```bash
# Verify imports work
uv run python -c "from demos.bench import BenchApp; print('OK')"

# Verify slide graph is valid
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
