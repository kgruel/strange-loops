# cells Architecture

Data-flow reference for the cells TUI framework.

## The Stack

```
┌─────────────────────────────────────────────────────────────┐
│  Terminal                                                   │
│  ANSI escape sequences in, keyboard bytes out               │
├─────────────────────────────────────────────────────────────┤
│  Writer                                                     │
│  Translates Cell changes → ANSI sequences                   │
│  Detects terminal size                                      │
├─────────────────────────────────────────────────────────────┤
│  Buffer (diff engine)                                       │
│  2D grid of Cells                                           │
│  Compares current vs previous, emits only changes           │
├─────────────────────────────────────────────────────────────┤
│  Block / Compose                                            │
│  Immutable rectangles of Cells                              │
│  join_vertical, join_horizontal, pad, border, truncate      │
├─────────────────────────────────────────────────────────────┤
│  Span / Line                                                │
│  Styled text primitives                                     │
│  Span: text + style, Line: sequence of Spans                │
├─────────────────────────────────────────────────────────────┤
│  Cell / Style                                               │
│  Atomic unit: one character + one style                     │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow

### Render Path (State → Terminal)

```
AppState
    │
    ▼
render(state) ─────────────► Blocks
    │                           │
    │                           ▼
    │                      compose (join, pad, border)
    │                           │
    │                           ▼
    │                      Block.paint(buffer, x, y)
    │                           │
    ▼                           ▼
Buffer (current)           Cells written to grid
    │
    ▼
diff(previous, current)
    │
    ▼
Writer.write_cell(x, y, cell) ──► ANSI sequences
    │
    ▼
Terminal
```

### Input Path (Terminal → State)

```
Terminal
    │
    ▼
KeyboardInput.read() ──────► key: str
    │
    ▼
Surface.on_key(key)
    │
    ▼
process_key(key, state, ...) ─► Layer stack routing
    │                              │
    │                              ▼
    │                         top_layer.handle(key, layer_state, app_state)
    │                              │
    │                              ▼
    │                         (new_layer_state, new_app_state, action)
    │                              │
    ▼                              ▼
new AppState ◄──────────────── apply action (Stay/Pop/Push)
```

## Layer Stack

Layers handle input routing and render ordering for modal UI.

```
┌─────────────────────┐
│   Help Layer        │  ← top: handles input first, renders last (on top)
│   state: ()         │
├─────────────────────┤
│   Search Layer      │
│   state: SearchState│
├─────────────────────┤
│   Nav Layer         │  ← base: handles if above pass, renders first
│   state: ()         │
└─────────────────────┘
```

**Input:** Top-down. Top layer handles. Returns action (Stay/Pop/Push).

**Render:** Bottom-up. Base renders, then overlays paint on top.

**Lifecycle:**
- Push: create layer with initial state, add to stack
- Stay: layer continues, state may change
- Pop: remove from stack, optionally return result

## App Loop

```python
class Surface:
    async def run(self):
        # Enter alternate screen
        # Initialize buffer

        while self._running:
            event = await self._wait_for_event()

            if event.is_resize:
                self._buf = Buffer(width, height)
                self.layout(width, height)

            elif event.is_key:
                self.on_key(event.key)

            self.render()      # state → buffer
            self._flush()      # diff → terminal

        # Exit alternate screen
```

## Component Pattern

All stateful elements follow the same pattern:

```python
# 1. State: frozen dataclass
@dataclass(frozen=True, slots=True)
class FooState:
    field: type = default

# 2. Update: pure function, returns new state
def update(state: FooState, input: T) -> FooState:
    return replace(state, field=new_value)

# 3. Render: pure function, state → Block
def render(state: FooState, context: ...) -> Block:
    return Block.text(...)
```

## Layer Pattern

Layers extend the component pattern with stack participation:

```python
@dataclass(frozen=True, slots=True)
class Layer(Generic[S]):
    name: str
    state: S
    handle: Callable[[str, S, AppState], tuple[S, AppState, Action]]
    render: Callable[[S, AppState, BufferView], None]

# Actions
Stay()              # remain active
Pop()               # remove from stack
Pop(result=value)   # remove and return result
Push(layer)         # add new layer on top
```

## Quick Reference

| Primitive | Purpose | Pattern |
|-----------|---------|---------|
| Cell/Style | Atomic styled character | Immutable value |
| Span/Line | Styled text | Immutable value |
| Block | Rectangle of cells | Immutable, composable |
| Buffer | 2D canvas + diff | Mutable (paint target) |
| BufferView | Clipped region | Mutable (delegates to Buffer) |
| Component | Stateful widget | State dataclass + pure functions |
| Layer | Modal input scope | State + handle + render + stack |
| Surface | Main loop | Owns state, orchestrates flow |
