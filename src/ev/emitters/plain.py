"""Plain text emitter for minimal output."""

import sys
from typing import TextIO

from ev.types import Event, Result


class PlainEmitter:
    """Emitter that outputs plain text to stderr.

    Minimal, line-oriented output suitable for pipes and dumb terminals.

    Options:
        show_level: Prefix log events with [LEVEL] (default: True)
        show_timestamp: Prefix events with timestamp (default: False)
    """

    def __init__(
        self,
        file: TextIO = sys.stderr,
        show_level: bool = True,
        show_timestamp: bool = False,
    ) -> None:
        self._file = file
        self._show_level = show_level
        self._show_timestamp = show_timestamp

    def emit(self, event: Event) -> None:
        """Format and print event."""
        line = self._format_event(event)
        if line:
            self._file.write(line + "\n")
            self._file.flush()

    def finish(self, result: Result) -> None:
        """Print result summary."""
        status = "OK" if result.status == "ok" else "ERROR"
        if result.summary:
            self._file.write(f"{status}: {result.summary}\n")
        else:
            self._file.write(f"{status}\n")
        self._file.flush()

    def _format_event(self, event: Event) -> str:
        """Format a single event as a string."""
        prefix = ""

        if self._show_timestamp and event.ts is not None:
            prefix = f"[{event.ts:.3f}] "

        if event.kind == "log":
            return self._format_log(event, prefix)
        elif event.kind == "progress":
            return self._format_progress(event, prefix)
        elif event.kind == "artifact":
            return self._format_artifact(event, prefix)
        elif event.kind == "metric":
            return self._format_metric(event, prefix)
        elif event.kind == "input":
            return self._format_input(event, prefix)
        else:  # pragma: no cover
            return ""

    def _format_log(self, event: Event, prefix: str) -> str:
        """Format a log event."""
        if self._show_level:
            level = event.level.upper()
            return f"{prefix}[{level}] {event.message}"
        return f"{prefix}{event.message}"

    def _format_progress(self, event: Event, prefix: str) -> str:
        """Format a progress event."""
        data = event.data

        if "step" in data and "of" in data:
            step_info = f"[{data['step']}/{data['of']}]"
            if event.message:
                return f"{prefix}{step_info} {event.message}"
            return f"{prefix}{step_info}"

        if "percent" in data:
            pct = data["percent"]
            if event.message:
                return f"{prefix}[{pct}%] {event.message}"
            return f"{prefix}[{pct}%]"

        if event.message:
            return f"{prefix}{event.message}"

        return ""

    def _format_artifact(self, event: Event, prefix: str) -> str:
        """Format an artifact event."""
        data = event.data
        location = data.get("path") or data.get("href") or data.get("url") or data.get("id", "")
        label = event.message or "Created"
        return f"{prefix}{label}: {location}"

    def _format_metric(self, event: Event, prefix: str) -> str:
        """Format a metric event."""
        data = event.data
        name = data.get("name", "metric")
        value = data.get("value", "")
        unit = data.get("unit", "")

        if unit:
            return f"{prefix}{name}: {value} {unit}"
        return f"{prefix}{name}: {value}"

    def _format_input(self, event: Event, prefix: str) -> str:
        """Format an input event."""
        question = event.message or "Input"
        response = event.data.get("response", "")
        return f"{prefix}{question} → {response}"
