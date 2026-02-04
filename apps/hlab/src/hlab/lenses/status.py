"""Lenses — zoom-based rendering for homelab stacks.

Zoom controls progressive enhancement of the same view:
- MINIMAL (0): one-liner summary
- SUMMARY (1): tree view with branch characters, problems inline
- DETAILED (2): enhanced tree with borders, uptime, summary
- FULL (3): interactive TUI (handled separately)

Higher zoom adds detail to the same structure, not a different format.
"""

from __future__ import annotations

from dataclasses import dataclass

from cells import Block, Style, Zoom, join_vertical, join_horizontal, border, ROUNDED

from ..theme import Theme, DEFAULT_THEME


@dataclass(frozen=True)
class PendingState:
    """State for rendering pending stacks with spinners."""

    pending: frozenset[str]  # Stack names still loading
    spinner_frame: int = 0  # Current spinner animation frame

    def tick(self) -> "PendingState":
        """Advance spinner frame."""
        return PendingState(
            pending=self.pending,
            spinner_frame=(self.spinner_frame + 1) % 10,
        )


def _is_healthy(container: dict) -> bool:
    """Check if a container is healthy."""
    state = container.get("State", "")
    health = container.get("Health", "")
    return state == "running" and health in ("healthy", "")


def _health_icon_style(payload: dict, theme: Theme) -> tuple[str, Style]:
    """Return icon and style based on stack health."""
    healthy = payload.get("healthy", 0)
    total = payload.get("total", 0)
    all_healthy = healthy == total
    icon = theme.icons.healthy if all_healthy else theme.icons.unhealthy
    style = Style(fg=theme.colors.success) if all_healthy else Style(fg=theme.colors.error)
    return icon, style


def status_view(
    stacks: dict[str, dict],
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render stacks at zoom level.

    Args:
        stacks: {stack_name: payload} where payload has containers, healthy, total
        zoom: MINIMAL=one-liner, SUMMARY=tree, DETAILED/FULL=bordered tree
        width: Available terminal width
        theme: Theme instance for icons/colors

    Returns:
        Block ready for print_block()

    MINIMAL: one-liner
        + 4 stacks, 44/45 healthy (1 down)

    SUMMARY: tree with branch chars
        Status
        ├─ + infra: 16/16
        ├─ + media: 22/22
        ├─ x dev: 4/5
        │  └─ x neo4j: unhealthy
        └─ + minecraft: 2/2

    DETAILED/FULL: bordered tree with uptime and summary
        ╭── Status ──────────────────────────────╮
        │ ├─ + infra: 16/16                      │
        │ ├─ + media: 22/22                      │
        │ ├─ x dev: 4/5                          │
        │ │  └─ x neo4j: unhealthy (3d uptime)   │
        │ └─ + minecraft: 2/2                    │
        │                                        │
        │ Total: 44/45 healthy                   │
        ╰────────────────────────────────────────╯
    """
    if not stacks:
        return Block.text("No data", Style(dim=True), width=width)

    if zoom == Zoom.MINIMAL:
        return _render_oneliner(stacks, width, theme)

    if zoom == Zoom.SUMMARY:
        return _render_tree(stacks, width, theme, show_uptime=False)

    # DETAILED or FULL: bordered tree with uptime and summary
    return _render_bordered_tree(stacks, width, theme)


def status_view_with_pending(
    stacks: dict[str, dict],
    pending: PendingState,
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render stacks with spinners for pending ones.

    Args:
        stacks: {stack_name: payload} for received stacks
        pending: PendingState with pending stack names and spinner frame
        zoom: MINIMAL=one-liner, SUMMARY=tree, DETAILED/FULL=bordered tree
        width: Available terminal width
        theme: Theme instance for icons/colors

    Returns:
        Block ready for print_block()
    """
    # MINIMAL: one-liner doesn't show spinners (too minimal)
    if zoom == Zoom.MINIMAL:
        if pending.pending:
            # Still loading - show spinner
            spinner = theme.icons.spinner[pending.spinner_frame]
            return Block.text(f"{spinner} Loading...", Style(dim=True), width=width)
        return _render_oneliner(stacks, width, theme)

    if zoom == Zoom.SUMMARY:
        return _render_tree_with_pending(stacks, pending, width, theme, show_uptime=False)

    # DETAILED/FULL: bordered tree with pending
    return _render_bordered_tree_with_pending(stacks, pending, width, theme)


def _render_tree_with_pending(
    stacks: dict[str, dict],
    pending: PendingState,
    width: int,
    theme: Theme,
    *,
    show_uptime: bool = False,
) -> Block:
    """Render tree view with spinners for pending stacks."""
    rows: list[Block] = [Block.text("Status", Style(bold=True), width=width)]

    # Combine received stacks + pending names for consistent ordering
    all_names = sorted(set(stacks.keys()) | pending.pending)

    for i, name in enumerate(all_names):
        is_last = i == len(all_names) - 1
        branch = theme.icons.branch_last if is_last else theme.icons.branch
        continuation = theme.icons.continuation_last if is_last else theme.icons.continuation

        if name in pending.pending:
            # Show spinner for pending stack
            spinner = theme.icons.spinner[pending.spinner_frame]
            header = f"{branch} {spinner} {name}..."
            rows.append(Block.text(header, Style(dim=True), width=width))
        else:
            # Render received stack
            payload = stacks[name]
            icon, style = _health_icon_style(payload, theme)
            healthy = payload.get("healthy", 0)
            total = payload.get("total", 0)
            header = f"{branch} {icon} {name}: {healthy}/{total}"
            rows.append(Block.text(header, style, width=width))

            # Show unhealthy services (indented)
            containers = payload.get("containers", [])
            unhealthy = [c for c in containers if not _is_healthy(c)]
            for j, c in enumerate(unhealthy):
                sub_is_last = j == len(unhealthy) - 1
                sub_branch = theme.icons.branch_last if sub_is_last else theme.icons.branch
                cname = c.get("Name", "?")
                health = c.get("Health", "") or c.get("State", "unhealthy")

                line = f"{continuation}{sub_branch} {theme.icons.unhealthy} {cname}: {health}"

                if show_uptime:
                    uptime = c.get("RunningFor", "")
                    if uptime:
                        line += f" ({uptime})"

                rows.append(Block.text(line, Style(fg=theme.colors.error), width=width))

    return join_vertical(*rows)


def _render_bordered_tree_with_pending(
    stacks: dict[str, dict],
    pending: PendingState,
    width: int,
    theme: Theme,
) -> Block:
    """Fidelity 2: Bordered tree with spinners, uptime and summary."""
    inner_width = width - 4

    tree_rows: list[Block] = []
    all_names = sorted(set(stacks.keys()) | pending.pending)

    total_healthy = sum(p.get("healthy", 0) for p in stacks.values())
    total_containers = sum(p.get("total", 0) for p in stacks.values())

    for i, name in enumerate(all_names):
        is_last = i == len(all_names) - 1
        branch = theme.icons.branch_last if is_last else theme.icons.branch
        continuation = theme.icons.continuation_last if is_last else theme.icons.continuation

        if name in pending.pending:
            spinner = theme.icons.spinner[pending.spinner_frame]
            header = f"{branch} {spinner} {name}..."
            tree_rows.append(Block.text(header, Style(dim=True), width=inner_width))
        else:
            payload = stacks[name]
            icon, style = _health_icon_style(payload, theme)
            healthy = payload.get("healthy", 0)
            total = payload.get("total", 0)
            header = f"{branch} {icon} {name}: {healthy}/{total}"
            tree_rows.append(Block.text(header, style, width=inner_width))

            containers = payload.get("containers", [])
            unhealthy = [c for c in containers if not _is_healthy(c)]
            for j, c in enumerate(unhealthy):
                sub_is_last = j == len(unhealthy) - 1
                sub_branch = theme.icons.branch_last if sub_is_last else theme.icons.branch
                cname = c.get("Name", "?")
                health = c.get("Health", "") or c.get("State", "unhealthy")
                uptime = c.get("RunningFor", "")

                line = f"{continuation}{sub_branch} {theme.icons.unhealthy} {cname}: {health}"
                if uptime:
                    line += f" ({uptime})"

                tree_rows.append(Block.text(line, Style(fg=theme.colors.error), width=inner_width))

    # Add blank line and summary
    tree_rows.append(Block.empty(inner_width, 1))
    if pending.pending:
        n_pending = len(pending.pending)
        summary_line = f"Total: {total_healthy}/{total_containers} healthy ({n_pending} loading...)"
    else:
        summary_line = f"Total: {total_healthy}/{total_containers} healthy"
    tree_rows.append(Block.text(summary_line, Style(bold=True), width=inner_width))

    content = join_vertical(*tree_rows)
    return border(content, title="Status", style=Style(fg=theme.colors.accent), chars=ROUNDED)


def _render_oneliner(stacks: dict[str, dict], width: int, theme: Theme) -> Block:
    """Fidelity 0: Single line summary."""
    total_healthy = sum(p.get("healthy", 0) for p in stacks.values())
    total_containers = sum(p.get("total", 0) for p in stacks.values())
    all_ok = total_healthy == total_containers
    down = total_containers - total_healthy

    icon = theme.icons.healthy if all_ok else theme.icons.unhealthy
    style = Style(fg=theme.colors.success) if all_ok else Style(fg=theme.colors.error)

    text = f"{icon} {len(stacks)} stacks, {total_healthy}/{total_containers} healthy"
    if down > 0:
        text += f" ({down} down)"

    return Block.text(text, style, width=width)


def _render_tree(
    stacks: dict[str, dict],
    width: int,
    theme: Theme,
    *,
    show_uptime: bool = False,
) -> Block:
    """Render tree view (used by F1 and F2)."""
    rows: list[Block] = [Block.text("Status", Style(bold=True), width=width)]

    stack_names = sorted(stacks.keys())
    for i, name in enumerate(stack_names):
        payload = stacks[name]
        is_last = i == len(stack_names) - 1
        branch = theme.icons.branch_last if is_last else theme.icons.branch
        continuation = theme.icons.continuation_last if is_last else theme.icons.continuation

        # Stack header
        icon, style = _health_icon_style(payload, theme)
        healthy = payload.get("healthy", 0)
        total = payload.get("total", 0)
        header = f"{branch} {icon} {name}: {healthy}/{total}"
        rows.append(Block.text(header, style, width=width))

        # Show unhealthy services (indented)
        containers = payload.get("containers", [])
        unhealthy = [c for c in containers if not _is_healthy(c)]
        for j, c in enumerate(unhealthy):
            sub_is_last = j == len(unhealthy) - 1
            sub_branch = theme.icons.branch_last if sub_is_last else theme.icons.branch
            cname = c.get("Name", "?")
            health = c.get("Health", "") or c.get("State", "unhealthy")

            line = f"{continuation}{sub_branch} {theme.icons.unhealthy} {cname}: {health}"

            if show_uptime:
                uptime = c.get("RunningFor", "")
                if uptime:
                    line += f" ({uptime})"

            rows.append(Block.text(line, Style(fg=theme.colors.error), width=width))

    return join_vertical(*rows)


def _render_bordered_tree(stacks: dict[str, dict], width: int, theme: Theme) -> Block:
    """Fidelity 2: Bordered tree with uptime and summary."""
    # Compute summary
    total_healthy = sum(p.get("healthy", 0) for p in stacks.values())
    total_containers = sum(p.get("total", 0) for p in stacks.values())

    # Inner width accounts for border (2 chars each side)
    inner_width = width - 4

    # Build tree content (without the "Status" header - that goes in border title)
    tree_rows: list[Block] = []
    stack_names = sorted(stacks.keys())

    for i, name in enumerate(stack_names):
        payload = stacks[name]
        is_last = i == len(stack_names) - 1
        branch = theme.icons.branch_last if is_last else theme.icons.branch
        continuation = theme.icons.continuation_last if is_last else theme.icons.continuation

        icon, style = _health_icon_style(payload, theme)
        healthy = payload.get("healthy", 0)
        total = payload.get("total", 0)
        header = f"{branch} {icon} {name}: {healthy}/{total}"
        tree_rows.append(Block.text(header, style, width=inner_width))

        containers = payload.get("containers", [])
        unhealthy = [c for c in containers if not _is_healthy(c)]
        for j, c in enumerate(unhealthy):
            sub_is_last = j == len(unhealthy) - 1
            sub_branch = theme.icons.branch_last if sub_is_last else theme.icons.branch
            cname = c.get("Name", "?")
            health = c.get("Health", "") or c.get("State", "unhealthy")
            uptime = c.get("RunningFor", "")

            line = f"{continuation}{sub_branch} {theme.icons.unhealthy} {cname}: {health}"
            if uptime:
                line += f" ({uptime})"

            tree_rows.append(Block.text(line, Style(fg=theme.colors.error), width=inner_width))

    # Add blank line and summary
    tree_rows.append(Block.empty(inner_width, 1))
    summary_line = f"Total: {total_healthy}/{total_containers} healthy"
    tree_rows.append(Block.text(summary_line, Style(bold=True), width=inner_width))

    content = join_vertical(*tree_rows)
    return border(content, title="Status", style=Style(fg=theme.colors.accent), chars=ROUNDED)


def render_plain(stacks: dict[str, dict], theme: Theme = DEFAULT_THEME) -> str:
    """Render stacks as plain text for non-TTY output.

    No ANSI codes, simple structure suitable for piping.

    Example:
        Status

        + infra: 16/16 healthy
        + media: 22/22 healthy
        x dev: 4/5 healthy
          - neo4j: unhealthy
        + minecraft: 2/2 healthy

        Total: 44/45 healthy
    """
    if not stacks:
        return "No data"

    lines: list[str] = ["Status", ""]

    total_healthy = 0
    total_containers = 0

    for name in sorted(stacks.keys()):
        payload = stacks[name]
        healthy = payload.get("healthy", 0)
        total = payload.get("total", 0)
        total_healthy += healthy
        total_containers += total

        all_ok = healthy == total
        icon = theme.icons.healthy if all_ok else theme.icons.unhealthy
        lines.append(f"{icon} {name}: {healthy}/{total} healthy")

        # Show unhealthy containers
        containers = payload.get("containers", [])
        unhealthy = [c for c in containers if not _is_healthy(c)]
        for c in unhealthy:
            cname = c.get("Name", "?")
            health = c.get("Health", "") or c.get("State", "unhealthy")
            lines.append(f"  - {cname}: {health}")

    lines.append("")
    lines.append(f"Total: {total_healthy}/{total_containers} healthy")

    return "\n".join(lines)


# Keep stack_lens for TUI (FULL zoom) backward compatibility
def stack_lens(
    name: str,
    payload: dict,
    zoom: Zoom,
    width: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render a stack at the given zoom level.

    Used by TUI (FULL zoom) for detailed container rendering.

    Args:
        name: Stack name (infra, media, etc.)
        payload: Tick payload with containers, healthy, total
        zoom: MINIMAL=header only, SUMMARY=+containers, DETAILED=+uptime, FULL=+all fields
        width: Available width
        theme: Theme instance

    Returns:
        Block with rendered stack
    """
    containers = payload.get("containers", [])
    healthy = payload.get("healthy", 0)
    total = payload.get("total", len(containers))

    all_healthy = healthy == total
    icon = theme.icons.healthy if all_healthy else theme.icons.unhealthy
    header_style = (
        Style(fg=theme.colors.success, bold=True)
        if all_healthy
        else Style(fg=theme.colors.error, bold=True)
    )

    # MINIMAL: just header
    header = Block.text(f"{icon} {name}: {healthy}/{total}", header_style, width=width)
    if zoom == Zoom.MINIMAL:
        return header

    # SUMMARY+: add containers
    rows = [header]
    for c in containers:
        rows.append(_render_container(c, zoom, width, theme))

    return join_vertical(*rows)


def _render_container(c: dict, zoom: Zoom, width: int, theme: Theme) -> Block:
    """Render a single container at zoom level."""
    cname = c.get("Name", "?")
    state = c.get("State", "?")
    health = c.get("Health", "")

    # Determine style and status text
    if state == "running" and health == "healthy":
        style = Style(fg=theme.colors.success)
        status = "healthy"
    elif state == "running":
        style = Style(fg=theme.colors.accent)
        status = health or "running"
    else:
        style = Style(fg=theme.colors.error)
        status = state

    # Build line based on zoom
    line = f"  {cname}: {status}"

    if zoom >= Zoom.DETAILED:
        uptime = c.get("RunningFor", "")
        if uptime:
            line += f" ({uptime})"

    if zoom >= Zoom.FULL:
        # Full detail: show all fields
        extras = []
        for key in ("Image", "Ports", "Networks"):
            if val := c.get(key):
                extras.append(f"{key}={val}")
        if extras:
            line += f" [{', '.join(extras)}]"

    return Block.text(line, style, width=width)


# === TUI Two-Panel Rendering (F3) ===


def render_stack_list(
    stacks: dict[str, dict],
    pending: PendingState,
    selected: int,
    width: int,
    height: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render the left panel: list of stacks with selection.

    Args:
        stacks: {stack_name: payload} for received stacks
        pending: PendingState with pending stack names and spinner frame
        selected: Index of currently selected stack
        width: Panel width (not including border)
        height: Panel height (not including border)
        theme: Theme instance

    Returns:
        Block for the stack list panel (without border)
    """
    all_names = sorted(set(stacks.keys()) | pending.pending)
    rows: list[Block] = []

    for i, name in enumerate(all_names):
        is_selected = i == selected

        if name in pending.pending:
            # Pending stack with spinner
            spinner = theme.icons.spinner[pending.spinner_frame]
            prefix = theme.icons.selected if is_selected else " "
            line = f"{prefix} {spinner} {name}..."
            style = Style(
                reverse=is_selected,
                fg=theme.colors.selected_fg if is_selected else None,
                bg=theme.colors.selected_bg if is_selected else None,
                dim=not is_selected,
            )
        else:
            # Received stack
            payload = stacks[name]
            icon, base_style = _health_icon_style(payload, theme)
            healthy = payload.get("healthy", 0)
            total = payload.get("total", 0)
            prefix = theme.icons.selected if is_selected else " "
            line = f"{prefix} {icon} {name}: {healthy}/{total}"
            if is_selected:
                style = Style(reverse=True, fg=theme.colors.selected_fg, bg=theme.colors.selected_bg)
            else:
                style = base_style

        rows.append(Block.text(line, style, width=width))

    # Pad to fill height
    while len(rows) < height:
        rows.append(Block.empty(width, 1))

    return join_vertical(*rows[:height])


def render_container_detail(
    name: str | None,
    payload: dict | None,
    pending: bool,
    spinner_frame: int,
    width: int,
    height: int,
    theme: Theme = DEFAULT_THEME,
) -> Block:
    """Render the right panel: containers for selected stack.

    Args:
        name: Stack name (None if no selection)
        payload: Stack payload (None if pending or no selection)
        pending: True if this stack is still loading
        spinner_frame: Current spinner frame for pending animation
        width: Panel width (not including border)
        height: Panel height (not including border)
        theme: Theme instance

    Returns:
        Block for the container detail panel (without border)
    """
    rows: list[Block] = []

    if name is None:
        rows.append(Block.text("No stack selected", Style(dim=True), width=width))
    elif pending:
        spinner = theme.icons.spinner[spinner_frame]
        rows.append(Block.text(f"{spinner} Waiting for data...", Style(dim=True), width=width))
    elif payload is None:
        rows.append(Block.text("No data", Style(dim=True), width=width))
    else:
        containers = payload.get("containers", [])
        for c in containers:
            cname = c.get("Name", "?")
            state = c.get("State", "?")
            health = c.get("Health", "")
            uptime = c.get("RunningFor", "")

            # Determine status and style
            if state == "running" and health == "healthy":
                style = Style(fg=theme.colors.success)
                status = "healthy"
            elif state == "running" and health == "unhealthy":
                style = Style(fg=theme.colors.error)
                status = "unhealthy"
            elif state == "running":
                style = Style(fg=theme.colors.accent)
                status = health or "running"
            else:
                style = Style(fg=theme.colors.error)
                status = state

            # Format: name status (uptime)
            # Align columns: name (left), status (center), uptime (right)
            uptime_str = f"({uptime})" if uptime else ""
            line = f"  {cname:<20} {status:<12} {uptime_str}"
            rows.append(Block.text(line[:width], style, width=width))

    # Pad to fill height
    while len(rows) < height:
        rows.append(Block.empty(width, 1))

    return join_vertical(*rows[:height])
