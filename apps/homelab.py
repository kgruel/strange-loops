"""Homelab dashboard: spec-driven projections over VM connections.

Run: uv run python -m apps.homelab

Loads the app spec (specs/homelab.app.kdl), displays VM inventory,
and allows connecting/disconnecting to VMs. Connected VMs get
per-connection projection instances rendered via convention-based
component mapping.

For now, connections simulate events. Real SSH comes later.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from pathlib import Path

from render.app import RenderApp
from render.block import Block
from render.cell import Style
from render.compose import join_horizontal, join_vertical, pad, border
from render.span import Line, Span
from render.components.list_view import ListState, list_view

from framework.spec import SpecProjection, ProjectionSpec
from framework.spec_render import render_projection
from framework.app_spec import parse_app_spec, AppSpec, VMInfo


SPECS_DIR = Path(__file__).parent.parent / "specs"
APP_SPEC = SPECS_DIR / "homelab.app.kdl"


@dataclass
class VMConnection:
    """State for a connected VM: projection instances + simulation task."""
    vm: VMInfo
    projections: list[SpecProjection]
    task: asyncio.Task | None = None


class HomelabApp(RenderApp):
    def __init__(self, app_spec: AppSpec):
        super().__init__(fps_cap=15)
        self.app_spec = app_spec
        self.vms = list(app_spec.vms)
        self.connections: dict[str, VMConnection] = {}

        # UI state
        self._list_state = ListState(item_count=len(self.vms))
        self._width = 80
        self._height = 24

    def layout(self, width: int, height: int) -> None:
        self._width = width
        self._height = height

    @property
    def selected_vm(self) -> VMInfo | None:
        if not self.vms:
            return None
        idx = self._list_state.selected
        if 0 <= idx < len(self.vms):
            return self.vms[idx]
        return None

    def update(self) -> None:
        # Any connected VM with new projection versions triggers redraw
        for conn in self.connections.values():
            for proj in conn.projections:
                if proj.version > 0:
                    self.mark_dirty()
                    return

    def render(self) -> None:
        # Left panel: VM list
        left_width = min(24, self._width // 3)
        vm_items = self._build_vm_list()
        vm_list_block = list_view(
            self._list_state,
            vm_items,
            self._height - 4,
            cursor_char="▸",
        )
        left_panel = border(vm_list_block, title="VMs")

        # Right panel: projections for selected VM
        right_width = self._width - left_width - 1
        right_height = self._height - 2
        right_panel = self._build_right_panel(right_width, right_height)

        composed = join_horizontal(left_panel, right_panel)

        if self._buf is not None:
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            composed.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _build_vm_list(self) -> list[Line]:
        """Build VM list items with connection indicators."""
        items: list[Line] = []
        for vm in self.vms:
            connected = vm.name in self.connections
            indicator = Span("● ", Style(fg="green")) if connected else Span("  ", Style(dim=True))
            name_style = Style(bold=True) if connected else Style()
            type_str = f" ({vm.service_type})" if vm.service_type else ""
            items.append(Line(spans=(
                indicator,
                Span(vm.name, name_style),
                Span(type_str, Style(dim=True)),
            )))
        return items

    def _build_right_panel(self, width: int, height: int) -> Block:
        """Build the right panel showing projections for the selected VM."""
        vm = self.selected_vm
        if vm is None:
            return Block.text("No VMs", Style(dim=True), width=width)

        conn = self.connections.get(vm.name)
        if conn is None:
            # Not connected — show VM info
            lines = [
                Block.text(f" {vm.name}", Style(bold=True), width=width),
                Block.text(f" {vm.user}@{vm.host}", Style(), width=width),
                Block.text(f" type: {vm.service_type or 'unknown'}", Style(dim=True), width=width),
                Block.text("", Style(), width=width),
                Block.text(" Press Enter to connect", Style(dim=True), width=width),
            ]
            return join_vertical(*lines)

        # Connected — render each projection
        if not conn.projections:
            return Block.text(" Connected (no projections)", Style(dim=True), width=width)

        n_projs = len(conn.projections)
        proj_height = max(5, (height - n_projs) // n_projs)  # divide space

        panels: list[Block] = []
        for proj in conn.projections:
            proj_block = render_projection(
                proj.spec, proj.state, width - 4, proj_height - 2
            )
            titled = border(proj_block, title=proj.spec.name)
            panels.append(titled)

        return join_vertical(*panels)

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            # Cancel all simulation tasks
            for conn in self.connections.values():
                if conn.task:
                    conn.task.cancel()
            self.quit()
        elif key == "up":
            self._list_state = self._list_state.move_up()
            self._list_state = self._list_state.scroll_into_view(self._height - 4)
        elif key == "down":
            self._list_state = self._list_state.move_down()
            self._list_state = self._list_state.scroll_into_view(self._height - 4)
        elif key in ("enter", "\r", "\n"):
            self._toggle_connection()

    def _toggle_connection(self) -> None:
        """Connect or disconnect the selected VM."""
        vm = self.selected_vm
        if vm is None:
            return

        if vm.name in self.connections:
            # Disconnect
            conn = self.connections.pop(vm.name)
            if conn.task:
                conn.task.cancel()
        else:
            # Connect — create projection instances and start simulation
            projections = [
                SpecProjection(spec) for spec in self.app_spec.projections
            ]
            conn = VMConnection(vm=vm, projections=projections)
            self.connections[vm.name] = conn
            # Start simulated event stream
            conn.task = asyncio.ensure_future(self._simulate_events(vm.name))

    async def _simulate_events(self, vm_name: str) -> None:
        """Simulate events for a connected VM (placeholder for real SSH)."""
        containers = ["nginx", "postgres", "redis", "app", "worker"]
        levels = ["info", "info", "info", "warn", "error", "debug"]
        messages = [
            "Request processed",
            "Connection established",
            "Health check passed",
            "Slow query detected",
            "Connection timeout",
            "Cache miss",
            "Worker started",
            "Memory usage high",
        ]

        while True:
            conn = self.connections.get(vm_name)
            if conn is None:
                break

            for proj in conn.projections:
                if proj.spec.name == "vm-health":
                    # Emit a container status event
                    container = random.choice(containers)
                    healthy = random.random() > 0.15
                    event = {
                        "container": container,
                        "service": container,
                        "state": "running" if healthy else "restarting",
                        "health": "healthy" if healthy else "unhealthy",
                        "healthy": healthy,
                    }
                    await proj.consume(event)

                elif proj.spec.name == "vm-logs":
                    # Emit a log line event
                    event = {
                        "source": random.choice(containers),
                        "message": random.choice(messages),
                        "level": random.choice(levels),
                    }
                    await proj.consume(event)

            self.mark_dirty()
            await asyncio.sleep(random.uniform(0.3, 1.5))


async def main():
    app_spec = parse_app_spec(APP_SPEC, specs_dir=SPECS_DIR)
    print(f"Homelab Dashboard: {app_spec.name}")
    print(f"VMs: {len(app_spec.vms)}  Projections: {[p.name for p in app_spec.projections]}")
    print("Use ↑/↓ to select, Enter to connect/disconnect, q to quit\n")

    app = HomelabApp(app_spec)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
