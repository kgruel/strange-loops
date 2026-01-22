#!/usr/bin/env python3
"""
Reactive logs viewer - port of gruel.network's logs.py

Demonstrates:
- Unbounded Signal + bounded Computed view (scrolling buffer pattern)
- Dynamic color assignment for sources
- Multiple output modes (UI, record, filtered)
- Conditional event emission based on mode

Run with:
    uv run examples/logs_reactive.py                    # UI mode
    uv run examples/logs_reactive.py --record out.jsonl # Record all lines
    uv run examples/logs_reactive.py --level error,warn # Filter by level
    uv run examples/logs_reactive.py --no-ui            # Events only (for LLM tailing)
"""

# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "reaktiv",
#     "rich",
#     "typing_extensions",
#     "ev @ file:///Users/kaygee/Code/ev",
# ]
# [tool.uv.sources]
# reaktiv_cli = { path = "../reaktiv_cli" }
# ///

from __future__ import annotations

import argparse
import asyncio
import random
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from reaktiv import Effect
from reaktiv_cli import ReactiveEmitter, Signal, Computed, batch
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

from ev import Event, Result, Emitter, ListEmitter


# =============================================================================
# LOG LINE PARSING
# =============================================================================

_LEVEL_PATTERNS = [
    (re.compile(r"\[ERROR\]", re.IGNORECASE), "error"),
    (re.compile(r"\[WARN(?:ING)?\]", re.IGNORECASE), "warn"),
    (re.compile(r"\[INFO\]", re.IGNORECASE), "info"),
    (re.compile(r"\[DEBUG\]", re.IGNORECASE), "debug"),
    (re.compile(r'\blevel[=:]\s*"?error"?', re.IGNORECASE), "error"),
    (re.compile(r'\blevel[=:]\s*"?warn(?:ing)?"?', re.IGNORECASE), "warn"),
    (re.compile(r'\blevel[=:]\s*"?info"?', re.IGNORECASE), "info"),
    (re.compile(r'\blevel[=:]\s*"?debug"?', re.IGNORECASE), "debug"),
    (re.compile(r"\bERROR\b"), "error"),
    (re.compile(r"\bWARNING\b"), "warn"),
    (re.compile(r"\bFATAL\b", re.IGNORECASE), "error"),
]

SOURCE_COLORS = [
    "cyan", "green", "yellow", "blue", "magenta",
    "red", "bright_cyan", "bright_green", "bright_yellow", "bright_blue",
]

LEVEL_STYLES = {
    "error": "red bold",
    "warn": "yellow",
    "info": None,
    "debug": "dim",
    "trace": "dim",
}

LEVEL_PRIORITY = {"error": 0, "warn": 1, "info": 2, "debug": 3, "trace": 4}


def detect_level(message: str) -> str | None:
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(message):
            return level
    return None


@dataclass(frozen=True)
class LogLine:
    """A parsed log line."""
    message: str
    raw: str | None = None
    source: str | None = None
    level: str | None = None
    timestamp: datetime | None = None
    index: int = 0  # Line number for tracking


def parse_compose_log_line(line: str, index: int = 0) -> LogLine:
    """Parse a docker compose log line."""
    if " | " in line:
        source, message = line.split(" | ", 1)
        return LogLine(
            raw=line, source=source.strip(), message=message,
            level=detect_level(message), index=index,
        )
    return LogLine(raw=line, source=None, message=line, level=detect_level(line), index=index)


# =============================================================================
# OUTPUT MODE CONFIGURATION
# =============================================================================

@dataclass
class OutputConfig:
    """Configuration for output modes."""
    show_ui: bool = True
    record_all: bool = False  # Emit every line as event
    level_filter: set[str] | None = None  # None = all levels
    unfiltered_path: Path | None = None  # Separate file for unfiltered output


# =============================================================================
# REACTIVE STATE MODEL
# =============================================================================

def create_logs_state(max_visible: int = 200, level_filter: set[str] | None = None):
    """
    Create the reactive state for logs viewing.

    Args:
        max_visible: Maximum lines to show in UI
        level_filter: If set, only show lines with these levels (affects UI AND events)
    """
    # Core state
    lines: Signal[list[LogLine]] = Signal([])
    source_colors: Signal[dict[str, str]] = Signal({})

    # Filter config (can be changed at runtime)
    filter_levels: Signal[set[str] | None] = Signal(level_filter)

    # Derived: filtered lines (respects level filter)
    def apply_filter() -> list[LogLine]:
        lvls = filter_levels()
        if lvls is None:
            return lines()
        return [l for l in lines() if (l.level or "info") in lvls]

    filtered_lines = Computed(apply_filter)

    # Derived: visible window (from filtered)
    visible_lines = Computed(lambda: filtered_lines()[-max_visible:])

    # Counts
    total_count = Computed(lambda: len(lines()))
    visible_count = Computed(lambda: len(filtered_lines()))

    return lines, source_colors, filtered_lines, visible_lines, total_count, visible_count, filter_levels


def assign_color(source_colors: Signal[dict[str, str]], source: str) -> str:
    """Get or assign a color for a source."""
    colors = source_colors()
    if source not in colors:
        new_color = SOURCE_COLORS[len(colors) % len(SOURCE_COLORS)]
        source_colors.set({**colors, source: new_color})
    return source_colors()[source]


# =============================================================================
# UI COMPONENT
# =============================================================================

class LogsUI:
    """Reactive logs UI component."""

    def __init__(
        self,
        visible_lines: Callable[[], list[LogLine]],
        source_colors: Callable[[], dict[str, str]],
        total_count: Callable[[], int],
        visible_count: Callable[[], int] | None = None,
        *,
        title: str = "Logs",
        source_width: int = 15,
    ):
        self._visible_lines = visible_lines
        self._source_colors = source_colors
        self._total_count = total_count
        self._visible_count = visible_count
        self._title = title
        self._source_width = source_width

    def render(self) -> Layout:
        # Show "X/Y lines" if filtered, else just "X lines"
        total = self._total_count()
        if self._visible_count and self._visible_count() != total:
            count_str = f"{self._visible_count()}/{total} lines (filtered)"
        else:
            count_str = f"{total} lines"

        header = Panel(
            f"[bold]{self._title}[/bold]  [dim]{count_str}[/dim]",
            expand=False, border_style="dim",
        )
        lines = self._visible_lines()
        colors = self._source_colors()
        rendered = [self._render_line(line, colors) for line in lines]
        body = Group(*rendered) if rendered else Text("[dim]Waiting for logs...[/dim]")

        layout = Layout()
        layout.split_column(
            Layout(header, name="header", size=3),
            Layout(body, name="logs"),
        )
        return layout

    def _render_line(self, line: LogLine, colors: dict[str, str]) -> Text:
        text = Text()
        if line.source:
            color = colors.get(line.source, "white")
            text.append(f"{line.source:{self._source_width}}", style=color)
            text.append(" \u2502 ", style="dim")
        style = LEVEL_STYLES.get(line.level) if line.level else None
        text.append(line.message, style=style)
        return text


# =============================================================================
# EMITTER UTILITIES
# =============================================================================

class TeeEmitter:
    """Fan out events to multiple emitters."""

    def __init__(self, *emitters: Emitter):
        self._emitters = [e for e in emitters if e is not None]

    def __enter__(self):
        for e in self._emitters:
            e.__enter__()
        return self

    def __exit__(self, *args):
        for e in self._emitters:
            e.__exit__(*args)

    def emit(self, event: Event) -> None:
        for e in self._emitters:
            e.emit(event)

    def finish(self, result: Result) -> None:
        for e in self._emitters:
            e.finish(result)


class FileEmitter:
    """Write events as JSONL to a file."""

    def __init__(self, path: Path):
        self._path = path
        self._file = None

    def __enter__(self):
        self._file = open(self._path, "w")
        return self

    def __exit__(self, *args):
        if self._file:
            self._file.close()

    def emit(self, event: Event) -> None:
        if self._file:
            import json
            self._file.write(json.dumps(event.to_dict()) + "\n")
            self._file.flush()

    def finish(self, result: Result) -> None:
        if self._file:
            import json
            self._file.write(json.dumps({"type": "result", **result.to_dict()}) + "\n")


class FilteredEmitter:
    """Filter events by predicate before forwarding."""

    def __init__(self, inner: Emitter, predicate: Callable[[Event], bool]):
        self._inner = inner
        self._predicate = predicate

    def __enter__(self):
        self._inner.__enter__()
        return self

    def __exit__(self, *args):
        self._inner.__exit__(*args)

    def emit(self, event: Event) -> None:
        if self._predicate(event):
            self._inner.emit(event)

    def finish(self, result: Result) -> None:
        self._inner.finish(result)


def level_filter_predicate(levels: set[str]) -> Callable[[Event], bool]:
    """Create a predicate that filters events by level."""
    def predicate(event: Event) -> bool:
        # Always pass non-log events and signals
        if event.kind != "log" or event.is_signal:
            return True
        event_level = event.data.get("log_level") or event.level or "info"
        return event_level in levels
    return predicate


# =============================================================================
# MOCK LOG STREAM
# =============================================================================

MOCK_SERVICES = ["traefik", "postgres", "redis", "api", "worker", "nginx"]
MOCK_MESSAGES = [
    ("[INFO] Request handled successfully", "info"),
    ("[DEBUG] Cache hit for key user:123", "debug"),
    ("[WARN] Connection pool running low", "warn"),
    ("[ERROR] Failed to connect to database", "error"),
    ("level=info msg=\"Health check passed\"", "info"),
    ("level=warn msg=\"Slow query detected\"", "warn"),
    ("level=error msg=\"Out of memory\"", "error"),
    ("Starting service...", None),
    ("Listening on port 8080", None),
    ("Received SIGTERM, shutting down", None),
]


async def mock_log_stream(
    lines: Signal[list[LogLine]],
    source_colors: Signal[dict[str, str]],
    on_line: Callable[[LogLine], None] | None = None,
    *,
    num_lines: int = 50,
    delay_range: tuple[float, float] = (0.05, 0.2),
):
    """Generate mock log lines and update the signal."""
    for i in range(num_lines):
        await asyncio.sleep(random.uniform(*delay_range))

        source = random.choice(MOCK_SERVICES)
        message, _ = random.choice(MOCK_MESSAGES)
        assign_color(source_colors, source)

        raw = f"{source} | {message}"
        log_line = parse_compose_log_line(raw, index=i)

        lines.update(lambda ls: [*ls, log_line])

        # Callback for per-line event emission
        if on_line:
            on_line(log_line)


# =============================================================================
# OPERATION
# =============================================================================

async def logs_operation_reactive(
    rem: ReactiveEmitter,
    config: OutputConfig,
    *,
    max_visible: int = 200,
    num_lines: int = 100,
) -> Result:
    """Reactive logs operation with configurable output modes."""

    # =========================================================================
    # STATE LAYER
    # =========================================================================

    (
        lines, source_colors, filtered_lines, visible_lines,
        total_count, visible_count, filter_levels
    ) = create_logs_state(max_visible, level_filter=config.level_filter)

    status: Signal[str] = Signal("starting")

    # =========================================================================
    # UI LAYER (conditional)
    # =========================================================================

    if config.show_ui:
        ui = LogsUI(
            visible_lines, source_colors, total_count, visible_count,
            title="Mock Logs Stream",
        )
        rem.set_ui(ui.render)

    # =========================================================================
    # EVENT BRIDGES
    # =========================================================================

    # Lifecycle events (always)
    rem.watch_lifecycle(
        status,
        started_name="logs.started",
        completed_name="logs.completed",
        is_started=lambda s: s == "streaming",
        is_completed=lambda s: s in ("completed", "error"),
        to_started_data=lambda s: {
            "max_visible": max_visible,
            "record_all": config.record_all,
            "level_filter": list(config.level_filter) if config.level_filter else None,
        },
        to_completed_data=lambda s: {
            "status": s,
            "total_lines": total_count(),
            "visible_lines": visible_count(),
            "unique_sources": len(source_colors()),
        },
    )

    # Notable errors (always - good for alerting, checks unfiltered lines)
    rem.watch_notable(
        lambda: [l for l in lines()[-10:] if l.level == "error"],
        "logs.recent_errors",
        is_notable=lambda lst: len(lst) > 0,
        to_data=lambda lst: {"count": len(lst), "messages": [l.message[:50] for l in lst]},
        level="warn",
    )

    # =========================================================================
    # PER-LINE EVENT EMISSION (conditional on record mode)
    # =========================================================================

    # Optional: separate unfiltered file emitter
    unfiltered_emitter: FileEmitter | None = None
    if config.unfiltered_path:
        unfiltered_emitter = FileEmitter(config.unfiltered_path)
        unfiltered_emitter.__enter__()

    def on_line(log_line: LogLine) -> None:
        """Emit event for each line when recording."""
        if not config.record_all:
            return

        event = Event.log(
            log_line.message,
            level=log_line.level or "info",
            raw=log_line.raw,
            source=log_line.source,
            log_level=log_line.level,
            index=log_line.index,
        )

        # Always write to unfiltered if configured
        if unfiltered_emitter:
            unfiltered_emitter.emit(event)

        # Only emit to main emitter if passes filter
        if config.level_filter and (log_line.level or "info") not in config.level_filter:
            return
        rem.emit(event)

    # =========================================================================
    # EXECUTION
    # =========================================================================

    status.set("streaming")

    try:
        await mock_log_stream(
            lines, source_colors,
            on_line=on_line if config.record_all else None,
            num_lines=num_lines,
            delay_range=(0.02, 0.1),
        )
        status.set("completed")
    except Exception as e:
        status.set("error")
        return Result.error(f"Stream error: {e}", data={"error": str(e)})
    finally:
        if unfiltered_emitter:
            unfiltered_emitter.__exit__(None, None, None)

    # Build summary
    if config.level_filter:
        summary = f"Streamed {visible_count()}/{total_count()} log lines (filtered)"
    else:
        summary = f"Streamed {total_count()} log lines"

    return Result.ok(
        summary,
        data={
            "total_lines": total_count(),
            "visible_lines": visible_count(),
            "unique_sources": len(source_colors()),
            "sources": list(source_colors().keys()),
            "level_filter": list(config.level_filter) if config.level_filter else None,
        },
    )


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reactive logs viewer demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                              # UI mode, no recording
  %(prog)s --record out.jsonl           # UI + record all to file
  %(prog)s --level error,warn           # UI shows only errors/warnings
  %(prog)s --no-ui --level error        # Headless, errors only (for LLM)
  %(prog)s --record all.jsonl --record-unfiltered unfiltered.jsonl --level error
                                        # UI shows errors, record filtered + unfiltered
""",
    )
    parser.add_argument("--record", type=Path, metavar="PATH",
                        help="Record events to JSONL (respects --level filter)")
    parser.add_argument("--record-unfiltered", type=Path, metavar="PATH",
                        help="Record ALL events to JSONL (ignores --level filter)")
    parser.add_argument("--level", type=str, metavar="LEVELS",
                        help="Filter UI and --record by level (comma-separated: error,warn,info,debug)")
    parser.add_argument("--no-ui", action="store_true",
                        help="Disable UI (events only, for LLM tailing)")
    parser.add_argument("--lines", type=int, default=50,
                        help="Number of mock lines to generate")
    return parser.parse_args()


def build_emitter(args: argparse.Namespace) -> tuple[Emitter, OutputConfig, ListEmitter]:
    """
    Build emitter chain based on CLI flags.

    Supports simultaneous outputs:
    - ListEmitter: always (for inspection)
    - FileEmitter (--record): respects level filter
    - FileEmitter (--record-unfiltered): ignores level filter
    """

    # Parse level filter
    level_filter = None
    if args.level:
        level_filter = {l.strip().lower() for l in args.level.split(",")}

    config = OutputConfig(
        show_ui=not args.no_ui,
        record_all=args.record is not None or args.record_unfiltered is not None or args.no_ui,
        level_filter=level_filter,
    )

    # Base emitter for inspection
    base = ListEmitter()
    emitters: list[Emitter] = [base]

    # Filtered recording (respects --level)
    if args.record:
        emitters.append(FileEmitter(args.record))

    # Unfiltered recording (ignores --level, but we handle this specially)
    # For unfiltered, we need to emit ALL lines regardless of filter
    # This requires a separate path - we'll handle it in the operation
    if args.record_unfiltered:
        # Mark that we need unfiltered recording
        config.unfiltered_path = args.record_unfiltered

    emitter = TeeEmitter(*emitters) if len(emitters) > 1 else base

    return emitter, config, base


def main():
    args = parse_args()

    if not args.no_ui:
        print("\n" + "=" * 60)
        print("REACTIVE LOGS VIEWER DEMO")
        print("=" * 60)
        if args.record:
            print(f"\nRecording (filtered) to: {args.record}")
        if args.record_unfiltered:
            print(f"Recording (all) to: {args.record_unfiltered}")
        if args.level:
            print(f"Level filter: {args.level}")
        print()

    emitter, config, base_emitter = build_emitter(args)
    console = Console(stderr=True)

    async def run():
        rem = ReactiveEmitter(emitter, console=console)
        with rem:
            result = await logs_operation_reactive(
                rem, config,
                max_visible=20,
                num_lines=args.lines,
            )
        return result

    result = asyncio.run(run())
    emitter.finish(result)

    # Show results
    console.print()
    style = "green" if result.is_ok else "red"
    console.print(f"[{style}]{result.summary}[/{style}]")

    console.print(f"\n[bold]Captured Events ({len(base_emitter.events)}):[/bold]")

    # Show summary by type
    by_signal = {}
    log_count = 0
    for e in base_emitter.events:
        if e.is_signal:
            by_signal[e.signal_name] = by_signal.get(e.signal_name, 0) + 1
        else:
            log_count += 1

    if log_count:
        console.print(f"  [dim]log lines: {log_count}[/dim]")
    for name, count in sorted(by_signal.items()):
        console.print(f"  [dim]{name}: {count}[/dim]")

    if args.record:
        console.print(f"\n[dim]Recorded (filtered) to: {args.record}[/dim]")
    if args.record_unfiltered:
        console.print(f"[dim]Recorded (all) to: {args.record_unfiltered}[/dim]")

    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
