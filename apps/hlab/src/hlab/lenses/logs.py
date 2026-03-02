"""Logs lens — rendering for streaming log output.

Logs don't follow the same zoom pattern as other views since they're
streaming data. This module provides log line parsing and formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from painted import Block, Style, Span, Line

from ..theme import Theme, DEFAULT_THEME


# Level detection patterns
_LEVEL_PATTERNS = [
    (re.compile(r"\[ERROR\]", re.IGNORECASE), "error"),
    (re.compile(r"\[WARN(?:ING)?\]", re.IGNORECASE), "warn"),
    (re.compile(r"\[INFO\]", re.IGNORECASE), "info"),
    (re.compile(r"\[DEBUG\]", re.IGNORECASE), "debug"),
    (re.compile(r"\[TRACE\]", re.IGNORECASE), "trace"),
    # Key=value formats: level=error, level="error"
    (re.compile(r'\blevel[=:]\s*"?error"?', re.IGNORECASE), "error"),
    (re.compile(r'\blevel[=:]\s*"?warn(?:ing)?"?', re.IGNORECASE), "warn"),
    (re.compile(r'\blevel[=:]\s*"?info"?', re.IGNORECASE), "info"),
    (re.compile(r'\blevel[=:]\s*"?debug"?', re.IGNORECASE), "debug"),
    # JSON formats: "level":"error"
    (re.compile(r'"level"\s*:\s*"error"', re.IGNORECASE), "error"),
    (re.compile(r'"level"\s*:\s*"warn(?:ing)?"', re.IGNORECASE), "warn"),
    (re.compile(r'"level"\s*:\s*"info"', re.IGNORECASE), "info"),
    (re.compile(r'"level"\s*:\s*"debug"', re.IGNORECASE), "debug"),
    # Standalone keywords (more specific patterns to avoid false positives)
    (re.compile(r"\bERROR\b"), "error"),
    (re.compile(r"\bWARNING\b"), "warn"),
    (re.compile(r"\bFATAL\b", re.IGNORECASE), "error"),
    (re.compile(r"\bCRITICAL\b", re.IGNORECASE), "error"),
]

# Colors for source names (hash-based assignment)
_SOURCE_COLORS = [
    "cyan",
    "green",
    "yellow",
    "blue",
    "magenta",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_blue",
]


def detect_level(message: str) -> str | None:
    """Detect log level from message content."""
    for pattern, level in _LEVEL_PATTERNS:
        if pattern.search(message):
            return level
    return None


@dataclass(frozen=True)
class LogLine:
    """A parsed log line."""

    message: str
    raw: str | None = None
    source: str | None = None  # Container/service name
    level: str | None = None  # error, warn, info, debug, trace
    timestamp: datetime | None = None
    data: dict[str, Any] = field(default_factory=dict)


def parse_compose_log_line(line: str, *, detect_level_: bool = True) -> LogLine:
    """Parse a docker compose log line.

    Docker compose logs format: "container_name | message"
    """
    if " | " in line:
        source, message = line.split(" | ", 1)
        lvl = detect_level(message) if detect_level_ else None
        return LogLine(raw=line, source=source.strip(), message=message, level=lvl)
    lvl = detect_level(line) if detect_level_ else None
    return LogLine(raw=line, source=None, message=line, level=lvl)


def _hash_color(value: str) -> str:
    """Get a consistent color for a source name."""
    return _SOURCE_COLORS[hash(value) % len(_SOURCE_COLORS)]


@dataclass(frozen=True)
class LogLineConfig:
    """Configuration for log line rendering."""

    show_source: bool = True
    source_width: int = 15
    separator: str = " | "


@dataclass
class RenderState:
    """Mutable state for rendering (color assignments)."""

    source_colors: dict[str, str] = field(default_factory=dict)


def render_log_line(
    log: LogLine,
    theme: Theme,
    config: LogLineConfig,
    state: RenderState,
    width: int,
) -> Block:
    """Render a single log line as a Block.

    Args:
        log: Parsed log line
        theme: Theme for colors
        config: Rendering configuration
        state: Mutable render state (for color assignment)
        width: Available width

    Returns:
        Block containing the formatted log line
    """
    spans: list[Span] = []

    # Source prefix
    if config.show_source and log.source:
        color = state.source_colors.get(log.source)
        if color is None:
            color = _hash_color(log.source)
            state.source_colors[log.source] = color

        source_text = log.source[:config.source_width].ljust(config.source_width)
        spans.append(Span(source_text, Style(fg=color)))
        spans.append(Span(config.separator, Style(dim=True)))

    # Message with level-based styling
    msg_style: Style | None = None
    if log.level == "error":
        msg_style = Style(fg=theme.colors.error)
    elif log.level == "warn":
        msg_style = Style(fg="yellow")
    elif log.level in ("debug", "trace"):
        msg_style = Style(dim=True)

    if msg_style:
        spans.append(Span(log.message, msg_style))
    else:
        spans.append(Span(log.message))

    line = Line(tuple(spans))
    return line.to_block(width)


def render_log_line_plain(log: LogLine, config: LogLineConfig) -> str:
    """Render a log line as plain text (no ANSI codes)."""
    if config.show_source and log.source:
        source = log.source[:config.source_width].ljust(config.source_width)
        return f"{source}{config.separator}{log.message}"
    return log.message


@dataclass(frozen=True)
class LogFilter:
    """Filter criteria for log lines."""

    levels: frozenset[str] | None = None  # None = all levels
    source: str | None = None  # Substring match
    grep: str | None = None  # Substring match in message

    def matches(self, log: LogLine) -> bool:
        """Check if a log line matches the filter."""
        if self.levels is not None:
            lvl = (log.level or "info").lower()
            if lvl == "warning":
                lvl = "warn"
            if lvl not in self.levels:
                return False

        if self.source is not None:
            if self.source not in (log.source or ""):
                return False

        if self.grep is not None:
            if self.grep not in log.message:
                return False

        return True


def build_filter(
    levels: str | None = None,
    source: str | None = None,
    grep: str | None = None,
) -> LogFilter | None:
    """Build a LogFilter from CLI arguments.

    Args:
        levels: Comma-separated list of levels (error,warn,info,debug,trace)
        source: Source substring to match
        grep: Message substring to match

    Returns:
        LogFilter or None if no filtering needed
    """
    level_set: frozenset[str] | None = None
    if levels:
        raw_levels = {lvl.strip().lower() for lvl in levels.split(",") if lvl.strip()}
        # Accept common aliases
        level_set = frozenset(("warn" if lvl == "warning" else lvl) for lvl in raw_levels)

    if not level_set and not source and not grep:
        return None

    return LogFilter(levels=level_set, source=source, grep=grep)
