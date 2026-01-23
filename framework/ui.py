"""Reusable render helpers: pure functions returning Rich renderables.

No widget classes, no DSL, no hidden state. Each function takes data in,
returns a Rich renderable out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


# =============================================================================
# DATA TYPES
# =============================================================================


@dataclass(frozen=True)
class ColumnSpec:
    """Column definition for event_table."""
    name: str
    style: str | None = None
    justify: str | None = None
    width: int | None = None
    ratio: int | None = None
    no_wrap: bool = True


@dataclass(frozen=True)
class ScrollInfo:
    """Scroll position info returned by event_table."""
    above_count: int
    below_count: int

    @property
    def subtitle(self) -> str | None:
        """Format as panel subtitle string, or None if no scrolling."""
        parts = []
        if self.above_count > 0:
            parts.append(f"↑ {self.above_count} more")
        if self.below_count > 0:
            parts.append(f"↓ {self.below_count} more")
        return "  ".join(parts) if parts else None


# =============================================================================
# RENDER HELPERS
# =============================================================================


def app_layout(
    main_content: Any,
    status: Text,
    help: Text,
) -> Layout:
    """Create the standard 3-row app layout (main expands, status+help fixed 1 line each)."""
    layout = Layout()
    layout.split_column(
        Layout(main_content, name="main", ratio=1),
        Layout(status, name="status", size=1),
        Layout(help, name="help", size=1),
    )
    return layout


def focus_panel(
    content: Any,
    title: str,
    focused: bool,
    subtitle: str | None = None,
) -> Panel:
    """Wrap content in a Panel with green border if focused, dim otherwise."""
    border_style = "green" if focused else "dim"
    return Panel(
        content,
        title=title,
        subtitle=subtitle,
        border_style=border_style,
    )


def event_table(
    rows: list[list[str | Text]],
    columns: list[ColumnSpec],
    max_rows: int,
    selected_idx: int | None = None,
    show_scroll: bool = True,
    show_header: bool = True,
) -> tuple[Table, ScrollInfo]:
    """Build a table with optional selection and scroll tracking.

    Args:
        rows: List of row data. Each row is a list of cell values (str or Text).
        columns: Column specifications.
        max_rows: Maximum visible rows (terminal-aware).
        selected_idx: Which row index (in the full rows list) gets ▶ and reverse styling.
        show_scroll: Whether to compute scroll indicators.
        show_header: Whether to show column headers.

    Returns:
        (Table, ScrollInfo) — the table renderable and scroll position info.
    """
    table = Table(
        show_header=show_header,
        header_style="bold",
        expand=True,
        box=None,
        padding=(0, 1),
    )

    # Selection indicator column (always first when selection is enabled)
    has_selection = selected_idx is not None
    if has_selection:
        table.add_column("", no_wrap=True, width=1)

    # User-defined columns
    for col in columns:
        table.add_column(
            col.name,
            style=col.style,
            justify=col.justify,
            no_wrap=col.no_wrap,
            width=col.width,
            ratio=col.ratio,
        )

    # Calculate visible window (scroll-to-selection)
    total = len(rows)
    start_idx = max(0, total - max_rows)
    if selected_idx is not None:
        if selected_idx < start_idx:
            start_idx = selected_idx
        if selected_idx >= start_idx + max_rows:
            start_idx = selected_idx - max_rows + 1
    end_idx = min(total, start_idx + max_rows)

    above_count = start_idx
    below_count = total - end_idx

    # Render visible rows
    for i in range(start_idx, end_idx):
        row_data = rows[i]
        is_selected = (i == selected_idx)

        cells: list[str | Text] = []
        if has_selection:
            indicator = "▶" if is_selected else ""
            cells.append(Text(indicator, style="cyan bold"))

        for cell in row_data:
            if is_selected:
                # Apply reverse to selected row cells
                if isinstance(cell, Text):
                    # Clone with reverse added to style
                    style = str(cell.style) if cell.style else ""
                    rev_style = f"{style} reverse".strip()
                    cells.append(Text(cell.plain, style=rev_style))
                else:
                    cells.append(Text(str(cell), style="reverse"))
            else:
                cells.append(cell)

        table.add_row(*cells)

    scroll = ScrollInfo(above_count, below_count) if show_scroll else ScrollInfo(0, 0)
    return table, scroll


def metrics_panel(
    sections: list[tuple[str, list[tuple[str, str] | tuple[str, str, str]]]],
) -> Text:
    """Build metrics text from sections.

    Args:
        sections: List of (header, entries). Each entry is (name, value) or
                  (name, value, style) where style wraps the value in markup.

    Returns:
        Text renderable with formatted metrics.
    """
    lines: list[str] = []
    for i, (header, entries) in enumerate(sections):
        if i > 0:
            lines.append("")
        lines.append(f"[bold underline]{header}[/bold underline]")
        for entry in entries:
            if len(entry) == 3:
                name, value, style = entry
                lines.append(f"  {name}: [{style}]{value}[/{style}]")
            else:
                name, value = entry
                lines.append(f"  {name}: {value}")

    return Text.from_markup("\n".join(lines))


def help_bar(bindings: list[tuple[str, str]], separator: str = "  ") -> Text:
    """Format key bindings as a help bar.

    Args:
        bindings: List of (key, action) pairs. Use "|" as key for a group separator.

    Returns:
        Formatted Text with dim keys and plain actions.
    """
    parts: list[str] = []
    for key, action in bindings:
        if key == "|":
            parts.append("|")
        else:
            parts.append(f"[dim]{key}[/dim]={action}")
    return Text.from_markup(separator.join(parts))


def status_parts(*parts: str | None) -> Text:
    """Join non-None markup parts with separators into a status bar.

    Each part is a Rich markup string. None parts are skipped.
    Parts are joined with "  " (double space).
    """
    valid = [p for p in parts if p is not None]
    return Text.from_markup("  ".join(valid))


# =============================================================================
# TEXT-BASED VISUALIZATIONS
# =============================================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int = 10,
              max_value: float | None = None) -> str:
    """Render a list of floats as a sparkline string.

    Args:
        values: Data points to visualize.
        width: Number of characters in the output.
        max_value: Optional ceiling for normalization (auto-scaled if None).

    Returns:
        String of sparkline characters, left-padded to `width`.
    """
    if not values:
        return " " * width
    recent = values[-width:]
    lo = min(recent)
    hi = max_value if max_value is not None else max(recent)
    span = hi - lo if hi > lo else 1.0
    chars = []
    for v in recent:
        clamped = min(v, hi)
        idx = int((clamped - lo) / span * (len(_SPARK_CHARS) - 1))
        chars.append(_SPARK_CHARS[idx])
    return "".join(chars).ljust(width)


def compact_bar(value: float, max_value: float, width: int = 10) -> str:
    """Render a value as a compact horizontal bar.

    Args:
        value: Current value.
        max_value: Value that fills the full bar.
        width: Character width of the bar.

    Returns:
        String like "████░░░░░░" representing the proportion.
    """
    if max_value <= 0:
        return "░" * width
    fraction = min(value / max_value, 1.0)
    filled = int(fraction * width)
    return "█" * filled + "░" * (width - filled)
