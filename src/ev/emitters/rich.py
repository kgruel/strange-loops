"""Rich emitter for beautiful terminal output.

Requires the 'rich' package: pip install ev[rich]
"""

import sys

from rich.console import Console

from ev.types import Event, Result

# Level to Rich style mapping
LEVEL_STYLES = {
    "debug": "dim",
    "info": "",
    "warn": "yellow",
    "error": "red bold",
}


class RichEmitter:
    """Emitter that outputs styled text using Rich.

    Thin v1 implementation: just styled text, no live widgets.
    Outputs to stderr by default (stdout reserved for structured result).
    """

    def __init__(self, console: Console | None = None) -> None:
        if console is None:
            console = Console(file=sys.stderr)
        self._console = console

    def emit(self, event: Event) -> None:
        """Render event to console."""
        if event.kind == "log":
            self._render_log(event)
        elif event.kind == "progress":
            self._render_progress(event)
        elif event.kind == "artifact":
            self._render_artifact(event)
        elif event.kind == "metric":
            self._render_metric(event)
        elif event.kind == "input":
            self._render_input(event)
        else:  # pragma: no cover
            pass

    def finish(self, result: Result) -> None:
        """Render final result."""
        icon = "[green]✓[/green]" if result.status == "ok" else "[red]✗[/red]"

        if result.summary:
            self._console.print(f"{icon} {result.summary}")
        else:
            status_text = "OK" if result.status == "ok" else "ERROR"
            self._console.print(f"{icon} {status_text}")

    def _render_log(self, event: Event) -> None:
        """Render a log event."""
        style = LEVEL_STYLES.get(event.level, "")
        message = event.message or ""

        if event.level in ("warn", "error"):
            prefix = f"[{style}]{event.level.upper()}:[/{style}] "
            self._console.print(f"{prefix}{message}")
        elif style:
            self._console.print(f"[{style}]{message}[/{style}]")
        else:
            self._console.print(message)

    def _render_progress(self, event: Event) -> None:
        """Render a progress event."""
        data = event.data
        message = event.message or ""

        if "step" in data and "of" in data:
            step_info = f"[dim][{data['step']}/{data['of']}][/dim]"
            if message:
                self._console.print(f"{step_info} {message}")
            else:
                self._console.print(step_info)
        elif "percent" in data:
            pct = data["percent"]
            if message:
                self._console.print(f"[dim][{pct}%][/dim] {message}")
            else:
                self._console.print(f"[dim][{pct}%][/dim]")
        elif message:
            self._console.print(f"[dim]...[/dim] {message}")

    def _render_artifact(self, event: Event) -> None:
        """Render an artifact event."""
        data = event.data
        location = data.get("path") or data.get("href") or data.get("url") or data.get("id", "")
        label = event.message or "Created"
        self._console.print(f"[cyan]📄[/cyan] {label}: [bold]{location}[/bold]")

    def _render_metric(self, event: Event) -> None:
        """Render a metric event."""
        data = event.data
        name = data.get("name", "metric")
        value = data.get("value", "")
        unit = data.get("unit", "")

        if unit:
            self._console.print(f"[dim]{name}:[/dim] [bold]{value}[/bold] {unit}")
        else:
            self._console.print(f"[dim]{name}:[/dim] [bold]{value}[/bold]")

    def _render_input(self, event: Event) -> None:
        """Render an input event."""
        question = event.message or "Input"
        response = event.data.get("response", "")
        self._console.print(f"[yellow]?[/yellow] {question} → [bold]{response}[/bold]")
