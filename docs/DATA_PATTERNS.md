# Data Patterns in cells

This document captures the data modeling patterns used throughout cells. When designing new primitives, follow these patterns for consistency.

## Core Principle

**Frozen state + pure functions.**

All state is immutable (frozen dataclasses). State changes produce new state. Functions are pure: same inputs → same outputs, no side effects.

This enables:
- Predictable rendering (state → visual output)
- Efficient diffing (compare previous vs current)
- Simple reasoning (no hidden mutations)

## The Three Layers

cells has three conceptual layers, each with its own pattern:

### 1. Rendering Primitives

**Purpose:** Represent styled terminal content.

**Pattern:** Immutable data with computed properties.

```python
@dataclass(frozen=True, slots=True)
class Style:
    fg: str | None = None
    bg: str | None = None
    bold: bool = False
    ...

@dataclass(frozen=True, slots=True)
class Cell:
    char: str
    style: Style

@dataclass(frozen=True, slots=True)
class Span:
    text: str
    style: Style

    @cached_property
    def width(self) -> int: ...  # derived, not stored
```

**Key traits:**
- No update methods (create new instances instead)
- Properties derive from data, never stored redundantly
- Composition via functions, not methods

### 2. Composition Functions

**Purpose:** Combine Blocks into larger Blocks.

**Pattern:** Pure functions: `Block → Block` or `(Block, Block) → Block`.

```python
def join_vertical(*blocks: Block) -> Block: ...
def pad(block: Block, left: int = 0, ...) -> Block: ...
def border(block: Block, chars: BorderChars, style: Style) -> Block: ...
```

**Key traits:**
- Inputs unchanged (immutable)
- Output is new Block
- No state, no side effects
- Composable: `border(pad(join_vertical(a, b)))`

### 3. Components

**Purpose:** Stateful UI elements (spinner, list, text input).

**Pattern:** State dataclass + pure functions.

```python
# State: frozen dataclass with all component data
@dataclass(frozen=True, slots=True)
class ListViewState:
    selected: int = 0
    scroll_offset: int = 0

# Render: state → Block (pure)
def render(state: ListViewState, items: list[str], visible: int) -> Block: ...

# Update: (state, input) → state (pure)
def select_next(state: ListViewState, item_count: int) -> ListViewState:
    return replace(state, selected=min(state.selected + 1, item_count - 1))
```

**Key traits:**
- State is a value, not an object with identity
- App owns state instances, component provides functions
- Update functions return new state, never mutate
- Render is pure: same state → same Block

### 4. App-Level Primitives

**Purpose:** Coordinate input handling and rendering across the app.

**Pattern:** State dataclass + handler + renderer, following the component pattern.

```python
# State: frozen dataclass
@dataclass(frozen=True, slots=True)
class SearchState:
    query: str = ""
    selected: int = 0

# Handler: (input, local_state, app_state) → (local_state, app_state, action)
def handle(key: str, state: SearchState, app: AppState) -> tuple[SearchState, AppState, Action]: ...

# Renderer: (local_state, app_state, view) → None
def render(state: SearchState, app: AppState, view: BufferView) -> None: ...
```

**Key traits:**
- Same pattern as components: frozen state + pure functions
- Handler receives both local state and app state
- Handler returns both (may modify app state on exit, e.g., set selected item)
- Action indicates lifecycle (stay, pop, push)

## State Ownership

**The app owns all state.** Components and layers provide functions; the app holds instances.

```python
@dataclass(frozen=True)
class AppState:
    # App's own state
    current_view: str

    # Component state (app owns these)
    file_list: ListViewState
    search: SearchState

    # Layer stack
    layers: tuple[Layer, ...]
```

This keeps state:
- Visible (all in one place)
- Serializable (just data, no functions)
- Inspectable (print state, see everything)

## When to Create New State vs Reuse

**Create new state type when:**
- The data has its own lifecycle (created, updated, discarded)
- Multiple instances might exist
- The data is conceptually independent

**Reuse/inline when:**
- It's just a field or two
- Lifecycle is tied to parent
- No independent meaning

Example: `Search` is its own type (query + selected, used by search layer). But `show_help: bool` is just a field (no independent lifecycle).

## Actions and Results

When a layer pops, it may need to communicate a result (e.g., "user selected item X").

**Pattern:** Modify app state before returning Pop, or use `Pop(result=...)`.

```python
# Option A: Modify app state directly
def handle(key, state, app):
    if key == "enter":
        selected_item = get_selected(state, app)
        return state, replace(app, current_item=selected_item), Pop()

# Option B: Pop with result (receiver decides what to do)
def handle(key, state, app):
    if key == "enter":
        return state, app, Pop(result=get_selected(state, app))
```

Option A is simpler when the action is known. Option B is better when the layer is reusable and shouldn't know what the parent does with the result.

## Summary

| Layer | State | Functions | Ownership |
|-------|-------|-----------|-----------|
| Primitives | Frozen dataclass | Properties, no update | N/A (values) |
| Composition | N/A | Block → Block | N/A (pure) |
| Components | Frozen dataclass | render, update | App owns instances |
| App-level | Frozen dataclass | handle, render | App owns instances |

**The pattern is always:** frozen state + pure functions. The app owns state. Functions transform state. Rendering derives from state.
