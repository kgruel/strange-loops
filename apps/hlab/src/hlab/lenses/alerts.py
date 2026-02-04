"""Alerts lens — zoom-based rendering for Prometheus alerts.

Zoom controls progressive enhancement:
- MINIMAL (0): one-liner summary "[3 firing] alerts"
- SUMMARY (1): tree with alert names
- DETAILED (2): bordered tree with labels/annotations
- FULL (3): full detail with all metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cells import Block, Style, Zoom, join_vertical, border, ROUNDED

from ..theme import Theme, DEFAULT_THEME


@dataclass(frozen=True)
class FiringAlert:
    """A currently firing alert from Prometheus."""

    alertname: str
    state: str
    severity: str | None = None
    instance: str | None = None
    summary: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    active_at: str | None = None


@dataclass(frozen=True)
class AlertRule:
    """An alert rule from Prometheus."""

    name: str
    state: str  # firing, pending, inactive
    group: str
    health: str  # ok, err, unknown
    alerts_count: int = 0
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TargetHealth:
    """Prometheus scrape target health."""

    job: str
    instance: str
    health: str  # up, down, unknown
    scrape_url: str | None = None
    last_error: str | None = None
    last_scrape: str | None = None


@dataclass(frozen=True)
class AlertsData:
    """Complete alerts data for rendering."""

    firing_alerts: list[FiringAlert] = field(default_factory=list)
    alert_rules: list[AlertRule] = field(default_factory=list)
    targets: list[TargetHealth] = field(default_factory=list)
    show_targets: bool = False


def alerts_view(
    data: AlertsData,
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render alerts at zoom level.

    Args:
        data: AlertsData with firing alerts, rules, and optionally targets
        zoom: MINIMAL=one-liner, SUMMARY=tree, DETAILED/FULL=bordered tree
        width: Available terminal width
        theme: Theme instance for icons/colors

    Returns:
        Block ready for print_block()
    """
    if zoom == Zoom.MINIMAL:
        return _render_oneliner(data, width, theme)

    if zoom == Zoom.SUMMARY:
        return _render_tree(data, width, theme, show_details=False)

    # DETAILED or FULL: bordered tree with full details
    return _render_bordered_tree(data, width, theme, show_all=(zoom == Zoom.FULL))


def _render_oneliner(data: AlertsData, width: int, theme: Theme) -> Block:
    """MINIMAL: Single line summary."""
    firing_count = len(data.firing_alerts)
    rules_count = len(data.alert_rules)

    if firing_count == 0:
        icon = theme.icons.healthy
        style = Style(fg=theme.colors.success)
        text = f"{icon} No alerts firing ({rules_count} rules)"
    else:
        icon = theme.icons.unhealthy
        style = Style(fg=theme.colors.error)
        # Show severity breakdown
        critical = sum(1 for a in data.firing_alerts if a.severity == "critical")
        warning = sum(1 for a in data.firing_alerts if a.severity == "warning")
        parts = []
        if critical:
            parts.append(f"{critical} critical")
        if warning:
            parts.append(f"{warning} warning")
        if not parts:
            parts.append(f"{firing_count} firing")
        text = f"{icon} [{', '.join(parts)}] alerts"

    if data.show_targets:
        down = sum(1 for t in data.targets if t.health == "down")
        if down:
            text += f" | {down} targets down"

    return Block.text(text, style, width=width)


def _render_tree(
    data: AlertsData,
    width: int,
    theme: Theme,
    *,
    show_details: bool = False,
) -> Block:
    """SUMMARY: Tree view with alert names."""
    rows: list[Block] = []

    # Firing alerts section
    if data.firing_alerts:
        rows.append(Block.text("Firing Alerts", Style(fg=theme.colors.error, bold=True), width=width))
        for i, alert in enumerate(data.firing_alerts):
            is_last = i == len(data.firing_alerts) - 1
            branch = theme.icons.branch_last if is_last else theme.icons.branch

            # Severity styling
            sev_style = Style(fg=theme.colors.error) if alert.severity == "critical" else Style(
                fg="yellow" if alert.severity == "warning" else None
            )

            line = f"{branch} {theme.icons.unhealthy} {alert.alertname}"
            if alert.severity:
                line += f" [{alert.severity}]"
            if alert.instance:
                line += f" @ {alert.instance}"

            rows.append(Block.text(line, sev_style, width=width))

            if show_details and alert.summary:
                continuation = theme.icons.continuation_last if is_last else theme.icons.continuation
                rows.append(Block.text(f"{continuation}  {alert.summary}", Style(dim=True), width=width))
    else:
        rows.append(Block.text(
            f"{theme.icons.healthy} No firing alerts",
            Style(fg=theme.colors.success),
            width=width,
        ))

    rows.append(Block.empty(width, 1))

    # Alert rules by group
    if data.alert_rules:
        grouped: dict[str, list[AlertRule]] = {}
        for rule in data.alert_rules:
            grouped.setdefault(rule.group, []).append(rule)

        rows.append(Block.text("Alert Rules", Style(bold=True), width=width))
        group_names = sorted(grouped.keys())
        for i, group_name in enumerate(group_names):
            rules = grouped[group_name]
            is_last = i == len(group_names) - 1
            branch = theme.icons.branch_last if is_last else theme.icons.branch

            firing = sum(1 for r in rules if r.state == "firing")
            pending = sum(1 for r in rules if r.state == "pending")

            if firing:
                style = Style(fg=theme.colors.error)
            elif pending:
                style = Style(fg="yellow")
            else:
                style = Style(fg=theme.colors.success)

            line = f"{branch} {group_name}: {len(rules)} rules"
            if firing:
                line += f", {firing} firing"
            if pending:
                line += f", {pending} pending"

            rows.append(Block.text(line, style, width=width))

    # Targets section (if requested)
    if data.show_targets and data.targets:
        rows.append(Block.empty(width, 1))
        down = [t for t in data.targets if t.health == "down"]
        up = [t for t in data.targets if t.health == "up"]

        if down:
            rows.append(Block.text("Targets Down", Style(fg=theme.colors.error, bold=True), width=width))
            for i, target in enumerate(down):
                is_last = i == len(down) - 1
                branch = theme.icons.branch_last if is_last else theme.icons.branch
                line = f"{branch} {theme.icons.unhealthy} {target.job}/{target.instance}"
                rows.append(Block.text(line, Style(fg=theme.colors.error), width=width))
        else:
            rows.append(Block.text(
                f"{theme.icons.healthy} All {len(up)} targets up",
                Style(fg=theme.colors.success),
                width=width,
            ))

    return join_vertical(*rows)


def _render_bordered_tree(
    data: AlertsData,
    width: int,
    theme: Theme,
    *,
    show_all: bool = False,
) -> Block:
    """DETAILED/FULL: Bordered tree with complete details."""
    inner_width = width - 4
    rows: list[Block] = []

    # Firing alerts
    if data.firing_alerts:
        for i, alert in enumerate(data.firing_alerts):
            is_last = i == len(data.firing_alerts) - 1
            branch = theme.icons.branch_last if is_last else theme.icons.branch
            continuation = theme.icons.continuation_last if is_last else theme.icons.continuation

            sev_style = Style(fg=theme.colors.error) if alert.severity == "critical" else Style(
                fg="yellow" if alert.severity == "warning" else None
            )

            line = f"{branch} {theme.icons.unhealthy} {alert.alertname}"
            if alert.severity:
                line += f" [{alert.severity}]"
            if alert.instance:
                line += f" @ {alert.instance}"
            rows.append(Block.text(line, sev_style, width=inner_width))

            if alert.summary:
                rows.append(Block.text(f"{continuation}  {alert.summary}", Style(dim=True), width=inner_width))

            if show_all and alert.active_at:
                rows.append(Block.text(f"{continuation}  Active since: {alert.active_at}", Style(dim=True), width=inner_width))
    else:
        rows.append(Block.text(
            f"{theme.icons.healthy} No firing alerts",
            Style(fg=theme.colors.success),
            width=inner_width,
        ))

    rows.append(Block.empty(inner_width, 1))

    # Summary line
    firing_count = len(data.firing_alerts)
    rules_count = len(data.alert_rules)
    summary = f"Total: {firing_count} firing | {rules_count} rules monitored"

    if data.show_targets:
        up = sum(1 for t in data.targets if t.health == "up")
        down = sum(1 for t in data.targets if t.health == "down")
        summary += f" | {up}/{up + down} targets up"

    rows.append(Block.text(summary, Style(bold=True), width=inner_width))

    content = join_vertical(*rows)
    title = "Alerts" if not firing_count else f"Alerts ({firing_count} firing)"
    title_style = Style(fg=theme.colors.error) if firing_count else Style(fg=theme.colors.accent)
    return border(content, title=title, style=title_style, chars=ROUNDED)


def render_plain(data: AlertsData, theme: Theme = DEFAULT_THEME) -> str:
    """Render alerts as plain text for non-TTY output.

    No ANSI codes, simple structure suitable for piping.
    """
    lines: list[str] = ["Alerts", ""]

    if data.firing_alerts:
        lines.append("Firing:")
        for alert in data.firing_alerts:
            sev = f" [{alert.severity}]" if alert.severity else ""
            inst = f" @ {alert.instance}" if alert.instance else ""
            lines.append(f"  {theme.icons.unhealthy} {alert.alertname}{sev}{inst}")
    else:
        lines.append(f"{theme.icons.healthy} No firing alerts")

    lines.append("")
    lines.append(f"Rules: {len(data.alert_rules)} total")

    # Group summary
    grouped: dict[str, int] = {}
    for rule in data.alert_rules:
        grouped[rule.group] = grouped.get(rule.group, 0) + 1
    for group, count in sorted(grouped.items()):
        lines.append(f"  {group}: {count}")

    if data.show_targets:
        lines.append("")
        down = [t for t in data.targets if t.health == "down"]
        up = [t for t in data.targets if t.health == "up"]
        lines.append(f"Targets: {len(up)}/{len(up) + len(down)} up")
        for t in down:
            lines.append(f"  {theme.icons.unhealthy} {t.job}/{t.instance}")

    return "\n".join(lines)
