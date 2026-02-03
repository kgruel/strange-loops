"""Stack lens — zoom-based rendering for homelab stacks."""

from __future__ import annotations

from cells import Block, Style, join_vertical


# Style palette
GREEN = Style(fg="green")
BLUE = Style(fg="blue")
RED = Style(fg="red")


def stack_lens(
    name: str,
    payload: dict,
    zoom: int,
    width: int,
) -> Block:
    """Render a stack at the given zoom level.

    Args:
        name: Stack name (infra, media, etc.)
        payload: Tick payload with containers, healthy, total
        zoom: 0=minimal, 1=containers, 2=+uptime, 3=+all fields
        width: Available width

    Returns:
        Block with rendered stack
    """
    containers = payload.get("containers", [])
    healthy = payload.get("healthy", 0)
    total = payload.get("total", len(containers))

    all_healthy = healthy == total
    icon = "✓" if all_healthy else "✗"
    header_style = Style(fg="green", bold=True) if all_healthy else Style(fg="red", bold=True)

    # Zoom 0: just header
    header = Block.text(f"{icon} {name}: {healthy}/{total}", header_style, width=width)
    if zoom == 0:
        return header

    # Zoom 1+: add containers
    rows = [header]
    for c in containers:
        rows.append(_render_container(c, zoom, width))

    return join_vertical(*rows)


def _render_container(c: dict, zoom: int, width: int) -> Block:
    """Render a single container at zoom level."""
    cname = c.get("Name", "?")
    state = c.get("State", "?")
    health = c.get("Health", "")

    # Determine style and status text
    if state == "running" and health == "healthy":
        style = GREEN
        status = "healthy"
    elif state == "running":
        style = BLUE
        status = health or "running"
    else:
        style = RED
        status = state

    # Build line based on zoom
    line = f"  {cname}: {status}"

    if zoom >= 2:
        uptime = c.get("RunningFor", "")
        if uptime:
            line += f" ({uptime})"

    if zoom >= 3:
        # Full detail: show all fields
        extras = []
        for key in ("Image", "Ports", "Networks"):
            if val := c.get(key):
                extras.append(f"{key}={val}")
        if extras:
            line += f" [{', '.join(extras)}]"

    return Block.text(line, style, width=width)
