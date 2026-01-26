# Primitives Reference

Quick reference for cells primitives. See ARCHITECTURE.md for data flow, DATA_PATTERNS.md for patterns.

---

## Cell / Style

**Style** — Immutable text attributes (fg, bg, bold, italic, underline, reverse, dim).

```python
style = Style(fg="cyan", bold=True)
merged = base_style.merge(overlay_style)  # overlay wins non-None
```

**Cell** — Single character + style. Atomic unit.

```python
cell = Cell("x", style)
# Cells are the leaf data; you rarely create them directly
```

**Connects to:** Buffer stores Cells. Block contains rows of Cells.

---

## Buffer / BufferView

**Buffer** — Mutable 2D grid of Cells with diff support.

| Method | Description |
|--------|-------------|
| `put(x, y, char, style)` | Set single cell |
| `put_text(x, y, text, style)` | Write string (wide-char aware) |
| `fill(x, y, w, h, char, style)` | Fill rectangle |
| `region(x, y, w, h)` | Get clipped BufferView |
| `diff(other)` | List of changed CellWrites |
| `clone()` | Deep copy for diffing |

```python
buf = Buffer(80, 24)
buf.put_text(0, 0, "Hello", Style(fg="green"))
changes = new_buf.diff(old_buf)  # only what changed
```

**BufferView** — Clipped, translated window into a Buffer. Same API as Buffer for put/put_text/fill.

```python
view = buf.region(10, 5, 40, 10)  # x=10, y=5, 40x10
view.put(0, 0, "X", style)        # writes to buf[10,5]
```

**Connects to:** Surface owns Buffer. Blocks paint to Buffer/BufferView. Layers receive BufferView.

---

## Block

**Block** — Immutable rectangle of Cells with known dimensions.

| Method | Description |
|--------|-------------|
| `Block.text(s, style, width=, wrap=)` | Create from string |
| `Block.empty(w, h, style=)` | Space-filled block |
| `paint(buffer, x, y)` | Transfer cells to buffer |
| `row(y)` | Access row by index |

```python
block = Block.text("Status: OK", Style(fg="green"), width=20)
block.paint(buf, 5, 3)
```

**Wrap modes:** `Wrap.NONE`, `Wrap.CHAR`, `Wrap.WORD`, `Wrap.ELLIPSIS`

**Connects to:** Composed via `join_horizontal`, `join_vertical`, `pad`, `border`, `truncate`. Paints to Buffer/BufferView.

---

## Span / Line

**Span** — Text run with single style. Immutable.

```python
span = Span("error", Style(fg="red", bold=True))
print(span.width)  # display width (wide-char aware)
```

**Line** — Sequence of Spans forming one line.

| Method | Description |
|--------|-------------|
| `Line.plain(text, style)` | Single-span line |
| `paint(view, x, y)` | Render to BufferView |
| `truncate(max_width)` | Return truncated Line |
| `to_block(width)` | Convert to Block |

```python
line = Line((Span("Name: "), Span("Alice", Style(bold=True))))
line.paint(view, 0, 0)
```

**Connects to:** Can convert to Block via `to_block()`. Paints directly to BufferView.

---

## Layer

**Layer** — Bundles state + handle + render for modal stacking.

```python
@dataclass(frozen=True, slots=True)
class Layer(Generic[S]):
    name: str
    state: S
    handle: Callable[[str, S, AppState], tuple[S, AppState, Action]]
    render: Callable[[S, AppState, BufferView], None]
```

**Actions:** `Stay()`, `Pop(result=)`, `Push(layer)`, `Quit()`

| Function | Description |
|----------|-------------|
| `process_key(key, state, get_layers, set_layers)` | Route key through stack |
| `render_layers(state, buf, get_layers)` | Render bottom-to-top |

```python
def handle(key, state, app):
    if key == "q":
        return state, app, Pop()
    return replace(state, query=state.query + key), app, Stay()

search_layer = Layer("search", SearchState(), handle, render)
```

**Connects to:** Surface uses process_key/render_layers. Layers contain their own state, receive app state.

---

## Focus

**Focus** — Two-tier focus state (navigation vs captured).

| Method | Description |
|--------|-------------|
| `focus(id)` | Move focus to id, release capture |
| `capture()` | Widget takes keyboard |
| `release()` | Return to navigation |
| `toggle_capture()` | Toggle capture state |

```python
focus = Focus(id="sidebar")
focus = focus.capture()      # sidebar has keyboard
focus = focus.focus("main")  # move to main, released
```

**Navigation functions:** `ring_next`, `ring_prev`, `linear_next`, `linear_prev`

```python
items = ("sidebar", "main", "footer")
next_id = ring_next(items, focus.id)  # wraps around
```

**Connects to:** Lives in app state. Checked by components to style/behavior.

---

## Search

**Search** — Filtered selection state: query + selected index.

| Method | Description |
|--------|-------------|
| `type(char)` | Append to query, reset selection |
| `backspace()` | Remove last char |
| `clear()` | Empty query |
| `select_next(count)` | Move selection down (wrapping) |
| `select_prev(count)` | Move selection up (wrapping) |
| `selected_item(matches)` | Get current selection |

```python
search = Search()
search = search.type("f").type("o")  # query="fo"
matches = filter_contains(items, search.query)
search = search.select_next(len(matches))
item = search.selected_item(matches)
```

**Filter functions:** `filter_contains`, `filter_prefix`, `filter_fuzzy`

**Connects to:** Used by search layers. Filter functions are standalone utilities.

---

## Lens

**Lens** — Bundles render function + zoom metadata for content transformation.

```python
@dataclass(frozen=True, slots=True)
class Lens(Generic[T]):
    render: Callable[[T, int, int], Block]  # (content, zoom, width) -> Block
    max_zoom: int = 2
```

**shape_lens** — Default convention-based renderer for Python data:
- Zoom 0: type/count only (`dict[3]`, `list[5]`)
- Zoom 1: summary (keys, truncated values)
- Zoom 2: full representation

```python
from cells.lens import shape_lens, SHAPE_LENS

block = shape_lens({"a": 1, "b": 2}, zoom=1, width=40)  # "a, b"
block = shape_lens({"a": 1, "b": 2}, zoom=2, width=40)  # key: value table
```

**Connects to:** Produces Blocks. Nested structures reduce zoom at each level.

---

## Composition Functions

Not a primitive, but essential for combining Blocks.

| Function | Description |
|----------|-------------|
| `join_horizontal(*blocks, gap=, align=)` | Left-to-right |
| `join_vertical(*blocks, align=)` | Top-to-bottom |
| `pad(block, left=, right=, top=, bottom=)` | Add spacing |
| `border(block, chars=, style=, title=)` | Wrap with border |
| `truncate(block, width)` | Clip with ellipsis |

```python
panel = border(pad(content, left=1, right=1), title="Info")
layout = join_horizontal(sidebar, main, gap=1)
```

**Align:** `Align.START`, `Align.CENTER`, `Align.END`
