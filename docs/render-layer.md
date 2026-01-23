# Render Layer Reference

The cell-buffer rendering system. Python equivalent of Ratatui (buffer + diff) + Lip Gloss (styled composition) + Bubbles (interactive components).

## Mental Model

```
Keypress → on_key() → state transition → mark_dirty()
Timer    → update()  → state transition → mark_dirty()

                    ┌──────────────────────────────────┐
  mark_dirty() ───►│ render()                          │
                    │   state → StyledBlock → paint()   │
                    └──────────────┬───────────────────┘
                                   ▼
                    ┌──────────────────────────────────┐
                    │ _flush()                          │
                    │   buf.diff(prev) → write_frame()  │
                    └──────────────────────────────────┘
                                   ▼
                              Terminal
```

State is frozen. Rendering is a pure function of state. Side effects happen only at the terminal boundary.

## Layers

| Layer | Files | Primitive | Produces |
|-------|-------|-----------|----------|
| R1: Buffer | `cell.py`, `buffer.py`, `writer.py` | `Cell`, `Buffer` | Minimal terminal writes via diff |
| R2: Composition | `block.py`, `compose.py`, `borders.py` | `StyledBlock` | Composed rectangles of cells |
| R3: Components | `components/*.py` | Frozen state dataclasses | State machines + render functions |
| R4: App | `app.py`, `focus.py`, `region.py` | `RenderApp` | Lifecycle, keyboard, frame loop |

Each layer depends only on the one below it.

## R1: Cells and Buffers

### Cell

The atomic display unit. One character + one style. Immutable.

```python
Cell(char="x", style=Style(fg="red", bold=True))
```

### Style

Color + attribute flags. Frozen dataclass.

```python
Style(fg="red", bg=None, bold=True, italic=False, underline=False, reverse=False, dim=False)
```

Colors: named strings (`"red"`), 256-color ints (`196`), or hex RGB (`"#ff0000"`).

`style.merge(other)` — other's non-None/non-False fields override self's.

### Buffer

2D grid of Cells, indexed by (x, y). Fixed dimensions.

```python
buf = Buffer(80, 24)                    # all cells start as Cell(" ", Style())
buf.put(x, y, char, style)             # set one cell (out-of-bounds silently ignored)
buf.put_text(x, y, "hello", style)     # write string horizontally
buf.fill(x, y, w, h, char, style)      # fill rectangle
```

### BufferView

A clipped window into a Buffer with coordinate translation.

```python
view = buf.view(x=10, y=5, width=30, height=10)   # or: buf.region(x, y, w, h)
view.put(0, 0, "x", style)                         # writes to buf[10, 5]
view.put(-1, 0, "x", style)                        # silently clipped
```

### Diff

Compare two buffers, get minimal set of cell writes:

```python
writes: list[CellWrite] = current_buf.diff(previous_buf)
# writes contains cells from current_buf that differ from previous_buf
```

**Important:** `a.diff(b)` returns cells from `a` where `a` differs from `b`. The buffer you call `.diff()` on is the source of truth.

### Writer

Translates CellWrites to ANSI escape sequences. Handles:
- Mode 2026 synchronized output (atomic frame display, no tearing)
- Alternate screen enter/exit
- Cursor show/hide
- Color depth detection

```python
writer = Writer()
writer.enter_alt_screen()
writer.write_frame(writes)    # Mode 2026 brackets + ANSI sequences
writer.exit_alt_screen()
```

## R2: Styled Blocks and Composition

### StyledBlock

Immutable rectangle of cells with known dimensions. The composition currency.

```python
# From text (width inferred)
block = StyledBlock.text("hello", Style(fg="green"))         # width=5, height=1

# From text with width constraint
block = StyledBlock.text("hello world", style, width=8, wrap=Wrap.WORD)  # width=8, height=2

# Empty (spacer)
block = StyledBlock.empty(10, 3, Style())                    # 10x3 of spaces
```

#### Wrap modes

| Mode | Behavior |
|------|----------|
| `Wrap.NONE` | Truncate at width, single line |
| `Wrap.CHAR` | Break at any character |
| `Wrap.WORD` | Break at word boundaries, pad short lines |
| `Wrap.ELLIPSIS` | Truncate with "..." if too long |

#### Paint

Transfer a block's cells into a buffer:

```python
block.paint(buffer_or_view, x=0, y=0)   # clips to buffer bounds
```

### Composition Functions

All produce new StyledBlocks. No mutation.

```python
# Horizontal: side by side
row = join_horizontal(left, right, gap=1, align=Align.CENTER)
# width = sum(widths) + gaps, height = max(heights)

# Vertical: stacked
col = join_vertical(top, bottom, align=Align.START)
# width = max(widths), height = sum(heights)

# Padding: add whitespace
padded = pad(block, left=1, right=1, top=1, bottom=1, style=Style())
# width + left + right, height + top + bottom

# Border: 1-cell frame
bordered = border(block, ROUNDED, Style(fg="yellow"))
# width + 2, height + 2

# Truncate: cut with ellipsis
short = truncate(block, width=10, ellipsis="...")
# min(width, 10), same height
```

#### Align

Used by `join_horizontal` (vertical alignment of shorter blocks) and `join_vertical` (horizontal alignment of narrower blocks):

| Value | join_horizontal | join_vertical |
|-------|----------------|---------------|
| `Align.START` | top-aligned | left-aligned |
| `Align.CENTER` | vertically centered | horizontally centered |
| `Align.END` | bottom-aligned | right-aligned |

### Border Character Sets

```python
ROUNDED  # ╭╮╰╯─│
HEAVY    # ┏┓┗┛━┃
DOUBLE   # ╔╗╚╝═║
LIGHT    # ┌┐└┘─│
ASCII    # ++++ -|
```

## R3: Components

Every component follows the same pattern:

1. **Frozen state dataclass** — holds UI-domain state
2. **Transition methods** — return new instances (pure, no mutation)
3. **Render function** — `(state, width/height, ...) -> StyledBlock`

### Spinner

```python
state = SpinnerState()                    # frame=0, uses DOTS frames
state = state.tick()                      # advance to next frame

block = spinner(state, style=Style(fg="cyan"))  # 1x1 block
```

Frame sets: `DOTS`, `LINE`, `BRAILLE`.

### Progress Bar

```python
state = ProgressState(value=0.5)          # 0.0 to 1.0, clamped
state = state.set(0.75)

block = progress_bar(state, width=20,
                     filled_style=Style(fg="green"),
                     filled_char="█", empty_char="░")
```

### List View

```python
state = ListState(item_count=100)
state = state.move_down()                 # selected: 0 → 1
state = state.move_up()                   # selected: 1 → 0
state = state.move_to(50)                 # jump to index
state = state.scroll_into_view(visible_height=10)  # adjust scroll_offset

items = [StyledBlock.text(name, Style()) for name in names]
block = list_view(state, items, visible_height=10,
                  selected_style=Style(reverse=True),
                  cursor_char="▸")
```

### Text Input

```python
state = TextInputState()
state = state.insert("hello")             # text="hello", cursor=5
state = state.move_left()                 # cursor=4
state = state.delete_back()               # text="helo", cursor=3
state = state.move_home()                 # cursor=0
state = state.move_end()                  # cursor=4

block = text_input(state, width=30,
                   focused=True,
                   placeholder="Type here...",
                   cursor_style=Style(reverse=True))
```

Scroll handling: `text_input()` internally calls `state._ensure_visible(width)` to adjust `scroll_offset` so the cursor is always within the visible window.

### Table

```python
columns = [Column("Name", width=12), Column("Status", width=8, align=Align.END)]
rows = [["Alice", "Online"], ["Bob", "Away"]]

state = TableState(row_count=len(rows))
state = state.move_down()
state = state.scroll_into_view(visible_height=5)

block = table(state, columns, rows, visible_height=5,
              header_style=Style(bold=True),
              selected_style=Style(reverse=True))
```

## R4: Application Lifecycle

### RenderApp

Base class for interactive terminal apps. Subclass and override:

```python
class MyApp(RenderApp):
    def __init__(self):
        super().__init__(fps_cap=30)
        self._state = ListState(item_count=10)

    def layout(self, width: int, height: int) -> None:
        """Called on startup and terminal resize."""
        self._main = Region(0, 0, width, height)

    def update(self) -> None:
        """Called every loop iteration (fps_cap times/sec).
        Advance animations, check timers. Call mark_dirty() if state changed."""

    def render(self) -> None:
        """Called only when dirty. Paint StyledBlocks into self._buf."""
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        block = list_view(self._state, items, height=10)
        block.paint(self._buf, x=0, y=0)

    def on_key(self, key: str) -> None:
        """Called on keypress. Dispatch based on focus."""
        if key == "q":
            self.quit()

asyncio.run(MyApp().run())
```

### Lifecycle Phases

```
run() called
  → enter alt screen, hide cursor
  → size terminal, create buffers
  → layout(width, height)
  → loop:
      keyboard poll → on_key(key) → mark_dirty()
      update()                     → mark_dirty()  (if state changed)
      if dirty: render() → _flush()
      sleep(1/fps_cap)
  → show cursor, exit alt screen
```

### The Dirty Flag

Only `mark_dirty()` triggers a render+flush cycle. Sources:
- `on_key()` — main loop auto-marks dirty after any keypress
- `update()` — you call `mark_dirty()` when animation state changes
- `_on_resize()` — auto-marks dirty on terminal resize

If nothing marks dirty, the loop sleeps at fps_cap with zero terminal writes.

### FocusRing

Tracks which component receives key events:

```python
focus = FocusRing(items=["list", "input", "search"])
focus.next()                  # advance
focus.prev()                  # go back
focus.focus("search")         # jump to specific
print(focus.focused)          # current item ID
```

### Region

Named buffer rectangle, calculated in `layout()`:

```python
region = Region(x=0, y=0, width=40, height=10)
view = region.view(buffer)    # → BufferView for this area
```

## Data Flow: A Complete Keypress

User presses Down Arrow with list focused:

```
1. Terminal sends bytes: \x1b [ B
2. KeyboardInput.get_key() reads \x1b via os.read(fd, 1)
3. Main loop calls on_key("\x1b")
4. on_key dispatches to _handle_list_key
5. _handle_list_key reads "[" then "B" via get_key()
6. self._list_state = self._list_state.move_down()
   → new frozen ListState with selected += 1
7. Main loop sets _dirty = True
8. render() fires:
   a. buf.fill() clears the buffer
   b. list_view(state, items, height) → StyledBlock
   c. block.paint(buf, x, y) → cells written to buffer
9. _flush():
   a. buf.diff(prev) → list of changed CellWrites
   b. writer.write_frame(writes) → ANSI escapes to terminal
   c. prev = buf.clone()
10. Terminal displays updated list with new selection
```

## Double-Buffering

The system maintains two buffers:
- `_buf` — current frame (cleared + painted each render)
- `_prev` — previous frame (for diffing)

After each flush, `_prev = _buf.clone()`. On the next render, only cells that actually changed produce terminal writes. This is why the spinner works efficiently — only the spinner character cell changes each tick, so only 1 cell is written per frame.

## Key Contracts

1. **State is frozen.** All component state dataclasses are `frozen=True`. Transitions return new instances.
2. **Render is pure.** Given the same state, `render()` produces the same buffer content.
3. **Side effects only at the boundary.** `write_frame()` is the only thing that touches the terminal.
4. **Composition is spatial.** Blocks have known dimensions. No flex, no constraints, no layout negotiation.
5. **Dirty-gated rendering.** No work happens unless something changed.
6. **Diff-minimized output.** Only changed cells are written to the terminal.
