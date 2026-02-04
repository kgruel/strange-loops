"""Media lens — zoom-based rendering for media audit results.

Zoom controls progressive enhancement:
- MINIMAL (0): one-liner summary "[3 corrupt] media files"
- SUMMARY (1): table with key columns
- DETAILED (2): full table with all columns
- FULL (3): full table with deep scan results
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cells import Block, Style, Zoom, join_vertical, border, ROUNDED

from ..theme import Theme, DEFAULT_THEME
from ..radarr import format_size


@dataclass(frozen=True)
class DeepScanResult:
    """Results from deep file validation."""

    decode_test_passed: bool | None = None
    last_decodable_pct: float | None = None
    error_message: str | None = None


@dataclass
class AuditResult:
    """Result of auditing a single movie file."""

    movie_id: int
    title: str
    year: int | None
    quality: str
    runtime_seconds: int | None
    actual_size_bytes: int
    expected_min_bytes: int | None
    size_ratio: float | None  # actual / expected_min
    status: Literal["ok", "suspicious", "unknown", "corrupt", "truncated"]
    reason: str | None = None
    file_path: str | None = None
    deep_scan: DeepScanResult | None = None


@dataclass(frozen=True)
class AuditData:
    """Complete audit data for rendering."""

    results: list[AuditResult]
    show_all: bool = False
    deep_scan_enabled: bool = False


def media_audit_view(
    data: AuditData,
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render media audit results at zoom level.

    Args:
        data: AuditData with audit results
        zoom: MINIMAL=one-liner, SUMMARY=table, DETAILED/FULL=full table
        width: Available terminal width
        theme: Theme instance for icons/colors

    Returns:
        Block ready for print_block()
    """
    if zoom == Zoom.MINIMAL:
        return _render_oneliner(data, width, theme)

    if zoom == Zoom.SUMMARY:
        return _render_table(data, width, theme, compact=True)

    # DETAILED or FULL: full table
    return _render_bordered_table(data, width, theme, show_deep=(zoom == Zoom.FULL))


def _render_oneliner(data: AuditData, width: int, theme: Theme) -> Block:
    """MINIMAL: Single line summary."""
    total = len(data.results)
    suspicious = sum(1 for r in data.results if r.status == "suspicious")
    corrupt = sum(1 for r in data.results if r.status in ("corrupt", "truncated"))

    if corrupt > 0:
        icon = theme.icons.unhealthy
        style = Style(fg=theme.colors.error)
        text = f"{icon} [{corrupt} corrupt] media files ({total} total)"
    elif suspicious > 0:
        icon = theme.icons.unhealthy
        style = Style(fg="yellow")
        text = f"{icon} [{suspicious} suspicious] media files ({total} total)"
    else:
        icon = theme.icons.healthy
        style = Style(fg=theme.colors.success)
        text = f"{icon} All {total} media files OK"

    return Block.text(text, style, width=width)


def _status_style(status: str, theme: Theme) -> Style:
    """Get style for a status value."""
    if status in ("corrupt", "truncated"):
        return Style(fg=theme.colors.error, bold=True)
    elif status == "suspicious":
        return Style(fg="yellow")
    elif status == "ok":
        return Style(fg=theme.colors.success)
    else:
        return Style(dim=True)


def _render_table(
    data: AuditData,
    width: int,
    theme: Theme,
    *,
    compact: bool = False,
) -> Block:
    """SUMMARY: Table view of results."""
    # Filter to show only interesting results unless show_all
    results = data.results
    if not data.show_all:
        results = [r for r in results if r.status != "ok"]

    if not results:
        return Block.text(f"{theme.icons.healthy} No issues found", Style(fg=theme.colors.success), width=width)

    rows: list[Block] = []

    # Header
    header = "Title                           Quality      Size     Ratio  Status"
    rows.append(Block.text(header, Style(bold=True, dim=True), width=width))

    # Sort by ratio (lowest first for suspicious)
    sorted_results = sorted(results, key=lambda r: r.size_ratio or 999)

    for r in sorted_results[:20]:  # Limit to 20 rows in compact mode
        title = r.title[:28].ljust(28) if len(r.title) > 28 else r.title.ljust(28)
        quality = r.quality[:10].ljust(10) if len(r.quality) > 10 else r.quality.ljust(10)
        size = format_size(r.actual_size_bytes).rjust(8)
        ratio = f"{r.size_ratio:.0%}".rjust(6) if r.size_ratio else "?".rjust(6)

        status_text = r.status.upper()
        if r.deep_scan and r.deep_scan.decode_test_passed and r.status == "suspicious":
            status_text = "MISLABEL"

        line = f"{title}  {quality}  {size}  {ratio}  {status_text}"
        style = _status_style(r.status, theme)
        rows.append(Block.text(line, style, width=width))

    if len(sorted_results) > 20:
        rows.append(Block.text(f"  ... and {len(sorted_results) - 20} more", Style(dim=True), width=width))

    return join_vertical(*rows)


def _render_bordered_table(
    data: AuditData,
    width: int,
    theme: Theme,
    *,
    show_deep: bool = False,
) -> Block:
    """DETAILED/FULL: Bordered table with complete details."""
    inner_width = width - 4

    results = data.results
    if not data.show_all:
        results = [r for r in results if r.status != "ok"]

    if not results:
        content = Block.text(f"{theme.icons.healthy} No issues found", Style(fg=theme.colors.success), width=inner_width)
        return border(content, title="Media Audit", style=Style(fg=theme.colors.accent), chars=ROUNDED)

    rows: list[Block] = []

    # Header
    if show_deep and data.deep_scan_enabled:
        header = "Title                       Quality    Actual    Expected  Ratio   Status    Deep"
    else:
        header = "Title                       Quality    Actual    Expected  Ratio   Status"
    rows.append(Block.text(header, Style(bold=True, dim=True), width=inner_width))

    # Sort by status priority, then ratio
    def sort_key(r: AuditResult) -> tuple[int, float]:
        status_order = {"truncated": 0, "corrupt": 1, "suspicious": 2, "unknown": 3, "ok": 4}
        return (status_order.get(r.status, 5), r.size_ratio or 999)

    sorted_results = sorted(results, key=sort_key)

    for r in sorted_results:
        title = r.title[:24].ljust(24) if len(r.title) > 24 else r.title.ljust(24)
        quality = r.quality[:8].ljust(8) if len(r.quality) > 8 else r.quality.ljust(8)
        actual = format_size(r.actual_size_bytes).rjust(8)
        expected = format_size(r.expected_min_bytes).rjust(8) if r.expected_min_bytes else "?".rjust(8)
        ratio = f"{r.size_ratio:.0%}".rjust(6) if r.size_ratio else "?".rjust(6)

        status_text = r.status.upper()[:8].ljust(8)
        if r.deep_scan and r.deep_scan.decode_test_passed and r.status == "suspicious":
            status_text = "MISLABEL"

        line = f"{title}  {quality}  {actual}  {expected}  {ratio}  {status_text}"

        if show_deep and data.deep_scan_enabled:
            if r.deep_scan:
                if r.deep_scan.decode_test_passed:
                    deep = "PASS"
                else:
                    pct = r.deep_scan.last_decodable_pct or 0
                    deep = f"FAIL@{pct:.0%}"
                line += f"  {deep}"
            else:
                line += "  -"

        style = _status_style(r.status, theme)
        rows.append(Block.text(line, style, width=inner_width))

    # Summary
    rows.append(Block.empty(inner_width, 1))
    suspicious = sum(1 for r in data.results if r.status == "suspicious")
    corrupt = sum(1 for r in data.results if r.status in ("corrupt", "truncated"))
    mislabeled = sum(1 for r in data.results if r.deep_scan and r.deep_scan.decode_test_passed and r.status == "suspicious")

    summary_parts = [f"{len(data.results)} files scanned"]
    if corrupt:
        summary_parts.append(f"{corrupt} corrupt/truncated")
    if mislabeled:
        summary_parts.append(f"{mislabeled} mislabeled")
    elif suspicious:
        summary_parts.append(f"{suspicious} suspicious")

    summary = " | ".join(summary_parts)
    rows.append(Block.text(summary, Style(bold=True), width=inner_width))

    content = join_vertical(*rows)

    if corrupt:
        title = f"Media Audit ({corrupt} corrupt)"
        title_style = Style(fg=theme.colors.error)
    elif suspicious:
        title = f"Media Audit ({suspicious} suspicious)"
        title_style = Style(fg="yellow")
    else:
        title = "Media Audit"
        title_style = Style(fg=theme.colors.accent)

    return border(content, title=title, style=title_style, chars=ROUNDED)


def render_plain(data: AuditData, theme: Theme = DEFAULT_THEME) -> str:
    """Render audit results as plain text for non-TTY output."""
    lines: list[str] = ["Media Audit", ""]

    results = data.results
    if not data.show_all:
        results = [r for r in results if r.status != "ok"]

    if not results:
        lines.append(f"{theme.icons.healthy} No issues found")
    else:
        for r in sorted(results, key=lambda x: x.size_ratio or 999):
            ratio = f"{r.size_ratio:.0%}" if r.size_ratio else "?"
            lines.append(f"  [{r.status.upper()}] {r.title} ({r.year}) - {r.quality} - {ratio}")

    lines.append("")
    lines.append(f"Total: {len(data.results)} files")

    return "\n".join(lines)
