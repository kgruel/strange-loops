"""List view component: scrollable list with selection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..buffer import Buffer
from ..cell import Style
from ..block import StyledBlock
from ..span import Line, Span


@dataclass(frozen=True)
class ListState:
    """Immutable list state tracking selection and scroll position."""

    selected: int = 0
    scroll_offset: int = 0
    item_count: int = 0

    def move_up(self) -> ListState:
        """Move selection up, clamping to 0."""
        return replace(self, selected=max(0, self.selected - 1))

    def move_down(self) -> ListState:
        """Move selection down, clamping to last item."""
        return replace(self, selected=min(self.item_count - 1, self.selected + 1))

    def move_to(self, index: int) -> ListState:
        """Move selection to a specific index, clamped to valid range."""
        clamped = max(0, min(self.item_count - 1, index))
        return replace(self, selected=clamped)

    def scroll_into_view(self, visible_height: int) -> ListState:
        """Adjust scroll_offset so selected item is visible."""
        offset = self.scroll_offset
        if self.selected < offset:
            offset = self.selected
        elif self.selected >= offset + visible_height:
            offset = self.selected - visible_height + 1
        return replace(self, scroll_offset=offset)


def list_view(
    state: ListState,
    items: list[Line],
    visible_height: int,
    *,
    selected_style: Style = Style(reverse=True),
    cursor_char: str = "▸",
) -> StyledBlock:
    """Render a scrollable list with selection highlight."""
    if not items:
        return StyledBlock.empty(1, visible_height)

    # Determine visible window
    start = state.scroll_offset
    end = min(start + visible_height, len(items))

    # Find max width across visible items (+ 2 for cursor prefix)
    max_width = max((items[i].width for i in range(start, end)), default=0) + 2

    # Paint into a temporary buffer
    buf = Buffer(max_width, visible_height)

    for row_idx, i in enumerate(range(start, end)):
        is_selected = i == state.selected
        prefix_char = cursor_char if is_selected else " "

        # Build a Line: cursor prefix + item spans
        prefix_span = Span(prefix_char + " ", selected_style if is_selected else Style())
        if is_selected:
            # Merge selected_style as base onto item spans
            row_line = Line(
                spans=(prefix_span,) + items[i].spans,
                style=selected_style,
            )
        else:
            row_line = Line(
                spans=(prefix_span,) + items[i].spans,
            )

        row_line = row_line.truncate(max_width)
        view = buf.region(0, row_idx, max_width, 1)
        row_line.paint(view, 0, 0)

        # Fill remainder with selected_style if selected
        filled = row_line.width
        if filled < max_width:
            fill_style = selected_style if is_selected else Style()
            buf.fill(filled, row_idx, max_width - filled, 1, " ", fill_style)

    # Extract rows from buffer into StyledBlock
    rows = []
    for y in range(visible_height):
        row = [buf.get(x, y) for x in range(max_width)]
        rows.append(row)

    return StyledBlock(rows, max_width)
