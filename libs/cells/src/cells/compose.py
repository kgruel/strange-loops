"""Composition functions for Block: join, pad, border, truncate, vslice."""

from __future__ import annotations

from enum import Enum

from .block import Block
from .cell import Style, Cell
from .borders import BorderChars, ROUNDED


class Align(Enum):
    START = "start"    # top or left
    CENTER = "center"
    END = "end"        # bottom or right


def join_horizontal(*blocks: Block, gap: int = 0,
                    align: Align = Align.START) -> Block:
    """Join blocks left-to-right with optional gap and vertical alignment."""
    if not blocks:
        return Block.empty(0, 0)

    max_height = max(b.height for b in blocks)
    total_width = sum(b.width for b in blocks) + gap * (len(blocks) - 1)

    rows: list[list[Cell]] = [[] for _ in range(max_height)]
    gap_cell = Cell(" ", Style())

    for i, block in enumerate(blocks):
        # Calculate vertical offset for alignment
        offset = _valign_offset(block.height, max_height, align)

        for row_idx in range(max_height):
            src_row = row_idx - offset
            if 0 <= src_row < block.height:
                rows[row_idx].extend(block.row(src_row))
            else:
                rows[row_idx].extend([gap_cell] * block.width)

            # Add gap cells between blocks (not after the last)
            if i < len(blocks) - 1 and gap > 0:
                rows[row_idx].extend([gap_cell] * gap)

    return Block(rows, total_width)


def join_vertical(*blocks: Block,
                  align: Align = Align.START) -> Block:
    """Join blocks top-to-bottom with horizontal alignment."""
    if not blocks:
        return Block.empty(0, 0)

    max_width = max(b.width for b in blocks)
    pad_cell = Cell(" ", Style())

    rows: list[list[Cell]] = []

    for block in blocks:
        offset = _halign_offset(block.width, max_width, align)

        for row_idx in range(block.height):
            row: list[Cell] = []
            # Left padding
            if offset > 0:
                row.extend([pad_cell] * offset)
            # Block content
            row.extend(block.row(row_idx))
            # Right padding
            right_pad = max_width - offset - block.width
            if right_pad > 0:
                row.extend([pad_cell] * right_pad)
            rows.append(row)

    return Block(rows, max_width)


def pad(block: Block, *, left: int = 0, right: int = 0,
        top: int = 0, bottom: int = 0, style: Style = Style()) -> Block:
    """Add empty cell padding around a block."""
    new_width = block.width + left + right
    new_height = block.height + top + bottom
    space = Cell(" ", style)

    rows: list[list[Cell]] = []

    # Top padding
    for _ in range(top):
        rows.append([space] * new_width)

    # Content rows with left/right padding
    for row_idx in range(block.height):
        row: list[Cell] = []
        if left > 0:
            row.extend([space] * left)
        row.extend(block.row(row_idx))
        if right > 0:
            row.extend([space] * right)
        rows.append(row)

    # Bottom padding
    for _ in range(bottom):
        rows.append([space] * new_width)

    return Block(rows, new_width)


def border(block: Block, chars: BorderChars = ROUNDED,
           style: Style = Style(), title: str | None = None,
           title_style: Style | None = None) -> Block:
    """Wrap a block with a 1-cell border, optionally with a title in the top row."""
    new_width = block.width + 2
    rows: list[list[Cell]] = []

    # Top border
    top_row = ([Cell(chars.top_left, style)]
               + [Cell(chars.horizontal, style)] * block.width
               + [Cell(chars.top_right, style)])

    # Paint title into top row if provided
    if title and block.width >= len(title) + 2:
        ts = title_style if title_style is not None else style
        pos = 2  # start after top_left + 1 padding cell
        # Space before title
        top_row[pos] = Cell(" ", ts)
        pos += 1
        for ch in title:
            top_row[pos] = Cell(ch, ts)
            pos += 1
        # Space after title
        top_row[pos] = Cell(" ", ts)

    rows.append(top_row)

    # Content rows with vertical borders
    for row_idx in range(block.height):
        row = ([Cell(chars.vertical, style)]
               + list(block.row(row_idx))
               + [Cell(chars.vertical, style)])
        rows.append(row)

    # Bottom border
    bottom_row = ([Cell(chars.bottom_left, style)]
                  + [Cell(chars.horizontal, style)] * block.width
                  + [Cell(chars.bottom_right, style)])
    rows.append(bottom_row)

    return Block(rows, new_width)


def truncate(block: Block, width: int, ellipsis: str = "…") -> Block:
    """Truncate a block to width, appending ellipsis if truncated."""
    if block.width <= width:
        return block

    rows: list[list[Cell]] = []
    for row_idx in range(block.height):
        src_row = block.row(row_idx)
        if width <= 0:
            rows.append([])
        elif width == 1:
            # Only room for ellipsis
            rows.append([Cell(ellipsis, src_row[0].style)])
        else:
            new_row = list(src_row[:width - 1])
            new_row.append(Cell(ellipsis, src_row[width - 1].style))
            rows.append(new_row)

    return Block(rows, width)


def vslice(block: Block, offset: int, height: int) -> Block:
    """Extract a vertical slice of rows [offset, offset+height) from a block.

    Clamps offset to [0, block.height]. If offset+height exceeds block height,
    returns fewer rows (no padding). If offset >= block height, returns an
    empty block preserving the original width.
    """
    offset = max(0, min(offset, block.height))
    end = min(offset + height, block.height)

    if offset >= end:
        return Block.empty(block.width, 0)

    rows = [list(block.row(r)) for r in range(offset, end)]
    return Block(rows, block.width)


def _valign_offset(block_height: int, container_height: int, align: Align) -> int:
    """Calculate vertical offset for alignment within a container."""
    diff = container_height - block_height
    if align == Align.START:
        return 0
    elif align == Align.CENTER:
        return diff // 2
    else:  # END
        return diff


def _halign_offset(block_width: int, container_width: int, align: Align) -> int:
    """Calculate horizontal offset for alignment within a container."""
    diff = container_width - block_width
    if align == Align.START:
        return 0
    elif align == Align.CENTER:
        return diff // 2
    else:  # END
        return diff
