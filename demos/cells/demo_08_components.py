#!/usr/bin/env python3
"""Demo 08: Components — interactive UI widgets.

Built-in components with state management:
- spinner: animated loading indicator
- progress_bar: percentage bar
- list_view: scrollable selection list
- text_input: editable text field

Run: uv run python demos/demo_08_components.py
Tab to switch focus, arrow keys to interact, type in text field, 'q' to quit.
"""

import asyncio
from cells import (
    Surface, Style, Line, Span,
    border,
    SpinnerState, spinner,
    ProgressState, progress_bar,
    ListState, list_view,
    TextInputState, text_input,
    FocusRing,
)


class Demo08App(Surface):
    def __init__(self):
        super().__init__()

        # Component states
        self.spinner_state = SpinnerState()
        self.progress_state = ProgressState(value=0.35)

        # List items as Lines
        self.list_items = [
            Line.plain("Apple", Style(fg="red")),
            Line.plain("Banana", Style(fg="yellow")),
            Line.plain("Cherry", Style(fg="magenta")),
            Line.plain("Date", Style(fg="green")),
            Line.plain("Elderberry", Style(fg="cyan")),
        ]
        self.list_state = ListState(selected=0, item_count=len(self.list_items))

        self.text_state = TextInputState(text="Edit me", cursor=7)

        # Focus management
        self.focus = FocusRing(["progress", "list", "text"])
        self.frame = 0

    def update(self) -> None:
        """Advance animations."""
        self.frame += 1

        # Update spinner every few frames
        if self.frame % 6 == 0:
            self.spinner_state = self.spinner_state.tick()
            self.mark_dirty()

    def render(self) -> None:
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        y = 1

        # Title
        self._buf.put_text(2, y, "Component Demo", Style(fg="white", bold=True))
        y += 2

        # Spinner (always animating)
        self._buf.put_text(2, y, "Spinner: ", Style(dim=True))
        spin_block = spinner(self.spinner_state, style=Style(fg="cyan"))
        spin_block.paint(self._buf, 11, y)
        self._buf.put_text(14, y, "Loading...", Style(fg="cyan"))
        y += 2

        # Progress bar
        focused = self.focus.focused == "progress"
        label = "Progress:" if not focused else "Progress: [←/→]"
        self._buf.put_text(2, y, label, Style(fg="yellow" if focused else None))
        bar = progress_bar(
            self.progress_state,
            width=30,
            filled_style=Style(fg="green"),
            empty_style=Style(dim=True),
        )
        bar.paint(self._buf, 2, y + 1)
        pct = int(self.progress_state.value * 100)
        self._buf.put_text(34, y + 1, f"{pct}%", Style())
        y += 3

        # List view
        focused = self.focus.focused == "list"
        label = "List:" if not focused else "List: [↑/↓]"
        self._buf.put_text(2, y, label, Style(fg="yellow" if focused else None))

        # Scroll into view before rendering
        visible_height = 3
        scrolled_state = self.list_state.scroll_into_view(visible_height)
        lst = list_view(
            scrolled_state,
            items=self.list_items,
            visible_height=visible_height,
            selected_style=Style(fg="black", bg="cyan", bold=True),
        )
        lst_bordered = border(lst, style=Style(fg="cyan" if focused else None, dim=not focused))
        lst_bordered.paint(self._buf, 2, y + 1)
        y += 6

        # Text input
        focused = self.focus.focused == "text"
        label = "Input:" if not focused else "Input: [type]"
        self._buf.put_text(2, y, label, Style(fg="yellow" if focused else None))
        txt = text_input(
            self.text_state,
            width=25,
            focused=focused,
            style=Style(fg="white"),
            cursor_style=Style(reverse=True),
        )
        txt_bordered = border(txt, style=Style(fg="cyan" if focused else None, dim=not focused))
        txt_bordered.paint(self._buf, 2, y + 1)
        y += 4

        # Instructions
        self._buf.put_text(2, self._buf.height - 1,
                          "Tab: focus | Arrows/Type: interact | q: quit",
                          Style(dim=True))

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
        elif key == "tab":
            self.focus.next()
        elif self.focus.focused == "progress":
            if key == "right":
                self.progress_state = self.progress_state.set(
                    self.progress_state.value + 0.05
                )
            elif key == "left":
                self.progress_state = self.progress_state.set(
                    self.progress_state.value - 0.05
                )
        elif self.focus.focused == "list":
            if key == "up":
                self.list_state = self.list_state.move_up()
            elif key == "down":
                self.list_state = self.list_state.move_down()
        elif self.focus.focused == "text":
            if key == "right":
                self.text_state = self.text_state.move_right()
            elif key == "left":
                self.text_state = self.text_state.move_left()
            elif key == "backspace":
                self.text_state = self.text_state.delete_back()
            elif key == "delete":
                self.text_state = self.text_state.delete_forward()
            elif len(key) == 1 and key.isprintable():
                self.text_state = self.text_state.insert(key)


if __name__ == "__main__":
    asyncio.run(Demo08App().run())
