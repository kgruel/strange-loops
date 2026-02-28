# Resize Handling Investigation

**Date:** 2026-02-27
**Status:** Diagnosis complete, fix not yet implemented
**Symptom:** Visual corruption on terminal resize -- overlapping text, misaligned columns, partial old-frame artifacts

---

## Root Cause Analysis

The bug is a **framework-level issue in `Surface._on_resize`** (not demo-specific). It affects all Surface applications. The core problem is that on resize, `_on_resize` creates fresh buffers but does **not** clear the terminal screen. The diff-render system then compares two empty buffers of the new size, finds no differences, and writes nothing -- leaving the terminal displaying the old frame's content at the old dimensions.

### The precise sequence of failure

1. Terminal emits SIGWINCH.
2. `Surface._on_resize` runs (`src/painted/app.py`, line 199-206):
   ```python
   def _on_resize(self) -> None:
       width, height = self._writer.size()
       self._buf = Buffer(width, height)      # fresh empty buffer
       self._prev = Buffer(width, height)      # fresh empty buffer
       self.layout(width, height)
       self._dirty = True
   ```
3. `self._dirty = True` triggers a render on the next loop iteration.
4. `render()` paints the new content into `self._buf` (now at the new dimensions).
5. `_flush()` runs `self._buf.diff(self._prev)` -- comparing the rendered buffer against a fresh empty buffer of the same new dimensions.
6. The diff correctly identifies all non-empty cells as changed and writes them.
7. **But the terminal still has the old frame's pixels on screen.** Any cells that were painted in the old frame but are now empty in the new frame (or in different positions) remain visible because nothing clears them.

### Why it's worse than "just stale pixels"

When the terminal resizes, terminal emulators reflow or truncate content but do **not** clear the alt-screen buffer. So the old frame's ANSI-painted cells persist at their old positions. The new frame is painted on top at new positions. Where the old and new frames overlap differently, you get the reported symptoms:

- **Overlapping text:** Old content at position (30, 5) remains; new content paints at (25, 5). Both visible.
- **Misaligned columns:** A two-column layout computed for 120 cols now renders at 80 cols, but the old 120-col layout's right column still shows through.
- **Partial old frame:** If the new terminal is smaller, cells beyond the new bounds are invisible, but cells within the new bounds that happen to be "empty" in the new frame still show old content.

### The key gap

`Writer` has no `clear_screen()` method. There is no `\x1b[2J` (Erase Display) or `\x1b[3J` (Erase Scrollback) emitted anywhere in the codebase. The diff-based rendering was designed assuming **same-dimension frames**, which is true for every frame except the first one after a resize.

---

## Affected Code Paths

### Primary

| File | Location | Role |
|------|----------|------|
| `src/painted/app.py` | `_on_resize()` (line 199-206) | Creates fresh buffers but does not clear the terminal |
| `src/painted/app.py` | `_flush()` (line 208-221) | Runs diff, which only writes *changed* cells (not cleared ones) |
| `src/painted/buffer.py` | `diff()` (line 113-120) | Assumes `self` and `other` have the same dimensions (see below) |
| `src/painted/writer.py` | entire class | No `clear_screen()` method exists |

### Secondary

| File | Location | Role |
|------|----------|------|
| `src/painted/app.py` | `_try_flush_scroll_optimized()` (line 229) | Already guards against dimension mismatch (returns `False`), but this is dead code after `_on_resize` since both buffers match |
| `src/painted/inplace.py` | `InPlaceRenderer` | Has its own resize issues (see Related Concerns) |

---

## Buffer.diff() Dimension Mismatch Bug

`Buffer.diff()` has a latent correctness bug independent of the resize problem:

```python
def diff(self, other: Buffer) -> list[CellWrite]:
    writes: list[CellWrite] = []
    for i in range(len(self._cells)):
        if self._cells[i] != other._cells[i]:
            y, x = divmod(i, self.width)
            writes.append(CellWrite(x, y, self._cells[i]))
    return writes
```

If `self` and `other` have different dimensions:
- Different total cell count: `other._cells[i]` can raise `IndexError`.
- Same total cell count but different width: `divmod(i, self.width)` produces wrong (x, y) coordinates because the row stride differs.

Currently this is masked because `_on_resize` creates both buffers with matching dimensions. But it means any "dimension-aware diff" fix must handle this explicitly -- you cannot simply skip resetting `_prev` and expect diff to handle it.

---

## Scope: Framework Bug

This is **not** demo-specific. Every Surface subclass is affected because:

1. All demos that do a full `_buf.fill()` at the start of `render()` (most of them) will still show corruption because the terminal itself is not cleared.
2. The fill writes every cell of the *new* buffer, and the diff emits writes for every cell that differs from `_prev` (which is empty). But the terminal may have content from the old frame in positions that the new frame also fills -- in that case the write happens and the cell looks correct. The corruption appears specifically where:
   - Old frame had content at a position that the new frame leaves empty
   - Old frame had content at a position that the new frame fills differently (e.g., width shift means the "same" content is now offset)

Demos that use `self._buf.fill(0, 0, w, h, " ", Style())` to blank the entire buffer before rendering *do* write every cell via diff. So the question is: does writing a space cell to a terminal position where old styled content exists fully overwrite it? Yes, if the diff emits a CellWrite for that position. And it will, because `_prev` is empty (all `EMPTY_CELL` which is `Cell(" ", Style())`), and the fill writes `Cell(" ", Style())` -- **which is the same as `EMPTY_CELL`**. So the diff sees no change for those cells, and does not emit writes for them.

This confirms: even demos that "clear" the buffer still show corruption, because their clear writes `EMPTY_CELL` which matches the fresh `_prev`, so the diff skips those positions entirely.

---

## Fix Options

### Option A: Clear screen on resize (simple, minimal flicker)

Add a `clear_screen()` method to `Writer` and call it in `_on_resize`:

```python
# In Writer:
def clear_screen(self) -> None:
    """Erase entire display."""
    self._stream.write("\x1b[2J")
    self._stream.flush()

# In Surface._on_resize:
def _on_resize(self) -> None:
    width, height = self._writer.size()
    self._buf = Buffer(width, height)
    self._prev = Buffer(width, height)
    self._writer.clear_screen()       # <-- new
    self.layout(width, height)
    self._dirty = True
    self.emit("ui.resize", width=width, height=height)
```

**Pros:** One line change. Correct for all apps. Matches what most TUI frameworks do (e.g., curses calls `clear()` on resize).

**Cons:** One frame of blank screen before the new content renders. In practice this is sub-millisecond and happens during the synchronous `_on_resize` handler, so the render follows immediately. Flicker is negligible with synchronized output (mode 2026), which is already enabled in `write_frame`.

**Variant:** Combine the clear with the subsequent frame's synchronized output block. Emit `\x1b[2J` inside the next `write_frame` call's sync block so the erase and repaint are atomic from the terminal's perspective. This would require a flag (`_needs_full_clear`) checked in `_flush`.

### Option B: Force full repaint via _prev invalidation

Instead of clearing the screen, make `_prev` contain "wrong" content so the diff produces writes for every cell:

```python
def _on_resize(self) -> None:
    width, height = self._writer.size()
    self._buf = Buffer(width, height)
    # Fill _prev with a sentinel that won't match any real content
    self._prev = Buffer(width, height)
    sentinel = Cell("\x00", Style())  # null char never appears in real rendering
    self._prev._cells = [sentinel] * (width * height)
    self.layout(width, height)
    self._dirty = True
    self.emit("ui.resize", width=width, height=height)
```

**Pros:** No separate clear escape sequence needed. The next diff will emit a CellWrite for every cell, effectively doing a full repaint through the existing rendering path. Works within the synchronized output block.

**Cons:** Writes every cell even if the terminal would have been fine (wastes bandwidth on large terminals). More of a hack -- sentinel values are fragile. Does not actually erase terminal content at positions beyond the new buffer dimensions (if terminal shrunk), though those positions are off-screen anyway.

### Option C: Wrap the clear + full render in a synchronized output block

This is Option A done correctly -- the clear and render are atomic:

```python
def _on_resize(self) -> None:
    width, height = self._writer.size()
    self._buf = Buffer(width, height)
    self._prev = Buffer(width, height)
    self._needs_clear = True           # <-- flag
    self.layout(width, height)
    self._dirty = True
    self.emit("ui.resize", width=width, height=height)

def _flush(self) -> None:
    if self._buf is None or self._prev is None:
        return

    if self._scroll_optimization and self._try_flush_scroll_optimized():
        self._prev = self._buf.clone()
        self._needs_clear = False
        return

    writes = self._buf.diff(self._prev)

    if self._needs_clear:
        # Force full repaint: prepend a clear, diff against empty means all cells written
        self._writer.clear_and_write_frame(writes)
        self._needs_clear = False
    elif writes:
        self._writer.write_frame(writes)

    self._prev = self._buf.clone()
```

Where `clear_and_write_frame` wraps `\x1b[2J` inside the synchronized output block alongside the cell writes, so the terminal shows the erase and repaint as a single atomic operation (zero flicker).

**Pros:** Zero flicker. Correct. Minimal changes.

**Cons:** Slightly more complex than Option A.  Adds a flag to Surface state. But the flag is simple boolean, reset after one use.

### Recommendation: Option C

Option C is the correct approach. The synchronized output protocol (mode 2026) was designed exactly for this -- batching terminal state changes into an atomic update. The clear + full repaint should be one operation.

---

## Test Strategy

### Unit test: TestSurface with mid-run resize

`TestSurface` (`src/painted/tui/testing.py`) currently has no resize support. Add a `resize(width, height)` method:

```python
class TestSurface:
    def resize(self, width: int, height: int) -> None:
        """Simulate a terminal resize (SIGWINCH)."""
        self.width = width
        self.height = height
        self.surface._buf = Buffer(width, height)
        self.surface._prev = Buffer(width, height)
        self.surface.layout(width, height)
        self.surface._dirty = True
```

Then a test that:

1. Creates a Surface subclass that fills every cell with a character.
2. Renders at 80x24.
3. Resizes to 60x20.
4. Renders again.
5. Asserts that the captured frame has exactly 60x20 dimensions.
6. Asserts that no cell from the old frame "leaks" -- every cell in the captured buffer is the expected content.

This tests the buffer-level correctness. For the terminal-level clear, we need to also capture the ANSI output and verify that a clear sequence appears before the cell writes on the resize frame.

### Integration test: ANSI output verification

Use `TestSurface` with `write_ansi=True` and a `StringIO` stream. After resize, inspect the stream content for `\x1b[2J` (or equivalent clear) within the synchronized output block.

### Regression structure

```python
class TestResizeHandling:
    def test_resize_produces_correct_dimensions(self):
        """Buffer dimensions match new terminal size after resize."""
        ...

    def test_resize_clears_stale_content(self):
        """No cells from pre-resize frame appear in post-resize buffer."""
        ...

    def test_resize_emits_clear_sequence(self):
        """ANSI clear screen sequence appears in output on resize frame."""
        ...

    def test_resize_diff_covers_all_cells(self):
        """Post-resize diff produces writes for every cell (full repaint)."""
        ...

    def test_multiple_rapid_resizes(self):
        """Multiple resizes between renders produce correct final state."""
        ...
```

---

## Related Concerns

### Scroll optimization interaction

`_try_flush_scroll_optimized()` already guards against dimension mismatch (line 229):

```python
if cur.width != prev.width or cur.height != prev.height:
    return False
```

After `_on_resize`, both buffers match in dimensions, so this guard does not help. But the scroll optimization could produce incorrect results if it fires on the resize frame -- the "previous" buffer is empty, so scroll detection would find no matching lines and fall through to normal diff. This is safe. No additional change needed, but the `_needs_clear` flag from Option C should also disable scroll optimization for that frame (which it does, since the flag check runs before scroll optimization in the proposed code).

### InPlaceRenderer resize

`InPlaceRenderer` (`src/painted/inplace.py`) operates outside alt-screen, using cursor movement to overwrite previous output. On resize:

- Terminal reflow can change which line the output starts on.
- `_height` tracks lines written, but reflow can split or merge lines.
- There is no SIGWINCH handler in `InPlaceRenderer`.

This is a separate issue. `InPlaceRenderer` is designed for non-interactive CLI output (spinners, progress), where resize is uncommon and the visual cost of a glitch is low. Filing separately would be appropriate, but low priority.

### Buffer.diff() should validate dimensions

Even though `_on_resize` currently ensures matching dimensions, `diff()` should guard against mismatched buffers:

```python
def diff(self, other: Buffer) -> list[CellWrite]:
    if self.width != other.width or self.height != other.height:
        # Dimension mismatch: treat every cell as changed
        writes = []
        for i in range(len(self._cells)):
            y, x = divmod(i, self.width)
            writes.append(CellWrite(x, y, self._cells[i]))
        return writes
    ...
```

This is defensive programming. The current code would raise `IndexError` on dimension mismatch. Adding the guard makes the system more robust and is a good change independent of the resize fix.

### Multiple rapid resizes

SIGWINCH can fire multiple times during a drag-resize. The current `_on_resize` handler is synchronous and non-reentrant (Python signal handlers run in the main thread between bytecode instructions). Multiple signals queue and each runs `_on_resize`, creating new buffers each time. The last one wins, which is correct -- intermediate sizes are discarded before rendering. No issue here.

### Alt-screen behavior

Some terminal emulators clear the alt screen on resize, some don't. The fix should not depend on terminal behavior -- always clearing is the safe choice. The synchronized output block ensures the clear + repaint is atomic regardless of terminal implementation.
