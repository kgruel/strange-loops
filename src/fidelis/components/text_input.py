"""Text input component: single-line editable field."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style, Cell
from ..block import Block
from .._text_width import char_width, display_width, index_for_col, take_prefix


@dataclass(frozen=True)
class TextInputState:
    """Immutable text input state with cursor and scroll tracking."""

    text: str = ""
    cursor: int = 0
    scroll_offset: int = 0

    def insert(self, ch: str) -> TextInputState:
        """Insert character(s) at cursor position."""
        new_text = self.text[:self.cursor] + ch + self.text[self.cursor:]
        return replace(self, text=new_text, cursor=self.cursor + len(ch))

    def delete_back(self) -> TextInputState:
        """Delete character before cursor (backspace)."""
        if self.cursor == 0:
            return self
        new_text = self.text[:self.cursor - 1] + self.text[self.cursor:]
        return replace(self, text=new_text, cursor=self.cursor - 1)

    def delete_forward(self) -> TextInputState:
        """Delete character at cursor (delete key)."""
        if self.cursor >= len(self.text):
            return self
        new_text = self.text[:self.cursor] + self.text[self.cursor + 1:]
        return replace(self, text=new_text)

    def move_left(self) -> TextInputState:
        """Move cursor left."""
        if self.cursor == 0:
            return self
        return replace(self, cursor=self.cursor - 1)

    def move_right(self) -> TextInputState:
        """Move cursor right."""
        if self.cursor >= len(self.text):
            return self
        return replace(self, cursor=self.cursor + 1)

    def move_home(self) -> TextInputState:
        """Move cursor to start."""
        return replace(self, cursor=0)

    def move_end(self) -> TextInputState:
        """Move cursor to end."""
        return replace(self, cursor=len(self.text))

    def set_text(self, text: str) -> TextInputState:
        """Replace text and move cursor to end."""
        return replace(self, text=text, cursor=len(text))

    def _ensure_visible(self, width: int) -> TextInputState:
        """Adjust scroll_offset so cursor is visible within width."""
        if width <= 0:
            return replace(self, scroll_offset=0)

        text = self.text
        cursor_idx = max(0, min(self.cursor, len(text)))
        offset_idx = max(0, min(self.scroll_offset, len(text)))

        cursor_col = display_width(text[:cursor_idx])
        offset_col = display_width(text[:offset_idx])

        if cursor_col < offset_col:
            desired_offset_col = cursor_col
        elif cursor_col >= offset_col + width:
            desired_offset_col = max(0, cursor_col - width + 1)
        else:
            desired_offset_col = offset_col

        new_offset_idx = index_for_col(text, desired_offset_col)
        new_offset_idx = max(0, min(new_offset_idx, len(text)))
        return replace(self, cursor=cursor_idx, scroll_offset=new_offset_idx)


def text_input(
    state: TextInputState,
    width: int,
    *,
    focused: bool = True,
    style: Style = Style(),
    cursor_style: Style = Style(reverse=True),
    placeholder: str = "",
) -> Block:
    """Render a single-line text input field."""
    # Ensure cursor is visible
    state = state._ensure_visible(width)

    if not state.text and not focused and placeholder:
        # Show placeholder
        display, _ = take_prefix(placeholder, width)
        placeholder_style = Style(dim=True)
        cells: list[Cell] = []
        used = 0
        for ch in display:
            w = char_width(ch)
            if w == 0:
                continue
            if used + w > width:
                break
            cells.append(Cell(ch, placeholder_style))
            if w == 2 and used + 2 <= width:
                cells.append(Cell(" ", placeholder_style))
            used += w
        while len(cells) < width:
            cells.append(Cell(" ", style))
        return Block([cells], width)

    # Extract visible portion of text
    tail = state.text[state.scroll_offset:]
    visible_text, _ = take_prefix(tail, width)

    cells: list[Cell] = []
    used_cols = 0
    for i, ch in enumerate(visible_text):
        actual_pos = state.scroll_offset + i
        w = char_width(ch)
        if w == 0:
            continue
        if used_cols + w > width:
            break
        st = cursor_style if (focused and actual_pos == state.cursor) else style
        cells.append(Cell(ch, st))
        if w == 2 and used_cols + 2 <= width:
            cells.append(Cell(" ", st))
        used_cols += w

    # Cursor at end of visible text: render cursor as a space cell
    if focused:
        cursor_col = display_width(state.text[:state.cursor])
        offset_col = display_width(state.text[:state.scroll_offset])
        cursor_vis_col = cursor_col - offset_col
        if 0 <= cursor_vis_col < width and cursor_vis_col == used_cols:
            cells.append(Cell(" ", cursor_style))

    # Pad to width
    while len(cells) < width:
        cells.append(Cell(" ", style))

    return Block([cells[:width]], width)
