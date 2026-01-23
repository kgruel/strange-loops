"""Table component: scrollable table with headers and row selection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style, Cell
from ..block import StyledBlock
from ..compose import Align


@dataclass(frozen=True)
class Column:
    """Column definition for a table."""

    header: str
    width: int
    align: Align = Align.START


@dataclass(frozen=True)
class TableState:
    """Immutable table state tracking row selection and scroll position."""

    selected_row: int = 0
    scroll_offset: int = 0
    row_count: int = 0

    def move_up(self) -> TableState:
        """Move selection up, clamping to 0."""
        return replace(self, selected_row=max(0, self.selected_row - 1))

    def move_down(self) -> TableState:
        """Move selection down, clamping to last row."""
        return replace(self, selected_row=min(self.row_count - 1, self.selected_row + 1))

    def move_to(self, row: int) -> TableState:
        """Move selection to a specific row, clamped to valid range."""
        clamped = max(0, min(self.row_count - 1, row))
        return replace(self, selected_row=clamped)

    def scroll_into_view(self, visible_height: int) -> TableState:
        """Adjust scroll_offset so selected row is visible."""
        offset = self.scroll_offset
        if self.selected_row < offset:
            offset = self.selected_row
        elif self.selected_row >= offset + visible_height:
            offset = self.selected_row - visible_height + 1
        return replace(self, scroll_offset=offset)


def _align_cell(text: str, width: int, align: Align) -> str:
    """Align text within a fixed-width field, truncating if needed."""
    if len(text) > width:
        text = text[:width - 1] + "…" if width > 1 else text[:width]
    padding = width - len(text)
    if align == Align.START:
        return text + " " * padding
    elif align == Align.END:
        return " " * padding + text
    else:  # CENTER
        left = padding // 2
        right = padding - left
        return " " * left + text + " " * right


def table(
    state: TableState,
    columns: list[Column],
    rows: list[list[str]],
    visible_height: int,
    *,
    header_style: Style = Style(bold=True),
    selected_style: Style = Style(reverse=True),
    separator: str = "│",
) -> StyledBlock:
    """Render a table with headers, scrolling, and row selection."""
    if not columns:
        return StyledBlock.empty(1, visible_height + 2)

    # Calculate total width: sum of column widths + separators
    total_width = sum(c.width for c in columns) + len(separator) * (len(columns) - 1)

    all_rows: list[list[Cell]] = []

    # Header row
    header_cells: list[Cell] = []
    for i, col in enumerate(columns):
        aligned = _align_cell(col.header, col.width, col.align)
        header_cells.extend(Cell(ch, header_style) for ch in aligned)
        if i < len(columns) - 1:
            header_cells.extend(Cell(ch, header_style) for ch in separator)
    all_rows.append(header_cells)

    # Separator line
    sep_cells: list[Cell] = []
    for i, col in enumerate(columns):
        sep_cells.extend(Cell("─", Style()) for _ in range(col.width))
        if i < len(columns) - 1:
            sep_cells.extend(Cell("┼", Style()) for _ in range(len(separator)))
    all_rows.append(sep_cells)

    # Data rows (visible window)
    start = state.scroll_offset
    end = min(start + visible_height, len(rows))

    for row_idx in range(start, end):
        row_data = rows[row_idx] if row_idx < len(rows) else [""] * len(columns)
        is_selected = row_idx == state.selected_row
        row_style = selected_style if is_selected else Style()

        row_cells: list[Cell] = []
        for i, col in enumerate(columns):
            cell_text = row_data[i] if i < len(row_data) else ""
            aligned = _align_cell(cell_text, col.width, col.align)
            row_cells.extend(Cell(ch, row_style) for ch in aligned)
            if i < len(columns) - 1:
                row_cells.extend(Cell(ch, row_style) for ch in separator)
        all_rows.append(row_cells)

    # Pad remaining visible rows
    empty_count = visible_height - (end - start)
    for _ in range(empty_count):
        all_rows.append([Cell(" ", Style())] * total_width)

    return StyledBlock(all_rows, total_width)
