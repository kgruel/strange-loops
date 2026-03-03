#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Focus Form — focus navigation + text input.

Teaches:
- Focus.id + Focus.captured (navigation vs widget-owned input)
- TextInputState + text_input (state + render pattern)
- Composing multiple stateful widgets in one Surface app

Run: uv run python demos/apps/focus_form.py
Keys:
  Tab / Shift-Tab  move focus
  Enter            capture/release (or submit on button)
  Esc              release capture
  q                quit (only when not captured)
"""

from __future__ import annotations

import asyncio

from painted import Block, DOUBLE, LIGHT, ROUNDED, Style, border
from painted.tui import Focus, Region, Surface, ring_next, ring_prev
from painted.views import TextInputState, text_input


_FOCUS_IDS: tuple[str, ...] = ("hostname", "port", "username", "submit")
_FIELD_IDS: tuple[str, ...] = ("hostname", "port", "username")


def _is_text_edit_key(key: str) -> bool:
    if key in {"left", "right", "home", "end", "backspace", "delete"}:
        return True
    return len(key) == 1 and key.isprintable()


def _apply_text_key(state: TextInputState, key: str) -> tuple[TextInputState, bool]:
    if key == "left":
        return state.move_left(), True
    if key == "right":
        return state.move_right(), True
    if key == "home":
        return state.move_home(), True
    if key == "end":
        return state.move_end(), True
    if key == "backspace":
        return state.delete_back(), True
    if key == "delete":
        return state.delete_forward(), True
    if len(key) == 1 and key.isprintable():
        return state.insert(key), True
    return state, False


class FocusFormApp(Surface):
    def __init__(self) -> None:
        super().__init__()
        self.focus = Focus(id="hostname")

        self.hostname = TextInputState()
        self.port = TextInputState()
        self.username = TextInputState()

        self.last_submit: str = ""
        self._inner: Region = Region(1, 1, 0, 0)

    def layout(self, width: int, height: int) -> None:
        self._inner = Region(1, 1, max(0, width - 2), max(0, height - 2))

    def render(self) -> None:
        buf = self._buf
        buf.fill(0, 0, buf.width, buf.height, " ", Style())

        content_w = max(0, buf.width - 2)
        content_h = max(0, buf.height - 2)

        mode = "CAP" if self.focus.captured else "NAV"
        title = f"Focus Form  focus={self.focus.id}:{mode}"
        border(Block.empty(content_w, content_h), chars=LIGHT, title=title).paint(buf, 0, 0)

        view = self._inner.view(buf)
        view.fill(0, 0, view.width, view.height, " ", Style())

        status = f"Tab/Shift-Tab move • Enter edit/submit • Esc done • q quit (NAV only)"
        view.put_text(0, 0, status[: view.width], Style(dim=True))
        view.put_text(
            0, 1, f"Focus.id={self.focus.id}  Focus.captured={self.focus.captured}", Style(dim=True)
        )

        y = 3
        for field_id, label in (
            ("hostname", "Hostname"),
            ("port", "Port"),
            ("username", "Username"),
        ):
            self._field_block(field_id, label, view.width).paint(view, 0, y)
            y += 3

        self._submit_block(view.width).paint(view, 0, y)
        y += 3  # submit block height

        footer = self.last_submit or "Submit collects current values and shows them here."
        view.put_text(0, y, footer[: view.width], Style(dim=True))

    def _field_block(self, field_id: str, label: str, width: int) -> Block:
        is_focused = self.focus.id == field_id
        mode = "CAP" if (is_focused and self.focus.captured) else "NAV" if is_focused else ""
        marker = ">" if is_focused else " "
        title = f"{marker} {label}" + (f"  {mode}" if mode else "")

        chars = LIGHT
        if is_focused and self.focus.captured:
            chars = DOUBLE
        elif is_focused:
            chars = ROUNDED

        inner_w = max(0, width - 2)
        state = getattr(self, field_id)
        inp = text_input(
            state,
            width=inner_w,
            focused=is_focused and self.focus.captured,
            style=Style(),
            cursor_style=Style(reverse=True),
        )
        return border(inp, chars=chars, title=title)

    def _submit_block(self, width: int) -> Block:
        is_focused = self.focus.id == "submit"
        marker = ">" if is_focused else " "
        title = f"{marker} Submit"
        chars = ROUNDED if is_focused else LIGHT

        inner_w = max(0, width - 2)
        label = "[ Submit ]"
        pad_left = max(0, (inner_w - len(label)) // 2)
        content = Block.text((" " * pad_left) + label, Style(bold=True), width=inner_w)
        return border(content, chars=chars, title=title)

    def _submit(self) -> None:
        self.last_submit = (
            f"Submitted: hostname={self.hostname.text or '∅'}  "
            f"port={self.port.text or '∅'}  "
            f"username={self.username.text or '∅'}"
        )

    def on_key(self, key: str) -> None:
        if key in {"tab", "shift_tab"}:
            before = self.focus.id
            after = ring_next(_FOCUS_IDS, before) if key == "tab" else ring_prev(_FOCUS_IDS, before)
            self.focus = self.focus.focus(after)
            return

        if key == "q" and not self.focus.captured:
            self.quit()
            return

        if self.focus.id == "submit":
            if key == "enter":
                self._submit()
            return

        # Text fields
        field_id = self.focus.id
        if field_id not in _FIELD_IDS:
            return

        state: TextInputState = getattr(self, field_id)

        if self.focus.captured:
            if key == "escape":
                self.focus = self.focus.release()
                return
            if key == "enter":
                if field_id == "username":
                    self._submit()
                self.focus = self.focus.release()
                return

            new_state, handled = _apply_text_key(state, key)
            if handled:
                setattr(self, field_id, new_state)
            return

        # Navigation mode while on a text field
        if key == "enter":
            self.focus = self.focus.capture()
            return

        if _is_text_edit_key(key):
            self.focus = self.focus.capture()
            new_state, handled = _apply_text_key(state, key)
            if handled:
                setattr(self, field_id, new_state)


async def main() -> None:
    await FocusFormApp().run()


if __name__ == "__main__":
    asyncio.run(main())
