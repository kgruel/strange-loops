"""Three-level vertex with heterogeneous VM activities.

Each VM is a Vertex — an intersection of whatever loops pass through it.
Different VMs run different activities. Their ticks carry different kinds.
Region and global vertices collect whatever arrives.

    vm-1 [health]            ──→ Vertex ──tick──┐
                                                ├──→ East Vertex ──tick──┐
    vm-2 [health + deploy]   ──→ Vertex ──tick──┘                        │
                                                              ├──→ Global Vertex ──tick
    vm-3 [audit]             ──→ Vertex ──tick──┐                        │
                                                ├──→ West Vertex ──tick──┘
    vm-4 [health + audit]    ──→ Vertex ──tick──┘

Run:
    uv run python experiments/fleet.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from datetime import datetime, timezone

from atoms import Fact
from vertex import Peer
from vertex import Tick, Vertex
from atoms import Shape, Facet, Fold
from cells import Block, Style, join_vertical, border
from cells.tui import Surface

# System peer — unrestricted, used for all fact emissions in this experiment.
SYSTEM = Peer("system")


# -- Shapes ------------------------------------------------------------------
# Shape descriptors define contracts. No boundary — fleet uses manual tick.

health_shape = Shape(
    name="health",
    about="Container health observations",
    input_facets=(Facet("container", "str"), Facet("status", "str")),
    state_facets=(Facet("count", "int"), Facet("last", "str"), Facet("status", "str")),
    # No folds — hand-written fold (needs last-container-name logic)
)

deploy_shape = Shape(
    name="deploy",
    about="Deploy progression through stages",
    input_facets=(Facet("target", "str"), Facet("stage", "str")),
    state_facets=(Facet("target", "str"), Facet("stage", "str"), Facet("step", "int")),
    # No folds — hand-written fold (needs stage tracking logic)
)

audit_shape = Shape(
    name="audit",
    about="Audit scan results",
    input_facets=(Facet("scanned", "int"), Facet("issues", "int"), Facet("fixed", "int")),
    state_facets=(Facet("scanned", "int"), Facet("issues", "int"), Facet("fixed", "int")),
    folds=(
        Fold("sum", "scanned", {"field": "scanned"}),
        Fold("sum", "issues", {"field": "issues"}),
        Fold("sum", "fixed", {"field": "fixed"}),
    ),
)


# -- Folds -------------------------------------------------------------------

def health_fold(state: dict, payload: dict) -> dict:
    """Count container observations, keep last seen."""
    return {
        "count": state.get("count", 0) + 1,
        "last": payload.get("container", "?"),
        "status": payload.get("status", "?"),
    }


def deploy_fold(state: dict, payload: dict) -> dict:
    """Track deploy progression through stages."""
    return {
        "target": payload.get("target", state.get("target", "?")),
        "stage": payload.get("stage", state.get("stage", "pending")),
        "step": state.get("step", 0) + 1,
    }


def collect_fold(state: dict, tick_payload: dict) -> dict:
    """Higher-level fold: latest tick payload replaces state."""
    return tick_payload


# -- Topology ----------------------------------------------------------------

VM_REGION = {"vm-1": "east", "vm-2": "east", "vm-3": "west", "vm-4": "west"}

# What each VM does — (shape, fold) pairs.
# shape.apply() for audit (ops fit), hand-written folds for health/deploy.
VM_SHAPES: dict[str, list[tuple[Shape, object]]] = {
    "vm-1": [(health_shape, health_fold)],
    "vm-2": [(health_shape, health_fold), (deploy_shape, deploy_fold)],
    "vm-3": [(audit_shape, audit_shape.apply)],
    "vm-4": [(health_shape, health_fold), (audit_shape, audit_shape.apply)],
}


def build_topology() -> tuple[dict[str, Vertex], dict[str, Vertex], Vertex]:
    """Wire vertices from Shape descriptors."""
    # L0: leaf vertices — Shape drives registration
    vms: dict[str, Vertex] = {}
    for vm_name, shapes in VM_SHAPES.items():
        v = Vertex(vm_name)
        for shape, fold in shapes:
            v.register(shape.name, shape.initial_state(), fold)
        vms[vm_name] = v

    # L1: region vertices — collect fold, no shape needed
    regions: dict[str, Vertex] = {}
    for region_name in ("east", "west"):
        r = Vertex(region_name)
        for vm_name, vm_region in VM_REGION.items():
            if vm_region == region_name:
                r.register(vm_name, {}, collect_fold)
        regions[region_name] = r

    # L2: global vertex
    globe = Vertex("global")
    for region in regions:
        globe.register(region, {}, collect_fold)

    return vms, regions, globe


# -- Fact generators ---------------------------------------------------------

CONTAINERS = {
    "vm-1": ["nginx", "api", "redis"],
    "vm-2": ["postgres", "worker"],
    "vm-4": ["grafana", "prometheus"],
}

STATUSES = ["running", "running", "running", "unhealthy", "stopped"]

DEPLOY_STAGES = ["build", "test", "push", "rollout", "done"]


def generate_facts(cycle: int, vms: dict[str, Vertex]) -> list[str]:
    """Generate one round of facts. Returns log entries."""
    log = []

    # Health facts for VMs that have health registered
    for vm_name, containers in CONTAINERS.items():
        for c in containers:
            status = random.choice(STATUSES)
            f = Fact.of("health", container=c, status=status)
            vms[vm_name].receive(f, SYSTEM)
        log.append(f"{vm_name}: {len(containers)} health facts")

    # Deploy facts for vm-2
    stage_idx = min(cycle - 1, len(DEPLOY_STAGES) - 1)
    stage = DEPLOY_STAGES[stage_idx]
    f = Fact.of("deploy", target="api-v2.3", stage=stage)
    vms["vm-2"].receive(f, SYSTEM)
    log.append(f"vm-2: deploy -> {stage}")

    # Audit facts for vm-3 and vm-4
    for vm_name in ("vm-3", "vm-4"):
        scanned = random.randint(10, 50)
        issues = random.randint(0, 3)
        fixed = min(issues, random.randint(0, issues + 1))
        f = Fact.of("audit", scanned=scanned, issues=issues, fixed=fixed)
        vms[vm_name].receive(f, SYSTEM)
        log.append(f"{vm_name}: audit +{scanned} scanned")

    return log


# -- App ---------------------------------------------------------------------

DELAY = 0.3

DIM = Style(dim=True)
BOLD = Style(bold=True)
ACTIVE = Style(fg="cyan", bold=True)

KIND_STYLE = {
    "health": Style(fg="green"),
    "deploy": Style(fg="magenta"),
    "audit": Style(fg="yellow"),
}


def render_vm_tick(vm_name: str, tick: Tick | None, w: int) -> list[Block]:
    """Render a VM's tick payload — one line per kind."""
    lines = []
    kinds = [s.name for s, _ in VM_SHAPES[vm_name]]
    kind_tags = " ".join(f"[{k}]" for k in kinds)

    if tick is None:
        lines.append(Block.text(f"  {vm_name} {kind_tags}: (waiting)", DIM, width=w))
        return lines

    header_style = Style(bold=True)
    lines.append(Block.text(f"  {vm_name} {kind_tags}", header_style, width=w))

    for kind in kinds:
        state = tick.payload.get(kind, {})
        style = KIND_STYLE.get(kind, DIM)

        if kind == "health":
            count = state.get("count", 0)
            last = state.get("last", "?")
            status = state.get("status", "?")
            text = f"    health: {count} obs, last={last} ({status})"
        elif kind == "deploy":
            stage = state.get("stage", "?")
            target = state.get("target", "?")
            step = state.get("step", 0)
            text = f"    deploy: {target} [{stage}] step {step}"
        elif kind == "audit":
            scanned = state.get("scanned", 0)
            issues = state.get("issues", 0)
            fixed = state.get("fixed", 0)
            text = f"    audit: {scanned} scanned, {issues} issues, {fixed} fixed"
        else:
            text = f"    {kind}: {state}"

        lines.append(Block.text(text, style, width=w))

    return lines


class FleetApp(Surface):
    def __init__(self):
        super().__init__(fps_cap=30, on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        self.vms, self.regions, self.globe = build_topology()
        self.vm_ticks: dict[str, Tick] = {}
        self.region_ticks: dict[str, Tick] = {}
        self.global_tick: Tick | None = None
        self.cycle = 0
        self.active_level: int | None = None
        self.log: deque[str] = deque(maxlen=10)

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        try:
            while True:
                self.cycle += 1

                # --- Facts arrive ---
                self.active_level = 0
                fact_log = generate_facts(self.cycle, self.vms)
                self.log.append(f"cycle {self.cycle}: {len(fact_log)} sources")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # --- L0: leaf vertices tick ---
                now = datetime.now(timezone.utc)
                for vm_name, vertex in self.vms.items():
                    tick = vertex.tick(vm_name, now)
                    self.vm_ticks[vm_name] = tick
                    self.regions[VM_REGION[vm_name]].receive(
                        Fact.of(tick.origin, **tick.payload), SYSTEM
                    )
                kinds_seen = set()
                for vm_name in self.vms:
                    kinds_seen.update(s.name for s, _ in VM_SHAPES[vm_name])
                self.log.append(f"  L0: {len(self.vms)} VMs ticked ({', '.join(sorted(kinds_seen))})")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # --- L1: region vertices tick ---
                self.active_level = 1
                for region_name, vertex in self.regions.items():
                    tick = vertex.tick(region_name, now)
                    self.region_ticks[region_name] = tick
                    self.globe.receive(Fact.of(tick.origin, **tick.payload), SYSTEM)
                self.log.append(f"  L1: {', '.join(sorted(self.regions))} ticked")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # --- L2: global ticks ---
                self.active_level = 2
                self.global_tick = self.globe.tick("global", now)
                self.log.append(f"  L2: global ticked")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # --- Idle ---
                self.active_level = None
                self.mark_dirty()
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            pass

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def _level_style(self, level: int) -> Style:
        return ACTIVE if self.active_level == level else DIM

    def render(self) -> None:
        if self._buf is None:
            return

        w = self._w
        blocks: list[Block] = []

        # -- Header --
        blocks.append(Block.text(f" fleet — cycle {self.cycle}", BOLD, width=w))

        # -- L0: Leaf vertices --
        l0_style = self._level_style(0)
        vm_lines: list[Block] = []
        for vm_name in sorted(self.vms):
            tick = self.vm_ticks.get(vm_name)
            vm_lines.extend(render_vm_tick(vm_name, tick, w - 6))

        l0_title = "L0: leaves"
        if self.active_level == 0:
            l0_title += " *"
        blocks.append(border(join_vertical(*vm_lines), title=l0_title, style=l0_style))

        # -- L1: Region vertices --
        l1_style = self._level_style(1)
        region_lines: list[Block] = []
        for region_name in sorted(self.regions):
            tick = self.region_ticks.get(region_name)
            if tick:
                vm_names = sorted(tick.payload.keys())
                # Show what kinds each VM brought
                parts = []
                for vn in vm_names:
                    vm_kinds = sorted(tick.payload[vn].keys())
                    parts.append(f"{vn}({','.join(vm_kinds)})")
                text = f"  {region_name}: {' | '.join(parts)}"
            else:
                text = f"  {region_name}: (waiting)"
            region_lines.append(Block.text(text, l1_style, width=w - 6))

        l1_title = "L1: regions"
        if self.active_level == 1:
            l1_title += " *"
        blocks.append(border(join_vertical(*region_lines), title=l1_title, style=l1_style))

        # -- L2: Global --
        l2_style = self._level_style(2)
        if self.global_tick:
            all_kinds: set[str] = set()
            total_vms = 0
            for region_data in self.global_tick.payload.values():
                for vm_data in region_data.values():
                    total_vms += 1
                    all_kinds.update(vm_data.keys())
            text = f"  global: {len(self.global_tick.payload)} regions, {total_vms} VMs, kinds: {', '.join(sorted(all_kinds))}"
        else:
            text = "  global: (waiting)"
        l2_title = "L2: global"
        if self.active_level == 2:
            l2_title += " *"
        blocks.append(border(Block.text(text, l2_style, width=w - 6), title=l2_title, style=l2_style))

        # -- Log --
        log_lines = [Block.text(f"  {e}", DIM, width=w - 6) for e in self.log]
        if log_lines:
            blocks.append(border(join_vertical(*log_lines), title="log", style=DIM))

        # -- Footer --
        blocks.append(Block.text(" q to quit", DIM, width=w))

        composed = join_vertical(*blocks)

        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        composed.paint(
            self._buf.region(0, 0, self._buf.width, self._buf.height),
            0, 0,
        )

    def on_key(self, key: str) -> None:
        if key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    async def _shutdown(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.quit()


# -- Main --------------------------------------------------------------------

async def main():
    app = FleetApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
