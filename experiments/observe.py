"""Feedback loop experiment: user interactions are Facts.

Closes the loop: keypress → emit() → on_emit → vertex.receive() →
fold → state → render → user. External timer facts and user
interaction facts enter the same Vertex through the same receive().

Peer constrains the loop:
  - potential gates what you can emit (on_emit checks)
  - horizon gates what you can see (render filters)

Two peers:
  kyle          — unrestricted operator (None = can do anything)
  kyle/monitor  — read-only navigator (focus only, can't ack)

Debug panel is a lens, not a peer. The 'd' key toggles rendering depth,
not access level. Any peer can view debug — it's a presentation
mode, not a data boundary.

1/2 selects peer directly. Fold doesn't know the source.

Run:
    uv run python experiments/observe.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque

from peers import Peer, delegate
from ticks import Vertex
from specs import Shape, Facet
from cells import Block, Style, join_vertical, join_horizontal, border
from cells.tui import Surface


# -- Shapes ------------------------------------------------------------------
# Four shapes, four kinds, one vertex. No boundary — continuous fold.

health_shape = Shape(
    name="health",
    about="Container health status per container",
    input_facets=(Facet("container", "str"), Facet("status", "str")),
    state_facets=(Facet("statuses", "dict"),),
)

focus_shape = Shape(
    name="focus",
    about="Observer cursor position",
    input_facets=(Facet("index", "int"),),
    state_facets=(Facet("index", "int"),),
)

ack_shape = Shape(
    name="ack",
    about="Acknowledged containers",
    input_facets=(Facet("container", "str"), Facet("peer", "str")),
    state_facets=(Facet("acked", "dict"),),
)

keys_shape = Shape(
    name="ui.key",
    about="Raw keystroke capture (infrastructure)",
    input_facets=(Facet("key", "str"),),
    state_facets=(Facet("keys", "list"), Facet("count", "int")),
)


# -- Folds -------------------------------------------------------------------
# All hand-written — none fit standard fold ops.

def health_fold(state: dict, payload: dict) -> dict:
    """Track per-container status."""
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


def focus_fold(state: dict, payload: dict) -> dict:
    """Set cursor index."""
    return {"index": payload.get("index", 0)}


def ack_fold(state: dict, payload: dict) -> dict:
    """Record which peer acknowledged which container."""
    acked = dict(state.get("acked", {}))
    acked[payload["container"]] = payload["peer"]
    return {"acked": acked}


def keys_fold(state: dict, payload: dict) -> dict:
    """Collect recent keystrokes. Infrastructure fold."""
    keys = list(state.get("keys", []))
    keys.append(payload["key"])
    return {"keys": keys[-20:], "count": state.get("count", 0) + 1}


# -- Topology ----------------------------------------------------------------

CONTAINERS = ["nginx", "api", "redis", "postgres", "worker"]
STATUSES = ["running", "running", "running", "unhealthy", "stopped"]

SHAPES: list[tuple[Shape, object]] = [
    (health_shape, health_fold),
    (focus_shape, focus_fold),
    (ack_shape, ack_fold),
    (keys_shape, keys_fold),
]


def build_vertex() -> Vertex:
    """One vertex, four fold engines. No boundary."""
    v = Vertex("observer")
    for shape, fold in SHAPES:
        v.register(shape.name, shape.initial_state(), fold)
    return v


# -- Peers -------------------------------------------------------------------

def build_peers() -> tuple[Peer, ...]:
    """kyle: unrestricted operator. monitor: can navigate but can't ack.

    Debug panel is a lens, not a peer. The 'd' key toggles rendering depth,
    not access level. Any peer can view debug — it's a presentation
    mode, not a data boundary. Two peers, not three.
    """
    kyle = Peer("kyle")  # unrestricted: horizon=None, potential=None
    monitor = delegate(kyle, "kyle/monitor", potential={"focus"})
    return (kyle, monitor)


# -- App ---------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
ACTIVE = Style(fg="cyan", bold=True)

STATUS_STYLE = {
    "running": Style(fg="green"),
    "unhealthy": Style(fg="yellow"),
    "stopped": Style(fg="red"),
}


class ObserveApp(Surface):
    """Feedback loop: user actions and external facts fold together."""

    def __init__(self):
        super().__init__(fps_cap=100, on_emit=self._make_bridge(), on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        self.vertex = build_vertex()
        self._trace: deque[str] = deque(maxlen=20)
        self._wrap_receive()

        self.peers = build_peers()
        self.peer_idx = 0
        self.log: deque[str] = deque(maxlen=8)
        self._debug_open = False
        self._debug_width = 0

    def _wrap_receive(self):
        """Instrument vertex.receive() — captures the full event stream."""
        real_receive = self.vertex.receive
        def traced(kind, payload):
            parts = " ".join(f"{k}={v}" for k, v in payload.items())
            self._trace.append(f"{kind}  {parts}")
            return real_receive(kind, payload)
        self.vertex.receive = traced

    @property
    def peer(self) -> Peer:
        return self.peers[self.peer_idx]

    def _make_bridge(self):
        """on_emit callback: potential gates which facts the peer can produce."""
        def on_emit(kind: str, data: dict) -> None:
            if self.peer.potential is not None and kind not in self.peer.potential:
                self.log.append(f"blocked: {self.peer.name} cannot emit '{kind}'")
                self.mark_dirty()
                return
            self.vertex.receive(kind, {**data, "peer": self.peer.name})
            self.log.append(f"{self.peer.name}: {kind}")
            self.mark_dirty()
        return on_emit

    # -- Lifecycle -----------------------------------------------------------

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        """External health facts — bypass on_emit, not the peer's actions."""
        try:
            while True:
                for c in CONTAINERS:
                    status = random.choice(STATUSES)
                    self.vertex.receive("health", {"container": c, "status": status})
                self.mark_dirty()
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass

    # -- Input ---------------------------------------------------------------

    def _visible_containers(self) -> list[str]:
        """Containers this peer can see, filtered by horizon."""
        if self.peer.horizon is None:
            return list(CONTAINERS)
        return [c for c in CONTAINERS if c in self.peer.horizon]

    def on_key(self, key: str) -> None:
        # Infrastructure: raw key capture, direct to vertex (like health timer).
        # Not the peer's action — no potential gating.
        self.vertex.receive("ui.key", {"key": key})

        visible = self._visible_containers()
        if not visible:
            if key in ("q", "escape"):
                asyncio.ensure_future(self._shutdown())
            return

        focus = self.vertex.state("focus")
        current = focus.get("index", 0)
        max_idx = len(visible) - 1

        if key == "j":
            self.emit("focus", index=min(current + 1, max_idx))
        elif key == "k":
            self.emit("focus", index=max(current - 1, 0))
        elif key in ("enter", "return"):
            idx = min(current, max_idx)
            self.emit("ack", container=visible[idx])
        elif key in ("1", "2", "3"):
            self._select_peer(int(key) - 1)
        elif key == "d":
            self._debug_open = not self._debug_open
            self.mark_dirty()
        elif key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    def _select_peer(self, idx: int):
        """Number key selects peer. Meta action — not a Fact."""
        if idx < 0 or idx >= len(self.peers):
            return
        if idx == self.peer_idx:
            return
        self.peer_idx = idx
        # Clamp focus to new peer's visible range
        visible = self._visible_containers()
        if visible:
            focus = self.vertex.state("focus")
            current = focus.get("index", 0)
            max_idx = len(visible) - 1
            if current > max_idx:
                self.emit("focus", index=max_idx)
        self.log.append(f"switched to {self.peer.name}")
        self.mark_dirty()

    async def _shutdown(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.quit()

    # -- Animation -----------------------------------------------------------

    def update(self) -> None:
        target = min(self._w * 2 // 5, 44) if self._debug_open else 0
        if self._debug_width != target:
            step = 4
            if self._debug_width < target:
                self._debug_width = min(self._debug_width + step, target)
            else:
                self._debug_width = max(self._debug_width - step, target)
            self.mark_dirty()

    # -- Rendering -----------------------------------------------------------

    def layout(self, width: int, height: int) -> None:
        self._w = width
        self._h = height

    def render(self) -> None:
        if self._buf is None:
            return

        w = self._w
        dw = self._debug_width
        body_w = w - dw
        peer = self.peer

        # Header spans full width
        header = self._render_header(w, peer)

        # Body splits horizontally: left (containers/log) | right (debug)
        body_left = self._render_body(body_w, peer)

        if dw >= 8:
            body_right = self._render_debug(dw, peer, body_left.height)
            body = join_horizontal(body_left, body_right)
        elif dw > 0:
            body = join_horizontal(body_left, Block.empty(dw, 1))
        else:
            body = body_left

        composed = join_vertical(header, body)

        self._buf.fill(0, 0, self._buf.width, self._buf.height, " ", Style())
        composed.paint(
            self._buf.region(0, 0, self._buf.width, self._buf.height),
            0, 0,
        )

    def _render_header(self, w: int, peer: Peer) -> Block:
        # Line 1: app name + peer selector
        selector_parts = []
        for i, p in enumerate(self.peers):
            tag = f" {i + 1}:{p.name} "
            if i == self.peer_idx:
                selector_parts.append(f"[{tag}]")
            else:
                selector_parts.append(f" {tag} ")
        line1 = Block.text(
            f" observe {''.join(selector_parts)}", BOLD, width=w,
        )

        # Line 2: potential (distinct color)
        potential_str = "*" if peer.potential is None else ", ".join(sorted(peer.potential)) or "none"
        line2 = Block.text(
            f" potential: {{{potential_str}}}",
            Style(fg="cyan"), width=w,
        )

        return join_vertical(line1, line2)

    def _render_body(self, w: int, peer: Peer) -> Block:
        inner = w - 6
        blocks: list[Block] = []

        # -- Container list --
        visible = self._visible_containers()
        focus = self.vertex.state("focus")
        current = min(focus.get("index", 0), max(len(visible) - 1, 0))
        health = self.vertex.state("health")
        statuses = health.get("statuses", {})
        ack_state = self.vertex.state("ack")
        acked = ack_state.get("acked", {})

        container_lines: list[Block] = []
        for i, name in enumerate(visible):
            cursor = ">" if i == current else " "
            status = statuses.get(name, "unknown")
            style = STATUS_STYLE.get(status, DIM)

            ack_mark = ""
            if name in acked:
                ack_mark = f"  [acked by {acked[name]}]"

            text = f"  {cursor} {name:<12} {status:<12}{ack_mark}"
            container_lines.append(Block.text(text, style, width=inner))

        if container_lines:
            blocks.append(border(
                join_vertical(*container_lines),
                title=f"containers ({len(visible)}/{len(CONTAINERS)})",
                style=DIM,
            ))
        else:
            blocks.append(border(
                Block.text("  (no containers in horizon)", DIM, width=inner),
                title="containers",
                style=DIM,
            ))

        # -- Log --
        if self.log:
            log_lines = [Block.text(f"  {e}", DIM, width=inner) for e in self.log]
            blocks.append(border(
                join_vertical(*log_lines), title="log", style=DIM,
            ))

        # -- Footer --
        blocks.append(Block.text(
            " j/k nav  enter ack  1/2 peer  d debug  q quit",
            DIM, width=w,
        ))

        return join_vertical(*blocks)

    def _render_debug(self, w: int, peer: Peer, target_h: int) -> Block:
        """Debug panel is a lens — rendering depth, not access control."""
        inner = w - 2  # border edges
        # border adds 2 rows; fill content to match body_left height
        content_h = max(target_h - 2, 1)

        lines: list[Block] = []

        # Fold engine versions — compact bar
        versions = "  ".join(
            f"{k}:v{self.vertex.version(k)}" for k in self.vertex.kinds
        )
        lines.append(Block.text(f" {versions}", DIM, width=inner))
        lines.append(Block.text("", DIM, width=inner))

        # Event trace — the raw stream
        lines.append(Block.text(
            " trace (vertex.receive)", BOLD, width=inner,
        ))
        if self._trace:
            for entry in self._trace:
                lines.append(Block.text(
                    f"  {entry}", Style(fg="cyan", dim=True), width=inner,
                ))
        else:
            lines.append(Block.text("  (waiting)", DIM, width=inner))

        # Pad to fill height
        while len(lines) < content_h:
            lines.append(Block.text("", DIM, width=inner))

        return border(
            join_vertical(*lines),
            title="debug (lens)", style=DIM,
        )


# -- Main --------------------------------------------------------------------

async def main():
    app = ObserveApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
