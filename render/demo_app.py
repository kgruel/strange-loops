"""Demo app: interactive list + text input + spinner with focus management."""

from __future__ import annotations

import asyncio
import time

from .app import RenderApp
from .block import StyledBlock
from .cell import Style
from .compose import border, join_horizontal, join_vertical, pad
from .components import (
    ListState,
    SpinnerState,
    TextInputState,
    list_view,
    spinner,
    text_input,
)
from .focus import FocusRing
from .region import Region


LIST_ITEMS = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta"]


class DemoApp(RenderApp):
    """Minimal app demonstrating the full render loop."""

    def __init__(self):
        super().__init__(fps_cap=30)
        self._focus = FocusRing(items=["list", "input"])
        self._list_state = ListState(item_count=len(LIST_ITEMS))
        self._input_state = TextInputState()
        self._spinner_state = SpinnerState()
        self._last_tick = time.monotonic()
        self._region_main = Region(0, 0, 80, 24)

    def layout(self, width: int, height: int) -> None:
        self._region_main = Region(0, 0, width, height)

    def update(self) -> None:
        now = time.monotonic()
        if now - self._last_tick >= 0.1:
            self._spinner_state = self._spinner_state.tick()
            self._last_tick = now
            self.mark_dirty()

    def render(self) -> None:
        # Build list block
        items = [
            StyledBlock.text(item, Style()) for item in LIST_ITEMS
        ]
        list_height = min(len(LIST_ITEMS), self._region_main.height - 6)
        self._list_state = self._list_state.scroll_into_view(list_height)
        list_block = list_view(self._list_state, items, list_height)
        list_bordered = border(list_block, style=Style(
            bold=(self._focus.focused == "list"),
        ))

        # Build text input block
        input_width = max(20, self._region_main.width - 6)
        input_block = text_input(
            self._input_state,
            input_width,
            focused=(self._focus.focused == "input"),
            placeholder="Type here...",
        )
        input_bordered = border(input_block, style=Style(
            bold=(self._focus.focused == "input"),
        ))

        # Build spinner + status
        spin_block = spinner(self._spinner_state, style=Style(fg="cyan"))
        status_text = f" Focus: {self._focus.focused} | q=quit Tab=switch"
        status_block = StyledBlock.text(status_text, Style(dim=True))
        header = join_horizontal(spin_block, status_block, gap=1)

        # Compose layout vertically
        composed = join_vertical(
            pad(header, top=0, bottom=1),
            list_bordered,
            pad(input_bordered, top=1),
        )

        # Paint into buffer
        if self._buf is not None:
            # Clear buffer
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            view = self._region_main.view(self._buf)
            composed.paint(view, x=1, y=0)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        if key == "\t":
            self._focus.next()
            return

        # Dispatch to focused component
        focused = self._focus.focused
        if focused == "list":
            self._handle_list_key(key)
        elif focused == "input":
            self._handle_input_key(key)

    def _handle_list_key(self, key: str) -> None:
        # Arrow keys come as escape sequences
        if key == "\x1b":
            # Read the rest of the escape sequence
            k2 = self._keyboard.get_key()
            if k2 == "[":
                k3 = self._keyboard.get_key()
                if k3 == "A":  # Up
                    self._list_state = self._list_state.move_up()
                elif k3 == "B":  # Down
                    self._list_state = self._list_state.move_down()

    def _handle_input_key(self, key: str) -> None:
        if key == "\x1b":
            k2 = self._keyboard.get_key()
            if k2 == "[":
                k3 = self._keyboard.get_key()
                if k3 == "D":  # Left
                    self._input_state = self._input_state.move_left()
                elif k3 == "C":  # Right
                    self._input_state = self._input_state.move_right()
        elif key == "\x7f":  # Backspace
            self._input_state = self._input_state.delete_back()
        elif key.isprintable() and len(key) == 1:
            self._input_state = self._input_state.insert(key)


async def main():
    app = DemoApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
