"""Text input component: single-line editable field."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style, Cell
from ..block import StyledBlock


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
        offset = self.scroll_offset
        if self.cursor < offset:
            offset = self.cursor
        elif self.cursor >= offset + width:
            offset = self.cursor - width + 1
        # Clamp offset to valid range
        offset = max(0, offset)
        return replace(self, scroll_offset=offset)


def text_input(
    state: TextInputState,
    width: int,
    *,
    focused: bool = True,
    style: Style = Style(),
    cursor_style: Style = Style(reverse=True),
    placeholder: str = "",
) -> StyledBlock:
    """Render a single-line text input field."""
    # Ensure cursor is visible
    state = state._ensure_visible(width)

    if not state.text and not focused and placeholder:
        # Show placeholder
        display = placeholder[:width]
        placeholder_style = Style(dim=True)
        cells = [Cell(ch, placeholder_style) for ch in display]
        while len(cells) < width:
            cells.append(Cell(" ", style))
        return StyledBlock([cells], width)

    # Extract visible portion of text
    visible_text = state.text[state.scroll_offset:state.scroll_offset + width]

    cells: list[Cell] = []
    for i, ch in enumerate(visible_text):
        actual_pos = state.scroll_offset + i
        if focused and actual_pos == state.cursor:
            cells.append(Cell(ch, cursor_style))
        else:
            cells.append(Cell(ch, style))

    # If cursor is at end of visible text, render cursor as space
    cursor_vis_pos = state.cursor - state.scroll_offset
    if focused and 0 <= cursor_vis_pos < width and cursor_vis_pos == len(visible_text):
        cells.append(Cell(" ", cursor_style))

    # Pad to width
    while len(cells) < width:
        cells.append(Cell(" ", style))

    return StyledBlock([cells[:width]], width)
