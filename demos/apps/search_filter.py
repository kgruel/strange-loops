#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""Search Filter — interactive fuzzy search over a list.

Teaches:
- Search state (query, selection, filter functions)
- TextInputState for the search box
- ListState filtered by Search.query
- Live filtering: type to narrow, up/down to select, enter to pick

Keys:
  type       filter the list
  backspace  remove character
  ↑/↓        move selection in filtered results
  enter      pick selected item
  escape     clear query
  q          quit (when query is empty)

Run: uv run python demos/apps/search_filter.py
"""

from __future__ import annotations

import asyncio

from painted import Style
from painted.buffer import BufferView
from painted.region import Region
from painted.tui import Search, Surface, filter_contains, filter_fuzzy, filter_prefix
from painted.views import TextInputState, text_input


SAMPLE_ITEMS: tuple[str, ...] = (
    "deploy-production",
    "deploy-staging",
    "deploy-canary",
    "rollback-production",
    "rollback-staging",
    "scale-up",
    "scale-down",
    "restart-workers",
    "restart-api",
    "restart-scheduler",
    "run-migrations",
    "run-tests",
    "run-benchmarks",
    "check-health",
    "check-logs",
    "check-metrics",
    "backup-database",
    "backup-config",
    "rotate-secrets",
    "flush-cache",
)

FILTER_MODES: tuple[str, ...] = ("fuzzy", "contains", "prefix")
FILTER_FNS = {
    "fuzzy": filter_fuzzy,
    "contains": filter_contains,
    "prefix": filter_prefix,
}


def _put(view: BufferView, x: int, y: int, text: str, style: Style) -> None:
    if y >= view.height or x >= view.width:
        return
    view.put_text(x, y, text[: view.width - x], style)


class SearchFilterApp(Surface):
    def __init__(self, *, items: tuple[str, ...] = SAMPLE_ITEMS) -> None:
        super().__init__()
        self.items = items
        self.search = Search()
        self.input_state = TextInputState()
        self.filter_idx = 0
        self.picked: str = ""

        # Regions computed in layout()
        self.header_r = Region(0, 0, 0, 0)
        self.input_r = Region(0, 0, 0, 0)
        self.list_r = Region(0, 0, 0, 0)
        self.status_r = Region(0, 0, 0, 0)

    @property
    def _filter_name(self) -> str:
        return FILTER_MODES[self.filter_idx]

    def _filtered(self) -> tuple[str, ...]:
        fn = FILTER_FNS[self._filter_name]
        return fn(self.items, self.search.query)

    def layout(self, width: int, height: int) -> None:
        self.header_r = Region(0, 0, width, 1)
        self.input_r = Region(0, 2, width, 1)
        list_top = 4
        list_h = max(1, height - list_top - 2)
        self.list_r = Region(0, list_top, width, list_h)
        self.status_r = Region(0, height - 1, width, 1)

    def render(self) -> None:
        buf = self._buf
        buf.fill(0, 0, buf.width, buf.height, " ", Style())

        matches = self._filtered()

        # Header
        hv = self.header_r.view(buf)
        _put(hv, 1, 0, "Search Filter", Style(bold=True))
        filter_label = f"[{self._filter_name}]"
        _put(hv, 16, 0, filter_label, Style(fg="cyan"))
        _put(hv, 16 + len(filter_label) + 1, 0, "tab: cycle filter  q: quit", Style(dim=True))

        # Search input
        iv = self.input_r.view(buf)
        _put(iv, 1, 0, "> ", Style(fg="yellow", bold=True))
        inp = text_input(
            self.input_state,
            width=max(1, iv.width - 3),
            focused=True,
            style=Style(),
            cursor_style=Style(reverse=True),
        )
        inp.paint(iv, 3, 0)

        # Separator
        sep_y = 3
        if sep_y < buf.height:
            buf.put_text(0, sep_y, "─" * buf.width, Style(dim=True))

        # Filtered list
        lv = self.list_r.view(buf)
        selected = self.search.selected
        for i, item in enumerate(matches):
            if i >= lv.height:
                break
            is_sel = i == selected
            marker = ">" if is_sel else " "
            style = Style(bold=True, fg="yellow") if is_sel else Style()
            _put(lv, 1, i, f"{marker} {item}", style)

        # Status bar
        sv = self.status_r.view(buf)
        sel_item = self.search.selected_item(matches) or "—"
        picked_info = f"  picked: {self.picked}" if self.picked else ""
        status = f" {len(matches)}/{len(self.items)} matches  sel: {sel_item}{picked_info}"
        _put(sv, 0, 0, status, Style(dim=True))

    def on_key(self, key: str) -> None:
        matches = self._filtered()

        if key == "q" and not self.search.query:
            self.quit()
            return

        if key == "tab":
            self.filter_idx = (self.filter_idx + 1) % len(FILTER_MODES)
            # Re-filter may change match count, clamp selection
            new_matches = self._filtered()
            if self.search.selected >= len(new_matches):
                self.search = Search(query=self.search.query, selected=0)
            return

        if key == "up":
            self.search = self.search.select_prev(len(matches))
            return

        if key == "down":
            self.search = self.search.select_next(len(matches))
            return

        if key == "enter":
            item = self.search.selected_item(matches)
            if item:
                self.picked = item
            return

        if key == "escape":
            self.search = self.search.clear()
            self.input_state = TextInputState()
            return

        if key == "backspace":
            self.search = self.search.backspace()
            self.input_state = self.input_state.delete_back()
            return

        # Printable character → type into search
        if len(key) == 1 and key.isprintable():
            self.search = self.search.type(key)
            self.input_state = self.input_state.insert(key)
            return


async def main() -> None:
    await SearchFilterApp().run()


if __name__ == "__main__":
    asyncio.run(main())
