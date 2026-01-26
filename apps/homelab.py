"""Homelab dashboard: spec-driven projections over VM connections.

Run:
    uv run python apps/homelab.py                          # live SSH
    uv run python apps/homelab.py --source /tmp/homelab    # tail JSONL

Loads the app spec (specs/homelab.app.kdl), connects to VMs via SSH,
folds events into projections in-memory, renders via convention-based
component mapping. Hot-reloads on spec file changes.

With --source, tails JSONL files from the given directory instead of SSH.
Expects {source}/{vm_name}/{projection_name}.jsonl layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as script: python apps/homelab.py
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import asyncio
from dataclasses import dataclass, field

from cells import (
    RenderApp, Block, Style,
    join_horizontal, join_vertical, border,
    Line, Span,
    ListState, list_view,
)

from framework import (
    SpecProjection, parse_projection_spec,
    AppSpec, VMInfo, parse_app_spec,
    SpecWatcher,
    SourceBinding,
    start_binding,
    stop_binding,
    create_binding_for_tailer,
    create_binding_for_poll,
    create_binding_for_stream,
)
from framework.ssh_session import SSHSession
from framework.spec_render import render_projection


SPECS_DIR = Path(__file__).parent.parent / "specs"
APP_SPEC = SPECS_DIR / "homelab.app.kdl"


# -- VMConnection --------------------------------------------------------------

@dataclass
class VMConnection:
    """State for a connected VM: SSH session and bindings."""
    vm: VMInfo
    bindings: dict[str, SourceBinding] = field(default_factory=dict)
    ssh: SSHSession | None = None

    @property
    def projections(self) -> dict[str, SpecProjection]:
        """Access projections from bindings for rendering."""
        return {name: b.projection for name, b in self.bindings.items()}


# -- HomelabApp ----------------------------------------------------------------

class HomelabApp(RenderApp):
    def __init__(self, app_spec: AppSpec, source: Path | None = None):
        super().__init__(fps_cap=15)
        self.app_spec = app_spec
        self.vms = list(app_spec.vms)
        self.connections: dict[str, VMConnection] = {}
        self._source = source

        # Watcher (if spec declares watch=true)
        self._watcher: SpecWatcher | None = None
        self._watcher_task: asyncio.Task | None = None

        # UI state
        self._list_state = ListState(item_count=len(self.vms))
        self._width = 80
        self._height = 24

    async def on_start(self) -> None:
        """Called after render loop starts. Start watcher if configured."""
        if self.app_spec.watch:
            self._watcher = SpecWatcher(
                directory=SPECS_DIR,
                patterns=["*.projection.kdl", "*.app.kdl"],
                on_change=self._on_spec_change,
            )
            self._watcher_task = asyncio.create_task(self._watcher.run())

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
        for conn in self.connections.values():
            for proj in conn.projections.values():
                if proj.version > 0:
                    self.mark_dirty()
                    return

    def render(self) -> None:
        left_width = min(24, self._width // 3)
        vm_items = self._build_vm_list()
        vm_list_block = list_view(
            self._list_state,
            vm_items,
            self._height - 4,
            cursor_char="▸",
        )
        left_panel = border(vm_list_block, title="VMs")

        right_width = self._width - left_width - 1
        right_height = self._height - 2
        right_panel = self._build_right_panel(right_width, right_height)

        composed = join_horizontal(left_panel, right_panel)

        if self._buf is not None:
            self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
            composed.paint(self._buf.region(0, 0, self._buf.width, self._buf.height), 0, 0)

    def _build_vm_list(self) -> list[Line]:
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
        vm = self.selected_vm
        if vm is None:
            return Block.text("No VMs", Style(dim=True), width=width)

        conn = self.connections.get(vm.name)
        if conn is None:
            lines = [
                Block.text(f" {vm.name}", Style(bold=True), width=width),
                Block.text(f" {vm.user}@{vm.host}", Style(), width=width),
                Block.text(f" type: {vm.service_type or 'unknown'}", Style(dim=True), width=width),
                Block.text("", Style(), width=width),
                Block.text(" Press Enter to connect", Style(dim=True), width=width),
            ]
            return join_vertical(*lines)

        if not conn.projections:
            return Block.text(" Connected (no projections)", Style(dim=True), width=width)

        n_projs = len(conn.projections)
        proj_height = max(5, (height - n_projs) // n_projs)

        panels: list[Block] = []
        for proj in conn.projections.values():
            proj_block = render_projection(
                proj.spec, proj.state, width - 4, proj_height - 2
            )
            titled = border(proj_block, title=proj.spec.name)
            panels.append(titled)

        return join_vertical(*panels)

    # -- Key handling ----------------------------------------------------------

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())
        elif key == "up":
            self._list_state = self._list_state.move_up()
            self._list_state = self._list_state.scroll_into_view(self._height - 4)
        elif key == "down":
            self._list_state = self._list_state.move_down()
            self._list_state = self._list_state.scroll_into_view(self._height - 4)
        elif key in ("enter", "\r", "\n"):
            asyncio.ensure_future(self._toggle_connection())

    # -- Connection lifecycle --------------------------------------------------

    async def _toggle_connection(self) -> None:
        vm = self.selected_vm
        if vm is None:
            return

        if vm.name in self.connections:
            await self._disconnect(vm.name)
        else:
            await self._connect(vm)

    async def _connect(self, vm: VMInfo) -> None:
        """Connect to a VM: create bindings, start sources."""
        conn = VMConnection(vm=vm)
        self.connections[vm.name] = conn

        if self._source:
            # Replay mode: create TailerSource bindings
            for spec in self.app_spec.projections:
                projection = SpecProjection(spec)
                path = self._source / vm.name / f"{spec.name}.jsonl"
                binding = create_binding_for_tailer(
                    name=spec.name,
                    path=path,
                    projection=projection,
                    poll_interval=0.5,
                )
                conn.bindings[spec.name] = binding
                await start_binding(binding)
        else:
            # Live mode: SSH + data source bindings
            try:
                ssh = SSHSession(vm.host, vm.user, vm.key_file, common_args=vm.common_args)
                await ssh.__aenter__()
                conn.ssh = ssh

                # Create bindings based on data sources from spec
                for ds in self.app_spec.data_sources:
                    # Find the projection spec for this data source
                    proj_spec = next(
                        (p for p in self.app_spec.projections if p.name == ds.projection),
                        None
                    )
                    if proj_spec is None:
                        continue

                    projection = SpecProjection(proj_spec)
                    if ds.mode == "collect":
                        binding = create_binding_for_poll(
                            name=ds.projection,
                            ssh=ssh,
                            collector_name=ds.collector,
                            projection=projection,
                            interval=float(ds.interval or 10),
                        )
                    else:  # stream
                        binding = create_binding_for_stream(
                            name=ds.projection,
                            ssh=ssh,
                            collector_name=ds.collector,
                            projection=projection,
                        )
                    conn.bindings[ds.projection] = binding
                    await start_binding(binding)

            except Exception:
                # Connection failed, clean up
                self.connections.pop(vm.name, None)

        self.mark_dirty()

    async def _disconnect(self, vm_name: str) -> None:
        """Disconnect a VM: stop bindings, close SSH."""
        conn = self.connections.pop(vm_name, None)
        if conn is None:
            return

        # Stop all bindings
        for binding in conn.bindings.values():
            await stop_binding(binding)

        # Close SSH session
        if conn.ssh is not None:
            await conn.ssh.__aexit__(None, None, None)

        self.mark_dirty()

    async def _shutdown(self) -> None:
        """Clean shutdown: disconnect all, stop watcher, quit."""
        for name in list(self.connections):
            await self._disconnect(name)
        if self._watcher:
            self._watcher.stop()
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
        self.quit()

    # -- Hot-reload (watch=true) -----------------------------------------------

    async def _on_spec_change(self, changed: set[Path]) -> None:
        """Handle spec file changes from SpecWatcher."""
        for path in changed:
            if not path.suffix == ".kdl":
                continue
            if path.name.endswith(".app.kdl"):
                await self._reload_app_spec()
            elif path.name.endswith(".projection.kdl"):
                await self._reload_projection(path)

    async def _reload_app_spec(self) -> None:
        """Re-parse app spec, diff projections for connected VMs."""
        try:
            new_spec = parse_app_spec(APP_SPEC, specs_dir=SPECS_DIR)
        except Exception:
            return

        added, removed = self.app_spec.diff_uses(new_spec)
        self.app_spec = new_spec
        self.vms = list(new_spec.vms)
        self._list_state = ListState(item_count=len(self.vms))

        for vm_name, conn in self.connections.items():
            for name in removed:
                binding = conn.bindings.pop(name, None)
                if binding:
                    await stop_binding(binding)
            # Note: adding new projections to running connections
            # would require creating new bindings with SSH session
            # For simplicity, we just remove; user can reconnect

        self.mark_dirty()

    async def _reload_projection(self, path: Path) -> None:
        """Re-parse a projection spec, replace instances in connected VMs."""
        name = path.stem.replace(".projection", "")
        try:
            new_spec = parse_projection_spec(path)
        except Exception:
            return

        for conn in self.connections.values():
            if name in conn.bindings:
                # Replace the projection in the binding
                # The binding's stream stays the same, just update projection
                old_binding = conn.bindings[name]
                new_projection = SpecProjection(new_spec)
                # Swap projection on the stream tap
                old_binding.stream.detach(
                    next(t for t in old_binding.stream._taps
                         if t.consumer is old_binding.projection)
                )
                old_binding.stream.tap(new_projection)
                old_binding.projection = new_projection

        self.mark_dirty()


# -- Entry point ---------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Homelab VM dashboard")
    parser.add_argument("--source", type=Path, metavar="DIR",
                        help="Tail JSONL from DIR/{vm}/{projection}.jsonl instead of SSH")
    return parser.parse_args()


async def main():
    args = parse_args()
    app_spec = parse_app_spec(APP_SPEC, specs_dir=SPECS_DIR)

    print(f"Homelab Dashboard: {app_spec.name}")
    print(f"VMs: {len(app_spec.vms)}  Projections: {[p.name for p in app_spec.projections]}")
    if args.source:
        print(f"Source: {args.source}")
    print("↑/↓ select, Enter connect/disconnect, q quit\n")

    app = HomelabApp(app_spec, source=args.source)
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
