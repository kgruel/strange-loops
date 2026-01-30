"""Boundary-first fleet experiment.

Same domain (VMs, health, deploy, audit), inverted control: data fires
boundaries, not an external clock.

    vm-1 [health]              ── boundary ticks ──┐
                                                    ├──→ east (collect) ── boundary tick
    vm-2 [health + deploy]     ── boundary ticks ──┘

    vm-3 [audit]               ── boundary ticks ──┐
                                                    ├──→ west (collect) ── boundary tick
    vm-4 [health + audit]      ── boundary ticks ──┘

Three boundary semantics: health resets each window, deploy self-completes
only when stage reaches "done", audit accumulates across cycles.

Run:
    uv run python experiments/boundary.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque

from facts import Fact
from peers import Peer
from ticks import Tick, Vertex
from specs import Shape, Facet, Fold, Boundary
from cells import Block, Style, join_vertical, border
from cells.tui import Surface

# System peer — unrestricted, used for all fact emissions in this experiment.
SYSTEM = Peer("system")


# -- Shapes ------------------------------------------------------------------
# Shape descriptors define contracts AND boundary semantics.
# The composition point reads shape.boundary.kind / shape.boundary.reset
# to wire vertex.register().

health_shape = Shape(
    name="health",
    about="Container health observations",
    input_facets=(
        Facet("container", "str"),
        Facet("status", "str"),
    ),
    state_facets=(
        Facet("count", "int"),
        Facet("last", "str"),
        Facet("status", "str"),
    ),
    # No folds — hand-written fold (needs last-container-name logic)
    boundary=Boundary("health.close", reset=True),
)

deploy_shape = Shape(
    name="deploy",
    about="Deploy progression through stages",
    input_facets=(
        Facet("target", "str"),
        Facet("stage", "str"),
    ),
    state_facets=(
        Facet("target", "str"),
        Facet("stage", "str"),
        Facet("step", "int"),
    ),
    # No folds — hand-written fold (needs stage tracking logic)
    boundary=Boundary("deploy.done", reset=True),
)

audit_shape = Shape(
    name="audit",
    about="Audit scan results — accumulating",
    input_facets=(
        Facet("scanned", "int"),
        Facet("issues", "int"),
    ),
    state_facets=(
        Facet("scanned", "int"),
        Facet("issues", "int"),
        Facet("cycles", "int"),
    ),
    folds=(
        Fold("sum", "scanned", {"field": "scanned"}),
        Fold("sum", "issues", {"field": "issues"}),
        Fold("count", "cycles"),
    ),
    boundary=Boundary("audit.complete", reset=False),
)

collect_shape = Shape(
    name="collect",
    about="Collect L0 ticks into nested origin→kind structure",
    # No state_facets → initial_state() returns {}
    boundary=Boundary("region.close", reset=True),
)

ALL_SHAPES = [health_shape, deploy_shape, audit_shape, collect_shape]


# -- Folds -------------------------------------------------------------------

def health_fold(state: dict, payload: dict) -> dict:
    """Count observations, track last container + status. Hand-written."""
    return {
        "count": state.get("count", 0) + 1,
        "last": payload.get("container", "?"),
        "status": payload.get("status", "?"),
    }


def deploy_fold(state: dict, payload: dict) -> dict:
    """Track deploy target + stage + step count. Hand-written."""
    return {
        "target": payload.get("target", state.get("target", "")),
        "stage": payload.get("stage", state.get("stage", "")),
        "step": state.get("step", 0) + 1,
    }


def collect_fold(state: dict, payload: dict) -> dict:
    """Nest tick payload under origin → kind. Hand-written."""
    origin = payload.get("origin", "?")
    kind = payload.get("kind", "?")
    nested = dict(state)
    origin_dict = dict(nested.get(origin, {}))
    origin_dict[kind] = payload.get("data", {})
    nested[origin] = origin_dict
    return nested


# audit_fold = audit_shape.apply  (used directly below)


# -- Topology ----------------------------------------------------------------

VM_REGION = {"vm-1": "east", "vm-2": "east", "vm-3": "west", "vm-4": "west"}

# What each VM does — (shape, fold) pairs.
# shape.apply() for audit (ops fit), hand-written folds for health/deploy.
VM_SHAPES: dict[str, list[tuple[Shape, object]]] = {
    "vm-1": [
        (health_shape, health_fold),
    ],
    "vm-2": [
        (health_shape, health_fold),
        (deploy_shape, deploy_fold),
    ],
    "vm-3": [
        (audit_shape, audit_shape.apply),
    ],
    "vm-4": [
        (health_shape, health_fold),
        (audit_shape, audit_shape.apply),
    ],
}


def build_topology() -> tuple[dict[str, Vertex], dict[str, Vertex]]:
    """Wire vertices from Shape descriptors.

    The composition point reads shape.boundary.kind and shape.boundary.reset
    to configure vertex.register() — Shape drives wiring.
    """
    # L0: leaf vertices
    vms: dict[str, Vertex] = {}
    for vm_name, shapes in VM_SHAPES.items():
        v = Vertex(vm_name)
        for shape, fold in shapes:
            v.register(
                shape.name,
                shape.initial_state(),
                fold,
                boundary=shape.boundary.kind,
                reset=shape.boundary.reset,
            )
        vms[vm_name] = v

    # L1: region vertices — single "collect" engine per region
    regions: dict[str, Vertex] = {}
    for region_name in ("east", "west"):
        r = Vertex(region_name)
        r.register(
            collect_shape.name,
            collect_shape.initial_state(),
            collect_fold,
            boundary=collect_shape.boundary.kind,
            reset=collect_shape.boundary.reset,
        )
        regions[region_name] = r

    return vms, regions


# -- Fact generators ---------------------------------------------------------

CONTAINERS = {
    "vm-1": ["nginx", "api", "redis"],
    "vm-2": ["postgres", "worker"],
    "vm-4": ["grafana", "prometheus"],
}

STATUSES = ["running", "running", "running", "unhealthy", "stopped"]

DEPLOY_STAGES = ["build", "test", "done"]  # round 1→build, 2→test, 3→done


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


class BoundaryApp(Surface):
    """Live visualisation of the boundary cascade."""

    def __init__(self):
        super().__init__(fps_cap=30, on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        self.vms, self.regions = build_topology()
        self.round = 0
        self.phase = ""
        self.recent_ticks: set[tuple[str, str]] = set()
        self.l1_ticks: dict[str, Tick] = {}
        self.log: deque[str] = deque(maxlen=12)

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        try:
            while True:
                self.round += 1
                l0_ticks: list[Tick] = []
                self.recent_ticks = set()

                # Phase 1: health — feed health facts
                self.phase = "health"
                for vm_name, containers in CONTAINERS.items():
                    for c in containers:
                        status = random.choice(STATUSES)
                        f = Fact.of("health", container=c, status=status)
                        self.vms[vm_name].receive(f, SYSTEM)
                    self.log.append(f"{vm_name}: {len(containers)} health facts")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 2: health.close — sentinel → boundary ticks (resets)
                self.phase = "health.close"
                for vm_name in ("vm-1", "vm-2", "vm-4"):
                    tick = self.vms[vm_name].receive(Fact.of("health.close"), SYSTEM)
                    if tick:
                        l0_ticks.append(tick)
                        self.recent_ticks.add((vm_name, "health"))
                        self.log.append(
                            f"{vm_name} → health tick "
                            f"(count={tick.payload.get('count', 0)})"
                        )
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 3: deploy — feed deploy fact
                self.phase = "deploy"
                stage = DEPLOY_STAGES[(self.round - 1) % len(DEPLOY_STAGES)]
                f = Fact.of("deploy", target="api-v2.3", stage=stage)
                self.vms["vm-2"].receive(f, SYSTEM)
                self.log.append(f"vm-2: deploy stage={stage}")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 4: deploy.done — boundary only when stage=done
                self.phase = "deploy.done"
                if stage == "done":
                    tick = self.vms["vm-2"].receive(Fact.of("deploy.done"), SYSTEM)
                    if tick:
                        l0_ticks.append(tick)
                        self.recent_ticks.add(("vm-2", "deploy"))
                        self.log.append(
                            f"vm-2 → deploy tick "
                            f"(target={tick.payload.get('target', '?')})"
                        )
                else:
                    self.log.append(f"(deploy.done skipped — stage={stage})")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 5: audit — feed audit facts
                self.phase = "audit"
                for vm_name in ("vm-3", "vm-4"):
                    scanned = random.randint(10, 50)
                    issues = random.randint(0, 3)
                    f = Fact.of("audit", scanned=scanned, issues=issues)
                    self.vms[vm_name].receive(f, SYSTEM)
                    self.log.append(f"{vm_name}: audit +{scanned} scanned")
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 6: audit.complete — sentinel → boundary ticks (carries)
                self.phase = "audit.complete"
                for vm_name in ("vm-3", "vm-4"):
                    tick = self.vms[vm_name].receive(Fact.of("audit.complete"), SYSTEM)
                    if tick:
                        l0_ticks.append(tick)
                        self.recent_ticks.add((vm_name, "audit"))
                        self.log.append(
                            f"{vm_name} → audit tick "
                            f"(cycles={tick.payload.get('cycles', 0)})"
                        )
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Phase 7: L0→L1 — route ticks to regions, fire region.close
                self.phase = "L0→L1"
                for tick in l0_ticks:
                    region_name = VM_REGION[tick.origin]
                    self.regions[region_name].receive(
                        Fact.of("collect", origin=tick.origin, kind=tick.name, data=tick.payload),
                        SYSTEM
                    )
                for region_name, vertex in sorted(self.regions.items()):
                    tick = vertex.receive(Fact.of("region.close"), SYSTEM)
                    if tick:
                        self.l1_ticks[region_name] = tick
                        self.recent_ticks.add((region_name, "region"))
                        origins = sorted(tick.payload.keys())
                        parts = []
                        for o in origins:
                            kinds = sorted(tick.payload[o].keys())
                            parts.append(f"{o}({','.join(kinds)})")
                        self.log.append(
                            f"{region_name} → region tick: "
                            f"{' | '.join(parts)}"
                        )
                self.mark_dirty()
                await asyncio.sleep(DELAY)

                # Idle
                self.phase = ""
                self.recent_ticks = set()
                self.mark_dirty()
                await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            pass

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def render(self) -> None:
        if self._buf is None:
            return

        w = self._w
        blocks: list[Block] = []

        # -- Header --
        phase_text = f"  [{self.phase}]" if self.phase else ""
        blocks.append(Block.text(
            f" boundary — round {self.round}{phase_text}",
            BOLD if self.phase else DIM,
            width=w,
        ))

        # -- L0: VMs --
        vm_lines: list[Block] = []
        inner = w - 6
        for vm_name in sorted(self.vms):
            kinds = [s.name for s, _ in VM_SHAPES[vm_name]]
            kind_tags = " ".join(f"[{k}]" for k in kinds)
            vm_lines.append(Block.text(
                f"  {vm_name} {kind_tags}", BOLD, width=inner,
            ))

            for kind in kinds:
                state = self.vms[vm_name].state(kind)
                style = KIND_STYLE.get(kind, DIM)
                ticked = (vm_name, kind) in self.recent_ticks

                if kind == "health":
                    count = state.get("count", 0)
                    last = state.get("last", "?")
                    status = state.get("status", "?")
                    text = f"    health: {count} obs, last={last} ({status})"
                elif kind == "deploy":
                    target = state.get("target", "")
                    stage = state.get("stage", "")
                    step = state.get("step", 0)
                    text = f"    deploy: {target} [{stage}] step {step}"
                elif kind == "audit":
                    scanned = state.get("scanned", 0)
                    issues = state.get("issues", 0)
                    cycles = state.get("cycles", 0)
                    text = f"    audit: {scanned} scanned, {issues} issues, {cycles} cycles"
                else:
                    text = f"    {kind}: {state}"

                if ticked:
                    marker = " ← tick"
                    text = text.ljust(inner - len(marker)) + marker
                    style = ACTIVE

                vm_lines.append(Block.text(text, style, width=inner))

        blocks.append(border(
            join_vertical(*vm_lines), title="L0: VMs", style=DIM,
        ))

        # -- L1: regions --
        region_lines: list[Block] = []
        for region_name in sorted(self.regions):
            tick = self.l1_ticks.get(region_name)
            ticked = (region_name, "region") in self.recent_ticks

            if tick:
                origins = sorted(tick.payload.keys())
                parts = []
                for o in origins:
                    okinds = sorted(tick.payload[o].keys())
                    parts.append(f"{o}({','.join(okinds)})")
                text = f"  {region_name}: {' | '.join(parts)}"
            else:
                text = f"  {region_name}: (waiting)"

            if ticked:
                marker = " ← tick"
                text = text.ljust(inner - len(marker)) + marker
                style = ACTIVE
            else:
                style = DIM

            region_lines.append(Block.text(text, style, width=inner))

        blocks.append(border(
            join_vertical(*region_lines), title="L1: regions", style=DIM,
        ))

        # -- Log --
        log_lines = [
            Block.text(f"  {e}", DIM, width=inner)
            for e in self.log
        ]
        if log_lines:
            blocks.append(border(
                join_vertical(*log_lines), title="log", style=DIM,
            ))

        # -- Footer --
        blocks.append(Block.text(" q to quit", DIM, width=w))

        composed = join_vertical(*blocks)

        self._buf.fill(
            0, 0, self._buf.width, self._buf.height, " ", Style(),
        )
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
    random.seed(42)
    app = BoundaryApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
