# painted.mouse — Optional Mouse Input

SGR mouse protocol support for interactive TUI applications.

```python
from painted.mouse import MouseEvent, MouseButton, MouseAction
```

- **`MouseEvent`** — `x`, `y`, `button`, `action`
- **`MouseButton`** — `LEFT`, `RIGHT`, `MIDDLE`, `SCROLL_UP`, `SCROLL_DOWN`
- **`MouseAction`** — `PRESS`, `RELEASE`, `MOVE`

Enable mouse in a Surface via the mouse protocol. Use hit testing with `Buffer.hit(x, y)` to map clicks to content.

This is an optional extension. Most TUI apps work fine with keyboard only.
