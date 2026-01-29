# Mouse Input in Terminal UIs

Research findings on terminal mouse protocols and recommendations for cells.

## Protocol Overview

Terminals support mouse input through escape sequences. The application enables
mouse tracking, the terminal reports events as escape sequences on stdin, and
the application parses them alongside keyboard input.

### Tracking Modes (What Gets Reported)

| Mode | DEC | Enable | Description |
|------|-----|--------|-------------|
| X10 | 9 | `\x1b[?9h` | Button press only |
| Normal | 1000 | `\x1b[?1000h` | Press and release |
| Button-event | 1002 | `\x1b[?1002h` | Press, release, and drag (motion while pressed) |
| Any-event | 1003 | `\x1b[?1003h` | All motion, regardless of button state |

Disable by replacing `h` with `l` (e.g., `\x1b[?1003l`).

### Encoding Modes (How Coordinates Are Formatted)

| Mode | DEC | Enable | Format |
|------|-----|--------|--------|
| Legacy | - | (default) | `CSI M Cb Cx Cy` — bytes, limited to 223 cols |
| UTF-8 | 1005 | `\x1b[?1005h` | Same, but UTF-8 encoded (up to 2015) |
| SGR | 1006 | `\x1b[?1006h` | `CSI < Cb ; Cx ; Cy M/m` — decimal, unlimited |
| URXVT | 1015 | `\x1b[?1015h` | `CSI Cb ; Cx ; Cy M` — decimal, no release info |

**SGR (1006) is the modern standard.** It has no coordinate limits and
distinguishes press (`M`) from release (`m`).

## SGR Mouse Protocol (1006)

### Response Format

```
\x1b[<Cb;Cx;CyM   (press)
\x1b[<Cb;Cx;Cym   (release)
```

- `Cb` — button code (decimal)
- `Cx` — column (1-indexed, decimal)
- `Cy` — row (1-indexed, decimal)
- `M` — press, `m` — release

### Button Encoding

The button code `Cb` is a bitmask:

| Bits | Meaning |
|------|---------|
| 0-1 | Button: 0=left, 1=middle, 2=right, 3=release (legacy only) |
| 2 | Shift modifier |
| 3 | Meta/Alt modifier |
| 4 | Control modifier |
| 5 | Motion event |
| 6-7 | Button high bits: 64=scroll up/button4, 65=scroll down/button5 |

**Button values:**

| Cb | Event |
|----|-------|
| 0 | Left press |
| 1 | Middle press |
| 2 | Right press |
| 32 | Left drag (motion with button) |
| 33 | Middle drag |
| 34 | Right drag |
| 35 | Motion (no button, requires mode 1003) |
| 64 | Scroll up |
| 65 | Scroll down |

Add 4/8/16 for Shift/Meta/Ctrl modifiers. Example: Ctrl+left click = 16.

### Scroll Wheel

Scroll events report as button 64 (up) and 65 (down). No release event is sent
for scroll — each scroll "tick" is a single press event. Trackpad scroll
gestures produce these same events, typically in rapid succession.

Horizontal scroll (where supported): button 66 (left) and 67 (right).

### Example Sequences

| Sequence | Meaning |
|----------|---------|
| `\x1b[<0;10;5M` | Left click at column 10, row 5 |
| `\x1b[<0;10;5m` | Left release at column 10, row 5 |
| `\x1b[<64;15;8M` | Scroll up at column 15, row 8 |
| `\x1b[<65;15;8M` | Scroll down at column 15, row 8 |
| `\x1b[<32;12;6M` | Left drag at column 12, row 6 |
| `\x1b[<16;5;3M` | Ctrl+left click at column 5, row 3 |

## Terminal Compatibility

SGR (1006) mouse mode is widely supported:

| Terminal | SGR (1006) | Any-event (1003) | Notes |
|----------|------------|------------------|-------|
| iTerm2 | Yes | Yes | Excellent support, configurable |
| macOS Terminal | Yes | Yes | |
| Windows Terminal | Yes | Yes | |
| Alacritty | Yes | Yes | |
| GNOME Terminal | Yes | Yes | |
| Konsole | Yes | Yes | |
| xterm | Yes | Yes | The reference implementation |
| kitty | Yes | Yes | |
| WezTerm | Yes | Yes | |
| tmux | Pass-through | Pass-through | Requires `set -g mouse on` |

**Legacy terminals without SGR support are rare today.** The main edge case is
tmux/screen multiplexers which pass through mouse sequences but may need
configuration.

## How Other Frameworks Handle This

### Textual (Python)

- Unified event model: `MouseDown`, `MouseUp`, `Click`, `MouseMove`, `MouseScrollUp/Down`
- Events contain: `x`, `y`, `button`, `shift`, `meta`, `ctrl`
- `Click` includes `chain` for double/triple click detection
- Mouse capture: `widget.capture_mouse()` routes all events to one widget
- Scroll events auto-handled by scrollable containers

### Blessed (Python)

- Events come through same `inkey()` as keyboard input
- Button names include modifiers: `"LEFT"`, `"CTRL_LEFT"`, `"LEFT_RELEASED"`
- Scroll: `"SCROLL_UP"`, `"SCROLL_DOWN"`
- Motion: `"MOTION"`, `"LEFT_MOTION"` (drag)
- `MouseEvent` class with `x`, `y`, `button_value`, `released`, `is_wheel`, `is_motion`

### Common Patterns

1. **Unified input stream** — mouse and keyboard events interleave on stdin
2. **Event types** — Click, Press, Release, Move, Scroll (not raw button codes)
3. **Modifiers as flags** — shift/meta/ctrl as booleans, not baked into button
4. **Coordinates** — 0-indexed for application use (protocol uses 1-indexed)
5. **Capture mode** — one widget can claim all mouse events temporarily
6. **Scroll → deltas** — scroll events become +1/-1 deltas for Viewport

## Recommended Approach for cells

### Design Principles

1. **Parallel to keyboard** — `MouseInput` context manager alongside `KeyboardInput`
2. **Same reader** — parse mouse sequences in the same stdin reader (they interleave)
3. **Typed events** — `MouseEvent` dataclass, not raw strings like keyboard
4. **Layer integration** — layers receive both key strings and mouse events
5. **Coordinate translation** — BufferView translates to local coordinates

### Proposed Types

```python
# libs/cells/src/cells/mouse.py

from dataclasses import dataclass
from enum import Enum, auto


class MouseButton(Enum):
    LEFT = 0
    MIDDLE = 1
    RIGHT = 2
    SCROLL_UP = 64
    SCROLL_DOWN = 65
    SCROLL_LEFT = 66
    SCROLL_RIGHT = 67
    NONE = -1  # motion without button


class MouseAction(Enum):
    PRESS = auto()
    RELEASE = auto()
    MOVE = auto()      # motion (drag or hover if mode 1003)
    SCROLL = auto()    # wheel event


@dataclass(frozen=True, slots=True)
class MouseEvent:
    """A mouse event with position, button, and modifiers."""

    action: MouseAction
    button: MouseButton
    x: int              # 0-indexed column
    y: int              # 0-indexed row
    shift: bool = False
    meta: bool = False
    ctrl: bool = False

    @property
    def is_scroll(self) -> bool:
        return self.action == MouseAction.SCROLL

    @property
    def is_click(self) -> bool:
        return self.action == MouseAction.PRESS and self.button in (
            MouseButton.LEFT, MouseButton.MIDDLE, MouseButton.RIGHT
        )

    def translate(self, dx: int, dy: int) -> "MouseEvent":
        """Return event with translated coordinates."""
        return MouseEvent(
            action=self.action,
            button=self.button,
            x=self.x - dx,
            y=self.y - dy,
            shift=self.shift,
            meta=self.meta,
            ctrl=self.ctrl,
        )


def parse_sgr_mouse(params: str, final: str) -> MouseEvent | None:
    """Parse SGR mouse sequence parameters.

    Args:
        params: The parameter string (e.g., "0;10;5")
        final: The final byte ('M' for press, 'm' for release)

    Returns:
        MouseEvent or None if malformed.
    """
    parts = params.split(";")
    if len(parts) != 3:
        return None

    try:
        cb = int(parts[0])
        cx = int(parts[1]) - 1  # Convert to 0-indexed
        cy = int(parts[2]) - 1
    except ValueError:
        return None

    # Decode modifiers
    shift = bool(cb & 4)
    meta = bool(cb & 8)
    ctrl = bool(cb & 16)
    motion = bool(cb & 32)

    # Decode button
    button_bits = cb & 3
    high_bits = cb & 192  # bits 6-7

    if high_bits == 64:
        # Scroll wheel
        button = MouseButton.SCROLL_UP if button_bits == 0 else MouseButton.SCROLL_DOWN
        action = MouseAction.SCROLL
    elif motion:
        # Motion event
        button = MouseButton(button_bits) if button_bits < 3 else MouseButton.NONE
        action = MouseAction.MOVE
    else:
        # Regular button
        button = MouseButton(button_bits) if button_bits < 3 else MouseButton.NONE
        action = MouseAction.RELEASE if final == "m" else MouseAction.PRESS

    return MouseEvent(
        action=action,
        button=button,
        x=cx,
        y=cy,
        shift=shift,
        meta=meta,
        ctrl=ctrl,
    )
```

### Keyboard Integration

Extend `KeyboardInput` to recognize mouse sequences:

```python
# In keyboard.py, extend _read_csi()

def _read_csi(self) -> str | MouseEvent:
    """Read a CSI sequence, returning key name or MouseEvent."""
    params: list[bytes] = []
    while True:
        b = self._read_byte(_ESC_TIMEOUT)
        if b is None:
            return "escape"
        code = b[0]

        # Check for SGR mouse prefix '<'
        if code == 0x3C and not params:  # '<'
            return self._read_sgr_mouse()

        if 0x40 <= code <= 0x7E:
            # Final byte — existing key handling
            ...
        params.append(b)

def _read_sgr_mouse(self) -> MouseEvent | str:
    """Read SGR mouse sequence after '<'."""
    params: list[bytes] = []
    while True:
        b = self._read_byte(_ESC_TIMEOUT)
        if b is None:
            return "escape"
        code = b[0]
        if code in (0x4D, 0x6D):  # 'M' or 'm'
            param_str = b"".join(params).decode("ascii", errors="replace")
            event = parse_sgr_mouse(param_str, chr(code))
            return event if event else "escape"
        params.append(b)
```

### Input Union Type

```python
# The input reader returns either:
Input = str | MouseEvent

# Layer handles both:
@dataclass(frozen=True, slots=True)
class Layer(Generic[S]):
    handle: Callable[[Input, S, Any], tuple[S, Any, Action]]
    # Or keep separate handlers:
    handle_key: Callable[[str, S, Any], tuple[S, Any, Action]]
    handle_mouse: Callable[[MouseEvent, S, Any], tuple[S, Any, Action]] | None
```

### Writer Mouse Mode Control

```python
# In writer.py

def enable_mouse(self, tracking: int = 1003, encoding: int = 1006) -> None:
    """Enable mouse tracking with SGR encoding."""
    self._stream.write(f"\x1b[?{tracking}h")  # Any-event or button-event
    self._stream.write(f"\x1b[?{encoding}h")  # SGR encoding
    self._stream.flush()

def disable_mouse(self, tracking: int = 1003, encoding: int = 1006) -> None:
    """Disable mouse tracking."""
    self._stream.write(f"\x1b[?{tracking}l")
    self._stream.write(f"\x1b[?{encoding}l")
    self._stream.flush()
```

### Surface Integration

```python
# In app.py

class Surface:
    def __init__(self, *, enable_mouse: bool = False, ...):
        self._enable_mouse = enable_mouse

    async def run(self):
        if self._enable_mouse:
            self._writer.enable_mouse()
        try:
            # ... main loop
            while self._running:
                while True:
                    inp = self._keyboard.get_input()  # str | MouseEvent | None
                    if inp is None:
                        break
                    if isinstance(inp, str):
                        self.on_key(inp)
                        self.emit("ui.key", key=inp)
                    else:
                        self.on_mouse(inp)
                        self.emit("ui.mouse", **inp.__dict__)
                    self._dirty = True
        finally:
            if self._enable_mouse:
                self._writer.disable_mouse()
            # ... cleanup

    def on_mouse(self, event: MouseEvent) -> None:
        """Override to handle mouse events."""
        pass
```

### Viewport Scroll Integration

The immediate use case from HANDOFF.md: scroll events → Viewport offset changes.

```python
# In a scrollable component

def handle_mouse(event: MouseEvent, state: ViewportState, app) -> tuple[...]:
    if event.is_scroll:
        delta = -1 if event.button == MouseButton.SCROLL_UP else 1
        new_offset = state.viewport.scroll(delta)
        return replace(state, viewport=new_offset), app, Stay()
    return state, app, Stay()
```

## Implementation Order

1. **MouseEvent types** — `mouse.py` with dataclasses and parsing
2. **Keyboard extension** — detect `CSI <` prefix, delegate to SGR parser
3. **Writer control** — `enable_mouse()` / `disable_mouse()`
4. **Surface plumbing** — opt-in mouse mode, `on_mouse()` callback
5. **Viewport integration** — scroll events adjust offset

## Open Questions

1. **Separate vs unified handler** — Should Layer have one `handle(Input)` or
   separate `handle_key`/`handle_mouse`? Unified is cleaner but changes the
   signature.

2. **Click detection** — Textual tracks `chain` (double-click). Do we need
   this? Requires state and timing logic.

3. **Capture mode** — Should a widget be able to claim all mouse events?
   Useful for drag operations. Adds complexity.

4. **Hover/motion** — Mode 1003 reports all motion. High volume. When is this
   useful? Probably opt-in per component.

5. **Coordinate systems** — Mouse events are screen-absolute. Layer/component
   may want local coordinates. BufferView already does translation — extend
   to MouseEvent?

## Trade-offs

| Approach | Pro | Con |
|----------|-----|-----|
| Mouse as opt-in | No overhead when unused | Extra flag to enable |
| Unified Input type | Clean API | Changes existing Layer signature |
| Separate handlers | Backward compatible | Two callback sites |
| Full motion tracking | Hover effects possible | High event volume |
| Button-event only | Lower overhead | No hover |

## References

- [XTerm Control Sequences](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html) — canonical protocol documentation
- [Textual Input Guide](https://textual.textualize.io/guide/input/) — Textual's mouse handling
- [Blessed Mouse Docs](https://blessed.readthedocs.io/en/latest/mouse.html) — Blessed's approach
- [ESPTerm Overview](https://espterm.github.io/docs/espterm-xterm.html) — clear mode summary
