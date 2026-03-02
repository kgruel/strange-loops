#!/usr/bin/env python3
"""Viewport — learn scroll state by watching it change.

A split-pane Surface app:
- Left: scrollable list (list_view)
- Right: live scroll/viewport state inspector

Run: uv run python demos/apps/viewport.py
Keys: ↑/↓ navigate, q quit
"""

from __future__ import annotations

import asyncio

from painted import Line, Style
from painted.region import Region
from painted.tui import Surface
from painted.views import ListState, list_view


def _sample_rows() -> list[Line]:
    procs = [
        ("python3", "-m uvicorn api.server:app --port 8080"),
        ("node", "dev-server --watch src/"),
        ("rg", "--files | xargs -n1 stat"),
        ("bash", "-lc ./dev check"),
        ("postgres", "-D /usr/local/var/postgres"),
        ("redis-server", "127.0.0.1:6379"),
        ("python3", "-m pytest tests/golden -q"),
        ("python3", "-m painted.demo --interactive"),
        ("git", "status --porcelain=v1"),
        ("ssh", "prod-web-02 tail -f /var/log/nginx/access.log"),
    ]

    rows: list[Line] = []
    pid = 3100
    for i in range(24):
        exe, args = procs[i % len(procs)]
        rows.append(Line.plain(f"{pid + i:5d}  {exe:<12} {args}"))
    return rows


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "…"
    return text[: width - 1] + "…"


def _viewport_bar(offset: int, visible: int, total: int, width: int) -> str:
    """Return a compact map of the visible window within the full list."""
    if width <= 0:
        return ""
    if total <= 0:
        return "·" * width

    start = max(0, min(total, offset))
    end = max(start, min(total, offset + max(0, visible)))

    bar = ["·"] * width
    a = int((start / total) * width)
    b = int((end / total) * width)
    if end > start:
        if b == a:
            b = min(width, a + 1)
        for i in range(a, b):
            bar[i] = "█"
    return "".join(bar)


class ViewportInspectorApp(Surface):
    def __init__(self):
        super().__init__()
        self.items = _sample_rows()
        self.state = ListState().with_count(len(self.items))

        self.left: Region = Region(0, 0, 0, 0)
        self.right: Region = Region(0, 0, 0, 0)
        self.list_region: Region = Region(0, 0, 0, 0)
        self.sep_x = 0

    def layout(self, width: int, height: int) -> None:
        right_w = min(36, max(28, width // 3))
        left_w = max(12, width - right_w - 1)
        right_w = max(0, width - left_w - 1)

        self.sep_x = left_w
        self.left = Region(0, 0, left_w, height)
        self.right = Region(left_w + 1, 0, right_w, height)

        header_h = 1
        footer_h = 1
        list_h = max(1, height - header_h - footer_h)
        self.list_region = Region(0, header_h, left_w, list_h)

        self.state = self.state.scroll_into_view(self.list_region.height)

    def on_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        if key == "up":
            self.state = self.state.move_up().scroll_into_view(self.list_region.height)
            self.mark_dirty()
        elif key == "down":
            self.state = self.state.move_down().scroll_into_view(self.list_region.height)
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        buf = self._buf
        buf.fill(0, 0, buf.width, buf.height, " ", Style())

        # Pane separator.
        if 0 <= self.sep_x < buf.width:
            for y in range(buf.height):
                buf.put_text(self.sep_x, y, "│", Style(dim=True))

        left_view = self.left.view(buf)
        right_view = self.right.view(buf)

        # Left header/footer.
        if left_view.width > 0:
            left_view.put_text(
                0,
                0,
                _truncate(" Scroll list (↑/↓) ", left_view.width),
                Style(fg="white", bold=True),
            )
            left_view.put_text(
                0,
                left_view.height - 1,
                _truncate(" q quit ", left_view.width),
                Style(dim=True),
            )

        # Scrollable list (between header/footer).
        list_viewport = self.list_region.view(buf)
        list_viewport.fill(0, 0, list_viewport.width, list_viewport.height, " ", Style())
        effective = self.state.scroll_into_view(self.list_region.height)
        block = list_view(effective, self.items, visible_height=self.list_region.height)
        block.paint(list_viewport, 0, 0)

        # Inspector.
        self._render_inspector(right_view, effective)

    def _render_inspector(self, view, state: ListState) -> None:
        view.fill(0, 0, view.width, view.height, " ", Style())
        if view.width <= 0 or view.height <= 0:
            return

        total = len(self.items)
        selected = state.selected
        offset = state.scroll_offset
        visible = state.viewport.visible
        end = min(total, offset + max(0, visible))

        y = 0
        view.put_text(0, y, _truncate(" Viewport inspector ", view.width), Style(fg="cyan", bold=True))
        y += 2

        lines = [
            f"offset        {offset}",
            f"selected      {selected}",
            f"visible_count {visible}",
            f"total_items   {total}",
            f"window        [{offset}..{max(offset, end)})",
        ]
        for line in lines:
            if y >= view.height:
                return
            view.put_text(0, y, _truncate(line, view.width), Style())
            y += 1

        y += 1
        if y < view.height:
            bar_w = max(0, view.width - len("map ") - 2)
            bar = _viewport_bar(offset, visible, total, bar_w)
            view.put_text(0, y, _truncate(f"map [{bar}]", view.width), Style(dim=True))
            y += 2

        if 0 <= selected < total and y < view.height:
            sample = self.items[selected].spans[0].text
            view.put_text(0, y, _truncate("selected_row:", view.width), Style(dim=True))
            y += 1
            if y < view.height:
                view.put_text(0, y, _truncate(sample, view.width), Style())
                y += 2

        if y < view.height:
            view.put_text(0, view.height - 1, _truncate(" ↑/↓ move  q quit ", view.width), Style(dim=True))


async def main() -> None:
    await ViewportInspectorApp().run()


if __name__ == "__main__":
    asyncio.run(main())
