# Building TUI Applications with Cells

A practical guide to the cells library for building terminal user interfaces.

## Core Concepts

The cells library implements a **cell-buffer rendering system** for TUI applications:

- **Cell**: Atomic unit (char + Style). Frozen, immutable.
- **Block**: Immutable rectangle of styled cells. Built by composition.
- **Buffer**: 2D grid you paint into. Diff-renders only changed cells.
- **Surface**: Async base class. Manages render loop, terminal state, async tasks.
- **Composition**: Functions like `join_horizontal()`, `join_vertical()`, `pad()`, `border()`.

## Minimal Working Example: Surface Subclass

```python
import asyncio
from cells import Block, Style, border
from cells.tui import Surface

class MinimalApp(Surface):
    """Minimal Surface subclass that renders static content."""

    def render(self) -> None:
        if self._buf is None:
            return

        # Create content block
        text = Block.text("Hello, cells!", Style(fg="green"))
        bordered = border(text, title="Demo")

        # Paint into buffer region
        bordered.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            self.quit()

async def main():
    app = MinimalApp()
    await app.run()

if __name__ == "__main__":
    asyncio.run(main())
```

**Key facts:**
- `render()` is called when the display is dirty (after input or `mark_dirty()`)
- `self._buf` is initialized in `run()` after `layout()` is called (app.py:59)
- Always check `if self._buf is None: return` in render()
- Use `block.paint(buffer_view, x, y)` to paint blocks

---

## Lifecycle: When is `_buf` Initialized?

Surface has a well-defined lifecycle (app.py:49-194):

```
run() called
  └─ enter_alt_screen()
  └─ hide_cursor()
  └─ get terminal size (width, height)
  └─ self._buf = Buffer(width, height)      ← _buf CREATED HERE
  └─ self._prev = Buffer(width, height)
  └─ layout(width, height)                  ← YOUR OVERRIDE: set up regions
  └─ add SIGWINCH handler
  └─ call on_start() if provided
  └─ Main loop:
     └─ drain keyboard input
     └─ update()                            ← Your override: animations, timers
     └─ render() if dirty                   ← Your override: paint to _buf
     └─ _flush(): diff _buf vs _prev, write to terminal
     └─ adaptive sleep

On exit (finally block):
  └─ call on_stop() if provided
  └─ remove SIGWINCH handler
  └─ disable mouse
  └─ show cursor
  └─ exit_alt_screen()
```

---

## Block Creation and Composition APIs

### Creating Blocks

```python
from cells import Block, Style, Cell
from cells.block import Wrap

# Text block (no wrapping)
b1 = Block.text("hello", Style(fg="cyan"), width=20)

# Text with wrapping
b2 = Block.text("long text...", Style(dim=True), width=10, wrap=Wrap.WORD)

# Empty block (fills with spaces)
b3 = Block.empty(width=30, height=10, style=Style(bg="blue"))
```

### Composition Functions

```python
from cells import join_horizontal, join_vertical, pad, border, Align, ROUNDED

# Horizontal join (left-to-right) - VARARGS, not list
h = join_horizontal(block1, block2, block3, gap=2, align=Align.CENTER)

# Vertical join (top-to-bottom) - VARARGS, not list
v = join_vertical(block1, block2, block3, gap=1, align=Align.START)

# Padding
padded = pad(block, left=2, right=2, top=1, bottom=1)

# Border with optional title
bordered = border(block, chars=ROUNDED, title="HEADER")
```

**Important:** `join_vertical(*blocks)` takes varargs. If you have a list, unpack it: `join_vertical(*my_list)`

---

## Running Async Tasks Alongside render()

Use `on_start` and `on_stop` hooks for background tasks:

```python
class AppWithAsync(Surface):
    def __init__(self):
        super().__init__(
            on_start=self._on_start,
            on_stop=self._on_stop,
        )
        self._bg_task = None
        self._latest_data = None

    async def _on_start(self) -> None:
        """Called once when Surface enters main loop."""
        self._bg_task = asyncio.create_task(self._background_work())

    async def _background_work(self) -> None:
        """Long-running task in background."""
        try:
            while True:
                self._latest_data = await self._fetch_data()
                self.mark_dirty()  # Signal re-render
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass

    async def _on_stop(self) -> None:
        """Called when Surface exits."""
        if self._bg_task:
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
```

**Key pattern from nested_flow/viz.py:218-239:**
- Launch task in `_on_start()`
- Update shared state from background task
- Call `mark_dirty()` to signal render needs update
- Cancel task in `_on_stop()` with proper exception handling

---

## Vertex State Integration Pattern

From nested_flow/viz.py:165-204:

```python
class VertexApp(Surface):
    def __init__(self, vertex, runner):
        super().__init__(on_start=self._on_start, on_stop=self._on_stop)
        self._vertex = vertex
        self._runner = runner
        self._runner_task = None

    async def _on_start(self) -> None:
        self._runner_task = asyncio.create_task(self._run_runner())

    async def _run_runner(self) -> None:
        try:
            async for tick in self._runner.run():
                self.mark_dirty()  # Re-render on each tick
        except asyncio.CancelledError:
            pass

    async def _on_stop(self) -> None:
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
        await self._runner.stop()

    def render(self) -> None:
        if self._buf is None:
            return

        # Access vertex state for rendering
        try:
            state = self._vertex.state("health")
            count = state.get("count", 0) if isinstance(state, dict) else 0
        except KeyError:
            count = 0

        block = Block.text(f"Count: {count}", Style(fg="cyan"))
        block.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)
```

---

## Common Gotchas

1. **Forgetting `if self._buf is None: return`** in render()

2. **Not calling `mark_dirty()` after state changes** - the loop only calls render() when dirty

3. **Passing a list to join_vertical** - it takes varargs: `join_vertical(*my_list)`

4. **Not handling `CancelledError` in background tasks**

5. **Forgetting `await self._runner.stop()`** in on_stop

---

## Key Files Reference

| File | Purpose | Key Lines |
|------|---------|-----------|
| `libs/cells/src/cells/app.py` | Surface base class | 49-194: lifecycle |
| `libs/cells/src/cells/block.py` | Block creation | 28-72: text(), 74-79: empty() |
| `libs/cells/src/cells/compose.py` | Composition | 18-45: join_horizontal, 48-80: join_vertical |
| `experiments/nested_flow/viz.py` | Working example | 218-239: async pattern |
| `experiments/cadence_viz.py` | Full multi-panel | 644-717: render layout |
