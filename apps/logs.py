"""Logs viewer app: SSH log streaming with visual polish."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, replace, field

from render.app import RenderApp
from render.block import Block
from render.cell import Style, Cell
from render.compose import join_horizontal
from render.components import ListState, SpinnerState, TextInputState, list_view, spinner, text_input
from render.region import Region
from render.theme import (
    HEADER_BG, FOOTER_BG, FILTER_INPUT_BG,
    HEADER_BASE, HEADER_DIM, HEADER_TARGET, HEADER_CONNECTED, HEADER_ERROR, HEADER_SPINNER,
    FOOTER_BASE, FOOTER_KEY, FOOTER_SEPARATOR, FOOTER_ACTIVE_FILTER,
    FILTER_PROMPT, FILTER_INPUT, FILTER_CURSOR,
    LEVEL_STYLES, LEVEL_LABELS, LEVEL_NAMES,
    SELECTION_CURSOR, SELECTION_HIGHLIGHT, SOURCE_DIM, SCROLL_PAUSED, ERROR_TEXT,
)

LEVEL_PATTERN = re.compile(
    r"\b(ERROR|ERRO|ERR|WARN|WRN|INFO|INF|DEBUG|DBG|TRACE|TRC)\b", re.IGNORECASE
)


# -- State --

@dataclass(frozen=True)
class LogLine:
    """A parsed log line."""
    raw: str
    source: str
    level: str  # one of LEVEL_NAMES or ""
    message: str


@dataclass(frozen=True)
class LogsState:
    """Immutable application state."""
    lines: tuple[LogLine, ...] = ()
    list_state: ListState = field(default_factory=ListState)
    spinner_state: SpinnerState = field(default_factory=SpinnerState)
    input_state: TextInputState = field(default_factory=TextInputState)
    active_filter: str = ""
    level_filters: tuple[bool, ...] = (True, True, True, True, True)  # error, warn, info, debug, trace
    filter_mode: bool = False
    connected: bool = False
    error: str = ""
    auto_scroll: bool = True
    line_count: int = 0
    max_source_width: int = 0


# -- Helpers --

def _detect_level(text: str) -> str:
    """Detect log level from text content."""
    m = LEVEL_PATTERN.search(text)
    if not m:
        return ""
    token = m.group(1).upper()
    if token in ("ERROR", "ERRO", "ERR"):
        return "error"
    if token in ("WARN", "WRN"):
        return "warn"
    if token in ("INFO", "INF"):
        return "info"
    if token in ("DEBUG", "DBG"):
        return "debug"
    if token in ("TRACE", "TRC"):
        return "trace"
    return ""


def _parse_line(raw: str) -> LogLine:
    """Parse a raw log line into source, level, message."""
    # Try "source | message" format
    if " | " in raw:
        parts = raw.split(" | ", 1)
        source = parts[0].strip()
        message = parts[1] if len(parts) > 1 else ""
    else:
        source = ""
        message = raw

    level = _detect_level(raw)
    return LogLine(raw=raw, source=source, level=level, message=message)


def _filter_lines(state: LogsState) -> list[int]:
    """Return indices of lines matching current filters."""
    result = []
    for i, line in enumerate(state.lines):
        # Level filter
        if line.level:
            level_idx = LEVEL_NAMES.index(line.level)
            if not state.level_filters[level_idx]:
                continue

        # Text filter
        if state.active_filter:
            if state.active_filter.lower() not in line.raw.lower():
                continue

        result.append(i)
    return result


# -- App --

class LogsApp(RenderApp):
    """SSH log streaming viewer with visual polish."""

    def __init__(self, target: str, *, ssh_command: str | None = None):
        super().__init__(fps_cap=30)
        self._target = target
        self._ssh_command = ssh_command
        self._state = LogsState()
        self._last_tick = time.monotonic()
        self._process: asyncio.subprocess.Process | None = None
        self._stream_task: asyncio.Task | None = None

        # Regions
        self._region_header = Region(0, 0, 80, 1)
        self._region_main = Region(0, 1, 80, 22)
        self._region_footer = Region(0, 23, 80, 1)

        # Filtered line indices (cached, rebuilt on filter change)
        self._filtered: list[int] = []
        self._filter_dirty = True

    def layout(self, width: int, height: int) -> None:
        self._region_header = Region(0, 0, width, 1)
        self._region_main = Region(0, 1, width, height - 2)
        self._region_footer = Region(0, height - 1, width, 1)

    async def run(self) -> None:
        """Start SSH streaming then run the UI loop."""
        self._stream_task = asyncio.ensure_future(self._stream_logs())
        try:
            await super().run()
        finally:
            if self._stream_task:
                self._stream_task.cancel()
                try:
                    await self._stream_task
                except (asyncio.CancelledError, Exception):
                    pass
            if self._process:
                try:
                    self._process.terminate()
                except ProcessLookupError:
                    pass

    async def _stream_logs(self) -> None:
        """Connect via SSH and stream log lines."""
        try:
            cmd = self._ssh_command or f"ssh {self._target}"
            self._process = await asyncio.create_subprocess_shell(
                cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._state = replace(self._state, connected=True)
            self.mark_dirty()

            assert self._process.stdout is not None
            async for raw_line in self._process.stdout:
                text = raw_line.decode("utf-8", errors="replace").rstrip("\n\r")
                if not text:
                    continue
                parsed = _parse_line(text)
                new_lines = self._state.lines + (parsed,)

                # Track max source width (capped at 20)
                src_w = min(len(parsed.source), 20)
                max_src = max(self._state.max_source_width, src_w)

                new_count = len(new_lines)
                new_list = self._state.list_state
                if self._state.auto_scroll:
                    new_list = replace(new_list, item_count=new_count, selected=new_count - 1)
                else:
                    new_list = replace(new_list, item_count=new_count)

                self._state = replace(
                    self._state,
                    lines=new_lines,
                    list_state=new_list,
                    line_count=new_count,
                    max_source_width=max_src,
                )
                self._filter_dirty = True
                self.mark_dirty()

        except Exception as e:
            self._state = replace(self._state, error=str(e), connected=False)
            self.mark_dirty()

    def update(self) -> None:
        now = time.monotonic()
        if now - self._last_tick >= 0.1:
            self._state = replace(
                self._state,
                spinner_state=self._state.spinner_state.tick(),
            )
            self._last_tick = now
            self.mark_dirty()

    def render(self) -> None:
        if self._buf is None:
            return

        # Rebuild filter cache if needed
        if self._filter_dirty:
            self._filtered = _filter_lines(self._state)
            self._filter_dirty = False

        width = self._region_header.width

        # Clear buffer
        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())

        # Render header
        header_block = self._render_header(width)
        header_view = self._region_header.view(self._buf)
        header_block.paint(header_view, x=0, y=0)

        # Render main log area
        self._render_main()

        # Render footer
        footer_block = self._render_footer(width)
        footer_view = self._region_footer.view(self._buf)
        footer_block.paint(footer_view, x=0, y=0)

    def _render_header(self, width: int) -> Block:
        """Build header: spinner/status + line count + level indicators + scroll pos."""
        parts: list[Cell] = []

        # Connection indicator
        if self._state.connected:
            parts.append(Cell("●", HEADER_CONNECTED))
        elif self._state.error:
            parts.append(Cell("●", HEADER_ERROR))
        else:
            # Show spinner frame while connecting
            frame = self._state.spinner_state.frames.frames[
                self._state.spinner_state.frame % len(self._state.spinner_state.frames.frames)
            ]
            parts.append(Cell(frame, HEADER_SPINNER))

        parts.append(Cell(" ", HEADER_BASE))

        # Target name
        target_display = self._target[:20]
        for ch in target_display:
            parts.append(Cell(ch, HEADER_TARGET))

        parts.append(Cell(" ", HEADER_BASE))
        parts.append(Cell(" ", HEADER_BASE))

        # Line count
        count_str = f"[{self._state.line_count} lines]"
        for ch in count_str:
            parts.append(Cell(ch, HEADER_DIM))

        parts.append(Cell(" ", HEADER_BASE))
        parts.append(Cell(" ", HEADER_BASE))

        # Level indicators: 1:err 2:wrn 3:inf 4:dbg 5:trc
        for idx, (label, name) in enumerate(zip(LEVEL_LABELS, LEVEL_NAMES)):
            active = self._state.level_filters[idx]
            # Key hint
            key_ch = str(idx + 1)
            if active:
                style = Style(fg=LEVEL_STYLES[name].fg, bold=LEVEL_STYLES[name].bold, bg=HEADER_BG)
            else:
                style = HEADER_DIM

            parts.append(Cell(key_ch, HEADER_DIM))
            parts.append(Cell(":", HEADER_DIM))
            for ch in label:
                parts.append(Cell(ch, style))
            parts.append(Cell(" ", HEADER_BASE))

        # Scroll position (right-aligned)
        scroll_info = self._scroll_info()
        # Calculate remaining space
        used = len(parts)
        remaining = width - used - len(scroll_info)
        # Fill gap
        for _ in range(max(0, remaining)):
            parts.append(Cell(" ", HEADER_BASE))
        for ch in scroll_info:
            parts.append(Cell(ch, HEADER_DIM))

        # Pad/truncate to width
        while len(parts) < width:
            parts.append(Cell(" ", HEADER_BASE))
        parts = parts[:width]

        return Block([parts], width)

    def _scroll_info(self) -> str:
        """Build scroll position string."""
        filtered_count = len(self._filtered)
        if filtered_count == 0:
            return ""

        if self._state.auto_scroll:
            return "[end]"

        selected = self._state.list_state.selected
        # Find position in filtered list
        if filtered_count > 0:
            pct = int((selected / max(1, filtered_count - 1)) * 100)
            return f"[{pct}%]"
        return ""

    def _render_main(self) -> None:
        """Render log lines into the main region."""
        view = self._region_main.view(self._buf)
        visible_height = self._region_main.height
        main_width = self._region_main.width

        filtered = self._filtered
        if not filtered:
            # Show empty state
            if self._state.error:
                msg = f"Error: {self._state.error}"
                view.put_text(1, 0, msg, ERROR_TEXT)
            elif not self._state.connected:
                view.put_text(1, 0, "Connecting...", SOURCE_DIM)
            else:
                view.put_text(1, 0, "No matching lines", SOURCE_DIM)
            return

        # Determine visible window based on list_state
        total = len(filtered)
        state = self._state.list_state

        # Calculate scroll offset
        scroll_offset = state.scroll_offset
        if state.selected < scroll_offset:
            scroll_offset = state.selected
        elif state.selected >= scroll_offset + visible_height:
            scroll_offset = state.selected - visible_height + 1
        scroll_offset = max(0, min(scroll_offset, total - visible_height))

        # Determine if we show source column
        has_sources = self._state.max_source_width > 0
        # Check if all sources are the same (single-service mode)
        if has_sources and len(self._state.lines) > 1:
            first_src = self._state.lines[0].source
            single_service = all(
                line.source == first_src for line in self._state.lines[:50]
            )
            if single_service:
                has_sources = False

        source_col_width = min(self._state.max_source_width, 20) if has_sources else 0
        separator_width = 3 if has_sources else 0  # " │ "
        message_start = source_col_width + separator_width

        for row_idx in range(visible_height):
            line_idx = scroll_offset + row_idx
            if line_idx >= total:
                break

            actual_idx = filtered[line_idx]
            line = self._state.lines[actual_idx]
            is_selected = line_idx == state.selected

            # Selection indicator
            if is_selected:
                view.put(0, row_idx, "▸", SELECTION_CURSOR)

            col = 2  # start after cursor + space

            # Source column
            if has_sources:
                src_display = line.source[:source_col_width]
                view.put_text(col, row_idx, src_display, SOURCE_DIM)
                col = 2 + source_col_width

                # Separator
                view.put(col, row_idx, " ", SOURCE_DIM)
                view.put(col + 1, row_idx, "│", SOURCE_DIM)
                view.put(col + 2, row_idx, " ", SOURCE_DIM)
                col += 3

            # Message with level coloring
            level_style = LEVEL_STYLES.get(line.level, Style())
            msg = line.message if has_sources else line.raw
            # Truncate to fit
            max_msg = main_width - col
            if len(msg) > max_msg:
                msg = msg[:max(0, max_msg - 1)] + "…"

            view.put_text(col, row_idx, msg, level_style)

            # Selection highlight (full row background)
            if is_selected:
                for c in range(main_width):
                    cell = self._buf.get(
                        self._region_main.x + c,
                        self._region_main.y + row_idx,
                    )
                    merged_style = Style(
                        fg=cell.style.fg,
                        bg=SELECTION_HIGHLIGHT.bg,
                        bold=cell.style.bold,
                        dim=cell.style.dim,
                        italic=cell.style.italic,
                    )
                    self._buf.put(
                        self._region_main.x + c,
                        self._region_main.y + row_idx,
                        cell.char,
                        merged_style,
                    )

        # Auto-scroll paused indicator
        if not self._state.auto_scroll and total > visible_height:
            indicator = " ↓ auto-scroll paused "
            x_pos = main_width - len(indicator) - 1
            if x_pos > 0:
                view.put_text(x_pos, visible_height - 1, indicator, SCROLL_PAUSED)

    def _render_footer(self, width: int) -> Block:
        """Build footer: keybinds or filter input."""
        parts: list[Cell] = []

        if self._state.filter_mode:
            # Filter mode: show prompt and input
            prompt = " / "
            for ch in prompt:
                parts.append(Cell(ch, FILTER_PROMPT))

            # Render text input inline
            input_width = width - len(prompt)
            text = self._state.input_state.text
            cursor_pos = self._state.input_state.cursor

            for i, ch in enumerate(text[:input_width]):
                if i == cursor_pos:
                    parts.append(Cell(ch, FILTER_CURSOR))
                else:
                    parts.append(Cell(ch, FILTER_INPUT))

            # Cursor at end
            if cursor_pos >= len(text):
                parts.append(Cell(" ", FILTER_CURSOR))

            # Fill rest
            while len(parts) < width:
                parts.append(Cell(" ", FILTER_INPUT))

        else:
            # Normal mode: keybind hints
            hints = [
                ("q", "quit"),
                ("/", "filter"),
                ("j/k", "scroll"),
                ("g/G", "top/btm"),
                ("1-5", "levels"),
            ]

            # Show active filter if any
            if self._state.active_filter:
                filter_display = f" filter: {self._state.active_filter} "
                for ch in filter_display:
                    parts.append(Cell(ch, FOOTER_ACTIVE_FILTER))
                parts.append(Cell("│", FOOTER_SEPARATOR))

            parts.append(Cell(" ", FOOTER_BASE))
            for i, (key, desc) in enumerate(hints):
                for ch in key:
                    parts.append(Cell(ch, FOOTER_KEY))
                parts.append(Cell(":", FOOTER_BASE))
                for ch in desc:
                    parts.append(Cell(ch, FOOTER_BASE))
                if i < len(hints) - 1:
                    parts.append(Cell(" ", FOOTER_BASE))
                    parts.append(Cell(" ", FOOTER_BASE))

            # Fill rest with footer bg
            while len(parts) < width:
                parts.append(Cell(" ", FOOTER_BASE))

        parts = parts[:width]
        return Block([parts], width)

    def on_key(self, key: str) -> None:
        if self._state.filter_mode:
            self._handle_filter_key(key)
        else:
            self._handle_normal_key(key)

    def _handle_normal_key(self, key: str) -> None:
        if key == "q":
            self.quit()
            return

        if key == "/":
            self._state = replace(
                self._state,
                filter_mode=True,
                input_state=TextInputState(text=self._state.active_filter,
                                           cursor=len(self._state.active_filter)),
            )
            return

        if key in ("j", "down"):
            self._scroll_down()
            return

        if key in ("k", "up"):
            self._scroll_up()
            return

        if key == "g":
            self._scroll_top()
            return

        if key == "G":
            self._scroll_bottom()
            return

        if key in "12345":
            idx = int(key) - 1
            filters = list(self._state.level_filters)
            filters[idx] = not filters[idx]
            self._state = replace(self._state, level_filters=tuple(filters))
            self._filter_dirty = True
            return

    def _handle_filter_key(self, key: str) -> None:
        if key == "escape":
            self._state = replace(self._state, filter_mode=False)
            return

        if key == "enter":
            self._state = replace(
                self._state,
                filter_mode=False,
                active_filter=self._state.input_state.text,
            )
            self._filter_dirty = True
            return

        if key == "backspace":
            self._state = replace(
                self._state,
                input_state=self._state.input_state.delete_back(),
            )
            return

        if key.isprintable() and len(key) == 1:
            self._state = replace(
                self._state,
                input_state=self._state.input_state.insert(key),
            )
            return

    def _scroll_down(self) -> None:
        filtered_count = len(self._filtered)
        if filtered_count == 0:
            return
        new_selected = min(self._state.list_state.selected + 1, filtered_count - 1)
        at_bottom = new_selected >= filtered_count - 1
        self._state = replace(
            self._state,
            list_state=replace(self._state.list_state, selected=new_selected),
            auto_scroll=at_bottom,
        )

    def _scroll_up(self) -> None:
        if len(self._filtered) == 0:
            return
        new_selected = max(self._state.list_state.selected - 1, 0)
        self._state = replace(
            self._state,
            list_state=replace(self._state.list_state, selected=new_selected),
            auto_scroll=False,
        )

    def _scroll_top(self) -> None:
        self._state = replace(
            self._state,
            list_state=replace(self._state.list_state, selected=0, scroll_offset=0),
            auto_scroll=False,
        )

    def _scroll_bottom(self) -> None:
        filtered_count = len(self._filtered)
        if filtered_count == 0:
            return
        self._state = replace(
            self._state,
            list_state=replace(self._state.list_state, selected=filtered_count - 1),
            auto_scroll=True,
        )


async def main(target: str = "localhost", *, ssh_command: str | None = None):
    app = LogsApp(target, ssh_command=ssh_command)
    await app.run()


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    asyncio.run(main(target))
