"""List view component: scrollable list with selection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style, Cell
from ..block import StyledBlock
from ..compose import join_vertical


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
    items: list[StyledBlock],
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

    rows: list[list[Cell]] = []
    for i in range(start, end):
        is_selected = i == state.selected
        prefix_char = cursor_char if is_selected else " "
        style = selected_style if is_selected else Style()

        # Build row: prefix + space content from block
        row: list[Cell] = [Cell(prefix_char, style), Cell(" ", style)]

        # Copy item cells, applying selected_style if selected
        item_row = items[i].row(0) if items[i].height > 0 else []
        for cell in item_row:
            if is_selected:
                row.append(Cell(cell.char, cell.style.merge(selected_style)))
            else:
                row.append(cell)

        # Pad to max_width
        while len(row) < max_width:
            row.append(Cell(" ", style))

        rows.append(row)

    # Pad remaining visible rows if fewer items than visible_height
    while len(rows) < visible_height:
        rows.append([Cell(" ", Style())] * max_width)

    return StyledBlock(rows, max_width)
