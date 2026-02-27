"""Table component: scrollable table with headers and row selection."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..block import Block
from ..buffer import Buffer
from ..cell import Style
from ..compose import Align
from ..cursor import Cursor
from ..span import Line, Span
from ..viewport import Viewport


@dataclass(frozen=True)
class Column:
    """Column definition for a table."""

    header: Line
    width: int
    align: Align = Align.START


@dataclass(frozen=True)
class TableState:
    """Immutable table state tracking row selection and scroll position.

    Composition:
    - `cursor`: selected row index over `row_count`
    - `viewport`: scroll offset/visible/content for rendering
    """

    cursor: Cursor = Cursor()
    viewport: Viewport = Viewport()

    @property
    def selected_row(self) -> int:
        return self.cursor.index

    @property
    def row_count(self) -> int:
        return self.cursor.count

    @property
    def scroll_offset(self) -> int:
        return self.viewport.offset

    def move_up(self) -> TableState:
        """Move selection up, clamping to 0."""
        return replace(self, cursor=self.cursor.prev())

    def move_down(self) -> TableState:
        """Move selection down, clamping to last row."""
        return replace(self, cursor=self.cursor.next())

    def move_to(self, row: int) -> TableState:
        """Move selection to a specific row, clamped to valid range."""
        return replace(self, cursor=self.cursor.move_to(row))

    def with_count(self, count: int) -> TableState:
        """Update row_count, clamping selection + scroll offset."""
        cursor = self.cursor.with_count(count)
        viewport = self.viewport.with_content(cursor.count)
        return replace(self, cursor=cursor, viewport=viewport)

    def with_visible(self, height: int) -> TableState:
        """Update viewport visible height."""
        return replace(self, viewport=self.viewport.with_visible(height))

    def scroll_into_view(self, visible_height: int) -> TableState:
        """Adjust viewport so selected row is visible."""
        vp = self.viewport.with_visible(visible_height).with_content(self.cursor.count)
        vp = vp.scroll_into_view(self.cursor.index)
        return replace(self, viewport=vp)


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

    vp = state.viewport.with_visible(visible_height).with_content(len(rows))
    cursor = state.cursor.with_count(len(rows))

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
    start = vp.offset
    end = min(start + visible_height, len(rows))

    for row_offset, row_idx in enumerate(range(start, end)):
        row_data = rows[row_idx] if row_idx < len(rows) else []
        is_selected = row_idx == cursor.index
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
