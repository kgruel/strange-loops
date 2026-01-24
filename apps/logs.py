#!/usr/bin/env python3
"""Streaming log viewer — SSH to homelab hosts and tail docker compose logs.

Rendered entirely with the render layer (no Rich).

Usage:
    python -m apps.logs infra --host 10.0.0.1
    python -m apps.logs infra --host 10.0.0.1 --service traefik --level error,warn
    python -m apps.logs infra --host 10.0.0.1 --user deploy --tail 200
"""

from __future__ import annotations

import argparse
import asyncio
import re
import shlex
import time
from dataclasses import dataclass, replace

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from render.app import RenderApp
from render.cell import Style
from render.components import ListState, SpinnerState, TextInputState
from render.region import Region
from render.span import Span, Line
from render.theme import (
    HEADER_BASE, HEADER_BOLD, HEADER_DIM, HEADER_CONNECTED, HEADER_ERROR,
    HEADER_SPINNER, HEADER_LEVEL_FILTER,
    FOOTER_KEY, FOOTER_DIM, FOOTER_ACTIVE_FILTER,
    FILTER_PROMPT, FILTER_CURSOR,
    LEVEL_STYLES, SELECTION_CURSOR, SELECTION_HIGHLIGHT, SOURCE_DIM,
    DEBUG_OVERLAY,
)
from render.timer import FrameTimer


# =============================================================================
# Log parsing (lifted from logs-v2.py)
# =============================================================================

_LEVEL_PATTERNS = [
    (re.compile(r"\[ERROR\]", re.IGNORECASE), "error"),
    (re.compile(r"\[WARN(?:ING)?\]", re.IGNORECASE), "warn"),
    (re.compile(r"\[INFO\]", re.IGNORECASE), "info"),
    (re.compile(r"\[DEBUG\]", re.IGNORECASE), "debug"),
    (re.compile(r"\[TRACE\]", re.IGNORECASE), "trace"),
    (re.compile(r'\blevel[=:]\s*"?error"?', re.IGNORECASE), "error"),
    (re.compile(r'\blevel[=:]\s*"?warn(?:ing)?"?', re.IGNORECASE), "warn"),
    (re.compile(r'\blevel[=:]\s*"?info"?', re.IGNORECASE), "info"),
    (re.compile(r'\blevel[=:]\s*"?debug"?', re.IGNORECASE), "debug"),
    (re.compile(r'"level"\s*:\s*"error"', re.IGNORECASE), "error"),
    (re.compile(r'"level"\s*:\s*"warn(?:ing)?"', re.IGNORECASE), "warn"),
    (re.compile(r'"level"\s*:\s*"info"', re.IGNORECASE), "info"),
    (re.compile(r'"level"\s*:\s*"debug"', re.IGNORECASE), "debug"),
    (re.compile(r"\bERROR\b"), "error"),
    (re.compile(r"\bWARNING\b"), "warn"),
    (re.compile(r"\bFATAL\b", re.IGNORECASE), "error"),
    (re.compile(r"\bCRITICAL\b", re.IGNORECASE), "error"),
]

_SOURCE_COLORS = [
    "cyan", "green", "yellow", "blue", "magenta",
    "red", "#5fafff", "#5fd787", "#d7af5f", "#af87d7",
]

LEVELS = ["error", "warn", "info", "debug", "trace"]



def _detect_level(message: str) -> str | None:
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(message):
            return level
    return None


@dataclass(frozen=True)
class LogLine:
    message: str
    raw: str | None = None
    source: str | None = None
    level: str | None = None


def _parse_log_line(line: str) -> LogLine:
    if " | " in line:
        source, message = line.split(" | ", 1)
        return LogLine(raw=line, source=source.strip(), message=message,
                       level=_detect_level(message))
    return LogLine(raw=line, source=None, message=line, level=_detect_level(line))


# =============================================================================
# Source color assignment
# =============================================================================

class SourceColorMap:
    """Assigns stable colors to sources by first-seen order."""

    def __init__(self):
        self._map: dict[str, str] = {}

    def get(self, source: str) -> str:
        if source not in self._map:
            self._map[source] = _SOURCE_COLORS[len(self._map) % len(_SOURCE_COLORS)]
        return self._map[source]


# =============================================================================
# App state
# =============================================================================

@dataclass(frozen=True)
class LogsState:
    stack: str = ""
    host: str = ""
    user: str = "deploy"
    service: str | None = None
    tail: int = 100
    follow: bool = True
    identity: str | None = None

    connected: bool = False
    connecting: bool = True
    error: str | None = None

    lines: tuple[LogLine, ...] = ()
    line_count: int = 0

    filter_text: str = ""
    level_filter: frozenset[str] = frozenset()  # empty = show all

    auto_scroll: bool = True
    filter_focused: bool = False

    def add_line(self, line: LogLine) -> LogsState:
        new_lines = self.lines + (line,)
        if len(new_lines) > 5000:
            new_lines = new_lines[-5000:]
        return replace(self, lines=new_lines, line_count=self.line_count + 1)

    def filtered_lines(self) -> list[LogLine]:
        result = []
        for line in self.lines:
            if self.level_filter:
                line_level = line.level or "info"
                if line_level not in self.level_filter:
                    continue
            if self.filter_text:
                text = self.filter_text.lower()
                haystack = (line.message + " " + (line.source or "")).lower()
                if text not in haystack:
                    continue
            result.append(line)
        return result

    def toggle_level(self, level: str) -> LogsState:
        if level in self.level_filter:
            return replace(self, level_filter=self.level_filter - {level})
        else:
            return replace(self, level_filter=self.level_filter | {level})


# =============================================================================
# LogsApp
# =============================================================================

class LogsApp(RenderApp):
    """Streaming log viewer on the cell-buffer render layer."""

    def __init__(self, args: argparse.Namespace):
        super().__init__(fps_cap=30)
        self._state = LogsState(
            stack=args.stack,
            host=args.host,
            user=args.user,
            service=args.service,
            tail=args.tail,
            follow=args.follow,
            identity=args.identity,
        )
        self._list_state = ListState()
        self._input_state = TextInputState()
        self._spinner_state = SpinnerState()
        self._source_colors = SourceColorMap()
        self._last_tick = time.monotonic()
        self._profile_path = getattr(args, 'profile', None)
        self._timer = FrameTimer(profile=bool(self._profile_path))
        self._show_debug = False
        self._frame_trigger: set[str] = set()

        self._region_header = Region(0, 0, 80, 1)
        self._region_main = Region(0, 1, 80, 20)
        self._region_footer = Region(0, 21, 80, 2)

        self._proc: asyncio.subprocess.Process | None = None
        self._stream_task: asyncio.Task | None = None

    # -- Lifecycle -------------------------------------------------------------

    def layout(self, width: int, height: int) -> None:
        header_h = 1
        footer_h = 2
        main_h = max(1, height - header_h - footer_h)

        self._region_header = Region(0, 0, width, header_h)
        self._region_main = Region(0, header_h, width, main_h)
        self._region_footer = Region(0, header_h + main_h, width, footer_h)

        # Re-sync list scroll
        filtered = self._state.filtered_lines()
        self._list_state = replace(
            self._list_state,
            item_count=len(filtered),
        )
        if self._state.auto_scroll and filtered:
            self._list_state = replace(
                self._list_state,
                selected=len(filtered) - 1,
            ).scroll_into_view(main_h)

    def update(self) -> None:
        now = time.monotonic()
        if self._state.connecting and now - self._last_tick >= 0.08:
            self._spinner_state = self._spinner_state.tick()
            self._last_tick = now
            self._frame_trigger.add("spinner")
            self.mark_dirty()
        if self._show_debug:
            self._frame_trigger.add("debug")
            self.mark_dirty()

    async def run(self) -> None:
        """Override to start SSH streaming alongside the render loop."""
        self._running = True
        self._writer.enter_alt_screen()
        self._writer.hide_cursor()

        width, height = self._writer.size()
        from render.buffer import Buffer
        self._buf = Buffer(width, height)
        self._prev = Buffer(width, height)
        self.layout(width, height)

        import signal as sig
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(sig.SIGWINCH, self._on_resize)

        self._stream_task = asyncio.create_task(self._stream_logs())

        try:
            with self._keyboard:
                while self._running:
                    self._timer.begin_frame()

                    with self._timer.phase("keys"):
                        while True:
                            key = self._keyboard.get_key()
                            if key is None:
                                break
                            self.on_key(key)
                            self._dirty = True
                            self._frame_trigger.add("key")

                    with self._timer.phase("update"):
                        self.update()

                    rendered = False
                    if self._dirty:
                        self._dirty = False
                        rendered = True
                        with self._timer.phase("render"):
                            self.render()
                        with self._timer.phase("flush"):
                            self._flush()

                    if self._frame_trigger:
                        self._timer.set_meta("trigger", sorted(self._frame_trigger))
                    self._timer.set_meta("items", len(self._state.lines))
                    self._timer.set_meta("rendered", rendered)
                    self._frame_trigger = set()
                    self._timer.end_frame()
                    await asyncio.sleep(1.0 / self._fps_cap)
        finally:
            loop.remove_signal_handler(sig.SIGWINCH)
            if self._stream_task and not self._stream_task.done():
                self._stream_task.cancel()
                try:
                    await self._stream_task
                except asyncio.CancelledError:
                    pass
            if self._proc and self._proc.returncode is None:
                self._proc.terminate()
                try:
                    await self._proc.wait()
                except Exception:
                    pass
            self._writer.show_cursor()
            self._writer.exit_alt_screen()
            if self._profile_path:
                from pathlib import Path
                n = self._timer.dump_jsonl(Path(self._profile_path))
                print(f"profile: {n} frames → {self._profile_path}")

    # -- SSH streaming ---------------------------------------------------------

    async def _stream_logs(self) -> None:
        ssh_args = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "LogLevel=ERROR",
        ]
        if self._state.identity:
            ssh_args.extend(["-i", self._state.identity])

        cmd = ["docker", "compose", "logs", "--no-color",
               "--tail", str(self._state.tail)]
        if self._state.follow:
            cmd.append("-f")
        if self._state.service:
            cmd.append(self._state.service)

        remote_cmd = (
            f"cd /opt/{shlex.quote(self._state.stack)} && {shlex.join(cmd)}"
        )

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *ssh_args,
                f"{self._state.user}@{self._state.host}",
                remote_cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            self._state = replace(self._state, connected=True, connecting=False)
            self.mark_dirty()

            assert self._proc.stdout is not None
            while True:
                raw = await self._proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").rstrip("\n")
                if not line:
                    continue

                parsed = _parse_log_line(line)
                self._state = self._state.add_line(parsed)

                # Sync list state
                filtered = self._state.filtered_lines()
                self._list_state = replace(
                    self._list_state, item_count=len(filtered)
                )
                if self._state.auto_scroll and filtered:
                    self._list_state = replace(
                        self._list_state, selected=len(filtered) - 1
                    ).scroll_into_view(self._region_main.height)

                self._frame_trigger.add("data")
                self.mark_dirty()

            rc = await self._proc.wait()
            if rc != 0:
                self._state = replace(self._state,
                                      error=f"exit {rc}", connecting=False)
            else:
                self._state = replace(self._state, connecting=False)
            self.mark_dirty()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._state = replace(self._state, error=str(e),
                                  connecting=False, connected=False)
            self.mark_dirty()

    # -- Rendering -------------------------------------------------------------

    def render(self) -> None:
        if self._buf is None:
            return
        with self._timer.phase("r.clear"):
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        with self._timer.phase("r.header"):
            self._render_header()
        with self._timer.phase("r.main"):
            self._render_main()
        with self._timer.phase("r.footer"):
            self._render_footer()
        if self._show_debug:
            self._render_debug()

    def _render_header(self) -> None:
        view = self._region_header.view(self._buf)
        width = self._region_header.width
        view.fill(0, 0, width, 1, " ", HEADER_BASE)

        spans: list[Span] = []
        spans.append(Span(f" {self._state.stack}", HEADER_BOLD))

        if self._state.connecting:
            frame = self._spinner_state.frames.frames[
                self._spinner_state.frame % len(self._spinner_state.frames.frames)
            ]
            spans.append(Span(f" {frame} ", HEADER_SPINNER))
            spans.append(Span("connecting", HEADER_DIM))
        elif self._state.error:
            spans.append(Span(f" ✗ {self._state.error}", HEADER_ERROR))
        elif self._state.connected:
            spans.append(Span(" ●", HEADER_CONNECTED))

        filtered = self._state.filtered_lines()
        spans.append(Span(f" {len(filtered)}/{self._state.line_count}", HEADER_DIM))

        if self._state.level_filter:
            lvl_str = " [" + ",".join(sorted(self._state.level_filter)) + "]"
            spans.append(Span(lvl_str, HEADER_LEVEL_FILTER))

        Line(tuple(spans), style=HEADER_BASE).truncate(width).paint(view, x=0, y=0)

    def _render_main(self) -> None:
        view = self._region_main.view(self._buf)
        width = self._region_main.width
        height = self._region_main.height

        with self._timer.phase("m.filter"):
            filtered = self._state.filtered_lines()
        if not filtered:
            return

        start = self._list_state.scroll_offset
        end = min(start + height, len(filtered))
        content_width = width - 2  # room for cursor prefix

        with self._timer.phase("m.build"):
            for row_idx, line in enumerate(filtered[start:end]):
                is_selected = (start + row_idx) == self._list_state.selected
                row_line = self._render_log_line(line, content_width)
                if is_selected:
                    sel = Line(
                        (Span("▸ ", SELECTION_CURSOR),) + row_line.spans,
                        style=SELECTION_HIGHLIGHT,
                    ).truncate(width)
                    sel.paint(view, x=0, y=row_idx)
                else:
                    prefixed = Line((Span("  "),) + row_line.spans).truncate(width)
                    prefixed.paint(view, x=0, y=row_idx)

    def _render_log_line(self, line: LogLine, width: int) -> Line:
        """Build a Line for a single log entry."""
        spans: list[Span] = []

        if line.source:
            color = self._source_colors.get(line.source)
            spans.append(Span(f"{line.source:>12} ", Style(fg=color)))
            spans.append(Span("│ ", SOURCE_DIM))

        msg_style = LEVEL_STYLES.get(line.level, Style())
        spans.append(Span(line.message, msg_style))

        return Line(tuple(spans)).truncate(width)

    def _render_footer(self) -> None:
        view = self._region_footer.view(self._buf)
        width = self._region_footer.width

        # Row 0: filter
        if self._state.filter_focused:
            spans: list[Span] = [Span("/", FILTER_PROMPT)]
            text = self._input_state.text
            cursor = self._input_state.cursor
            if text[:cursor]:
                spans.append(Span(text[:cursor]))
            cursor_ch = text[cursor] if cursor < len(text) else " "
            spans.append(Span(cursor_ch, FILTER_CURSOR))
            if cursor < len(text) - 1:
                spans.append(Span(text[cursor + 1:]))
            Line(tuple(spans)).truncate(width).paint(view, x=0, y=0)
        elif self._state.filter_text:
            Line((Span(f" filter: {self._state.filter_text}", FOOTER_ACTIVE_FILTER),)).truncate(width).paint(view, x=0, y=0)

        # Row 1: keyboard hints
        hints = [("q", "quit"), ("/", "filter"), ("j/k", "scroll"),
                 ("1-5", "levels"), ("G", "bottom"), ("d", "perf")]
        hint_spans: list[Span] = []
        for key, desc in hints:
            hint_spans.append(Span(f" {key}", FOOTER_KEY))
            hint_spans.append(Span(f"={desc}", FOOTER_DIM))

        Line(tuple(hint_spans)).truncate(width).paint(view, x=0, y=1)

    def _render_debug(self) -> None:
        """Overlay frame timing stats in top-right corner."""
        last = self._timer.last()
        if last is None:
            return

        # Build lines: phase name + last ms + avg ms
        lines: list[str] = []
        lines.append(f"{'phase':<10} {'last':>6} {'avg':>6} {'max':>6}")
        lines.append(f"{'─' * 10} {'─' * 6} {'─' * 6} {'─' * 6}")
        for name in self._timer.phase_names():
            val = last.phases.get(name, 0.0)
            avg = self._timer.avg(name)
            mx = self._timer.max(name)
            lines.append(f"{name:<10} {val:>5.1f}m {avg:>5.1f}m {mx:>5.1f}m")
        lines.append(f"{'─' * 10} {'─' * 6} {'─' * 6} {'─' * 6}")
        lines.append(f"{'TOTAL':<10} {last.total:>5.1f}m {self._timer.avg_total():>5.1f}m")

        # Also show item counts for context
        filtered = self._state.filtered_lines()
        lines.append(f"items: {len(filtered)}/{len(self._state.lines)}")

        # Paint directly into buffer at top-right
        panel_w = max(len(l) for l in lines) + 2
        panel_h = len(lines) + 1
        x_start = max(0, self._buf.width - panel_w - 1)
        y_start = 1

        bg = DEBUG_OVERLAY
        for dy, line in enumerate(lines):
            y = y_start + dy
            if y >= self._buf.height:
                break
            # Background fill for this row
            for dx in range(panel_w):
                self._buf.put(x_start + dx, y, " ", bg)
            # Write text
            self._buf.put_text(x_start + 1, y, line[:panel_w - 2], bg)

    def _flush(self) -> None:
        if self._buf is None or self._prev is None:
            return
        with self._timer.phase("f.diff"):
            writes = self._buf.diff(self._prev)
        if writes:
            with self._timer.phase("f.write"):
                self._writer.write_frame(writes)
        with self._timer.phase("f.clone"):
            self._prev = self._buf.clone()

    # -- Keyboard --------------------------------------------------------------

    def on_key(self, key: str) -> None:
        if self._state.filter_focused:
            self._handle_filter_key(key)
            return

        if key == "q":
            self.quit()
        elif key == "/":
            self._state = replace(self._state, filter_focused=True)
        elif key in ("j", "down"):
            self._scroll_down()
        elif key in ("k", "up"):
            self._scroll_up()
        elif key == "G":
            self._jump_to_bottom()
        elif key == "g":
            self._jump_to_top()
        elif key == "escape":
            if self._state.filter_text:
                self._state = replace(self._state, filter_text="")
                self._input_state = TextInputState()
                self._sync_list_after_filter()
        elif key == "d":
            self._show_debug = not self._show_debug
        elif key in "12345":
            level_idx = int(key) - 1
            if level_idx < len(LEVELS):
                self._state = self._state.toggle_level(LEVELS[level_idx])
                self._sync_list_after_filter()

    def _handle_filter_key(self, key: str) -> None:
        if key == "escape":
            self._state = replace(self._state, filter_focused=False, filter_text="")
            self._input_state = TextInputState()
            self._sync_list_after_filter()
        elif key == "enter":
            self._state = replace(
                self._state, filter_focused=False,
                filter_text=self._input_state.text,
            )
            self._sync_list_after_filter()
        elif key == "backspace":
            self._input_state = self._input_state.delete_back()
            self._state = replace(self._state, filter_text=self._input_state.text)
            self._sync_list_after_filter()
        elif key.isprintable() and len(key) == 1:
            self._input_state = self._input_state.insert(key)
            self._state = replace(self._state, filter_text=self._input_state.text)
            self._sync_list_after_filter()

    def _sync_list_after_filter(self) -> None:
        filtered = self._state.filtered_lines()
        self._list_state = replace(self._list_state, item_count=len(filtered))
        if self._state.auto_scroll and filtered:
            self._list_state = replace(
                self._list_state, selected=len(filtered) - 1
            ).scroll_into_view(self._region_main.height)

    def _scroll_up(self) -> None:
        self._state = replace(self._state, auto_scroll=False)
        self._list_state = self._list_state.move_up().scroll_into_view(
            self._region_main.height
        )

    def _scroll_down(self) -> None:
        self._list_state = self._list_state.move_down().scroll_into_view(
            self._region_main.height
        )
        filtered = self._state.filtered_lines()
        if filtered and self._list_state.selected >= len(filtered) - 1:
            self._state = replace(self._state, auto_scroll=True)

    def _jump_to_bottom(self) -> None:
        self._state = replace(self._state, auto_scroll=True)
        filtered = self._state.filtered_lines()
        if filtered:
            self._list_state = replace(
                self._list_state, selected=len(filtered) - 1
            ).scroll_into_view(self._region_main.height)

    def _jump_to_top(self) -> None:
        self._state = replace(self._state, auto_scroll=False)
        self._list_state = replace(
            self._list_state, selected=0, scroll_offset=0
        )


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streaming log viewer for homelab docker compose stacks",
        prog="logs",
    )
    parser.add_argument("stack", help="Stack name (matches /opt/<stack> on remote)")
    parser.add_argument("--host", required=True, help="SSH host (IP or hostname)")
    parser.add_argument("--user", default="deploy", help="SSH user (default: deploy)")
    parser.add_argument("-s", "--service", default=None,
                        help="Filter to a specific service")
    parser.add_argument("--tail", type=int, default=100,
                        help="Number of initial lines (default: 100)")
    parser.add_argument("-i", "--identity", default=None,
                        help="SSH identity file path")
    parser.add_argument("--level", default=None,
                        help="Initial level filter (comma-separated)")
    parser.add_argument("--no-follow", dest="follow", action="store_false",
                        help="Don't follow (just tail)")
    parser.add_argument("--profile", default=None, metavar="PATH",
                        help="Dump per-frame timing JSONL to this path on exit")
    parser.set_defaults(follow=True)
    return parser.parse_args()


async def main():
    args = parse_args()
    app = LogsApp(args)

    if args.level:
        levels = frozenset(
            ("warn" if v.strip().lower() == "warning" else v.strip().lower())
            for v in args.level.split(",") if v.strip()
        )
        app._state = replace(app._state, level_filter=levels)

    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
