"""Table component: scrollable table with headers and row selection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..buffer import Buffer
from ..cell import Style
from ..block import Block
from ..compose import Align
from ..span import Line, Span


@dataclass(frozen=True)
class Column:
    """Column definition for a table."""

    header: Line
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


def _pad_line(line: Line, target_width: int, align: Align, style: Style) -> Line:
    """Truncate or pad a Line to exactly target_width columns."""
    current = line.width
    if current > target_width:
        return line.truncate(target_width)
    if current == target_width:
        return line
    padding = target_width - current
    if align == Align.START:
        return Line(spans=line.spans + (Span(" " * padding, style),), style=line.style)
    elif align == Align.END:
        return Line(spans=(Span(" " * padding, style),) + line.spans, style=line.style)
    else:  # CENTER
        left = padding // 2
        right = padding - left
        return Line(
            spans=(Span(" " * left, style),) + line.spans + (Span(" " * right, style),),
            style=line.style,
        )


def table(
    state: TableState,
    columns: list[Column],
    rows: list[list[Line]],
    visible_height: int,
    *,
    header_style: Style = Style(bold=True),
    selected_style: Style = Style(reverse=True),
    separator: str = "│",
) -> Block:
    """Render a table with headers, scrolling, and row selection."""
    if not columns:
        return Block.empty(1, visible_height + 2)

    # Calculate total width: sum of column widths + separators
    sep_width = len(separator)
    total_width = sum(c.width for c in columns) + sep_width * (len(columns) - 1)

    # Total rows: header + separator + visible data
    total_rows = 2 + visible_height
    buf = Buffer(total_width, total_rows)

    # -- Header row --
    col_x = 0
    for i, col in enumerate(columns):
        header_line = _pad_line(col.header, col.width, col.align, header_style)
        header_line = Line(spans=header_line.spans, style=header_style)
        view = buf.region(col_x, 0, col.width, 1)
        header_line.paint(view, 0, 0)
        col_x += col.width
        if i < len(columns) - 1:
            buf.put_text(col_x, 0, separator, header_style)
            col_x += sep_width

    # -- Separator line --
    col_x = 0
    for i, col in enumerate(columns):
        buf.put_text(col_x, 1, "─" * col.width, Style())
        col_x += col.width
        if i < len(columns) - 1:
            buf.put_text(col_x, 1, "┼" * sep_width, Style())
            col_x += sep_width

    # -- Data rows (visible window) --
    start = state.scroll_offset
    end = min(start + visible_height, len(rows))

    for row_offset, row_idx in enumerate(range(start, end)):
        row_data = rows[row_idx] if row_idx < len(rows) else []
        is_selected = row_idx == state.selected_row
        row_style = selected_style if is_selected else Style()
        buf_y = 2 + row_offset

        col_x = 0
        for i, col in enumerate(columns):
            cell_line = row_data[i] if i < len(row_data) else Line.plain("")
            padded = _pad_line(cell_line, col.width, col.align, row_style)
            padded = Line(spans=padded.spans, style=row_style)
            view = buf.region(col_x, buf_y, col.width, 1)
            padded.paint(view, 0, 0)
            col_x += col.width
            if i < len(columns) - 1:
                buf.put_text(col_x, buf_y, separator, row_style)
                col_x += sep_width

    # Extract rows from buffer into Block
    block_rows = []
    actual_height = 2 + (end - start) + max(0, visible_height - (end - start))
    for y in range(actual_height):
        row = [buf.get(x, y) for x in range(total_width)]
        block_rows.append(row)

    return Block(block_rows, total_width)
