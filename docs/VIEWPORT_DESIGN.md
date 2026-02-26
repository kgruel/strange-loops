# Viewport Design

## Problem

Painted has mouse scroll events (`MouseEvent.scroll_delta`) and components like `ListState` and `TableState` that embed scroll management. The scroll logic is duplicated:

```python
# ListState.scroll_into_view
def scroll_into_view(self, visible_height: int) -> ListState:
    offset = self.scroll_offset
    if self.selected < offset:
        offset = self.selected
    elif self.selected >= offset + visible_height:
        offset = self.selected - visible_height + 1
    return replace(self, scroll_offset=offset)

# TableState.scroll_into_view (identical pattern)
def scroll_into_view(self, visible_height: int) -> TableState:
    offset = self.scroll_offset
    if self.selected_row < offset:
        offset = self.selected_row
    elif self.selected_row >= offset + visible_height:
        offset = self.selected_row - visible_height + 1
    return replace(self, scroll_offset=offset)
```

Need: a reusable `Viewport` that tracks scroll state, handles edge cases, and integrates with `vslice()` for rendering.

## Design

### State

```python
@dataclass(frozen=True, slots=True)
class Viewport:
    """Scroll state for a vertically-scrollable view."""

    offset: int = 0           # First visible row (0-indexed)
    visible: int = 0          # Number of visible rows
    content: int = 0          # Total content rows
```

Three values are sufficient:
- `offset`: where the view starts in content space
- `visible`: the viewport height (how many rows fit)
- `content`: total content height

Derived:
- `max_offset = max(0, content - visible)`
- `is_at_top = offset == 0`
- `is_at_bottom = offset >= max_offset`
- `can_scroll = content > visible`

### Operations

All operations return new `Viewport` instances (immutable pattern).

```python
# Scroll by delta (positive = down, negative = up)
def scroll(self, delta: int) -> Viewport

# Scroll to absolute position
def scroll_to(self, position: int) -> Viewport

# Page navigation (jump by visible height)
def page_up(self) -> Viewport
def page_down(self) -> Viewport

# Scroll to top/bottom
def home(self) -> Viewport
def end(self) -> Viewport

# Ensure index is visible (for cursor-follows-selection)
def scroll_into_view(self, index: int) -> Viewport

# Apply mouse scroll event directly
def apply_scroll(self, delta: int) -> Viewport  # alias for scroll()
```

### Integration with vslice

The Viewport works with `vslice()` for rendering:

```python
# Render pattern
def render(content: Block, viewport: Viewport) -> Block:
    return vslice(content, viewport.offset, viewport.visible)
```

Viewport doesn't call `vslice` itself—it just holds the slice parameters. This keeps Viewport pure data and lets the render layer choose how to slice.

### Integration with MouseEvent

```python
# In event handler
def on_mouse(self, event: MouseEvent) -> AppState:
    if event.is_scroll:
        return replace(self, viewport=self.viewport.scroll(event.scroll_delta))
    return self
```

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Content smaller than viewport | `max_offset = 0`, scrolling has no effect |
| Scroll past top | Clamps to 0 |
| Scroll past bottom | Clamps to `max_offset` |
| Zero visible height | `max_offset = content`, all offsets valid |
| Zero content height | `max_offset = 0`, offset always 0 |
| `scroll_into_view(index)` where index < offset | Scroll up to show index at top |
| `scroll_into_view(index)` where index >= offset + visible | Scroll down to show index at bottom |

## Implementation

```python
@dataclass(frozen=True, slots=True)
class Viewport:
    """Scroll state for a vertically-scrollable view."""

    offset: int = 0
    visible: int = 0
    content: int = 0

    @property
    def max_offset(self) -> int:
        """Maximum valid offset (0 if content fits in viewport)."""
        return max(0, self.content - self.visible)

    @property
    def can_scroll(self) -> bool:
        """True if content exceeds viewport."""
        return self.content > self.visible

    @property
    def is_at_top(self) -> bool:
        return self.offset == 0

    @property
    def is_at_bottom(self) -> bool:
        return self.offset >= self.max_offset

    def _clamp(self, offset: int) -> int:
        """Clamp offset to valid range."""
        return max(0, min(offset, self.max_offset))

    def scroll(self, delta: int) -> Viewport:
        """Scroll by delta rows. Positive = down, negative = up."""
        return replace(self, offset=self._clamp(self.offset + delta))

    def scroll_to(self, position: int) -> Viewport:
        """Scroll to absolute position."""
        return replace(self, offset=self._clamp(position))

    def page_up(self) -> Viewport:
        """Scroll up by one page (visible height)."""
        return self.scroll(-self.visible)

    def page_down(self) -> Viewport:
        """Scroll down by one page (visible height)."""
        return self.scroll(self.visible)

    def home(self) -> Viewport:
        """Scroll to top."""
        return replace(self, offset=0)

    def end(self) -> Viewport:
        """Scroll to bottom."""
        return replace(self, offset=self.max_offset)

    def scroll_into_view(self, index: int) -> Viewport:
        """Adjust offset to ensure index is visible."""
        if index < self.offset:
            return replace(self, offset=index)
        elif index >= self.offset + self.visible:
            return replace(self, offset=index - self.visible + 1)
        return self

    def with_content(self, content: int) -> Viewport:
        """Return viewport with updated content height, clamping offset."""
        new = replace(self, content=content)
        return replace(new, offset=new._clamp(new.offset))

    def with_visible(self, visible: int) -> Viewport:
        """Return viewport with updated visible height, clamping offset."""
        new = replace(self, visible=visible)
        return replace(new, offset=new._clamp(new.offset))
```

## Usage Examples

### Basic scrolling with mouse

```python
@dataclass(frozen=True)
class LogViewState:
    lines: tuple[str, ...]
    viewport: Viewport

def on_mouse(state: LogViewState, event: MouseEvent) -> LogViewState:
    if event.is_scroll:
        return replace(state, viewport=state.viewport.scroll(event.scroll_delta))
    return state

def render(state: LogViewState, width: int, height: int) -> Block:
    # Update viewport for current dimensions
    vp = state.viewport.with_visible(height).with_content(len(state.lines))

    # Build content block
    content = join_vertical(*[Block.text(line, Style(), width=width) for line in state.lines])

    # Slice to visible portion
    return vslice(content, vp.offset, vp.visible)
```

### Selection tracking

```python
@dataclass(frozen=True)
class ListViewState:
    items: tuple[str, ...]
    selected: int
    viewport: Viewport

def move_down(state: ListViewState) -> ListViewState:
    new_selected = min(len(state.items) - 1, state.selected + 1)
    new_viewport = state.viewport.scroll_into_view(new_selected)
    return replace(state, selected=new_selected, viewport=new_viewport)
```

## Location

`libs/painted/src/painted/viewport.py` — new file in the CLI core layer (no TUI dependencies).

Export from `painted/__init__.py` alongside `Block`, `Span`, etc.

## Why Not Extend ListState/TableState?

The existing components bake in selection + scrolling. Viewport extracts just the scrolling concern:

1. **Reusable**: Works for any scrollable content (logs, text, images, custom)
2. **Composable**: Selection logic stays separate—combine as needed
3. **Testable**: Pure data, easy to unit test scroll edge cases
4. **Simple**: Three fields, ~50 lines of implementation

ListState/TableState can migrate to use Viewport internally (future refactor), but that's out of scope for initial implementation.
