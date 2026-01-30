"""Peer-aware Surface integration: Vertex.receive(Fact, Peer) in a live TUI.

The full pipeline: Peer observes -> Fact -> Vertex (with gating) -> Surface -> user sees result.

Key differences from observe.py:
- Uses Vertex.receive(fact, peer) with explicit Fact objects
- Observer-state kinds: focus.{peer} enforces ownership (each peer owns their cursor)
- Gating is visual: blocked actions show in the TUI log

Scenario: Three peers with different potentials
  - kyle: unrestricted operator (root)
  - alice: can see/do health + focus.alice
  - bob: can only do focus.bob, can see focus.* (read alice's focus)

Run:
    uv run python experiments/peer_surface.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque

from facts import Fact
from peers import Peer, delegate
from ticks import Lens, Tick, Vertex
from cells import Block, Style, join_vertical, join_horizontal, border
from cells.tui import Surface


# -- Folds -------------------------------------------------------------------


def health_fold(state: dict, payload: dict) -> dict:
    """Track per-container status."""
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


def focus_fold(state: dict, payload: dict) -> dict:
    """Track focus index for a specific peer."""
    return {"index": payload.get("index", 0)}


def ack_fold(state: dict, payload: dict) -> dict:
    """Record which peer acknowledged which container."""
    acked = dict(state.get("acked", {}))
    acked[payload["container"]] = payload.get("peer", "?")
    return {"acked": acked}


def keys_fold(state: dict, payload: dict) -> dict:
    """Collect recent keystrokes. Infrastructure fold."""
    keys = list(state.get("keys", []))
    keys.append(payload["key"])
    return {"keys": keys[-20:], "count": state.get("count", 0) + 1}


# -- Topology ----------------------------------------------------------------

CONTAINERS = ["nginx", "api", "redis", "postgres", "worker"]
STATUSES = ["running", "running", "running", "unhealthy", "stopped"]


def build_vertex() -> Vertex:
    """One vertex, multiple fold engines with observer-state ownership.

    - health: shared state (any peer with potential can update)
    - focus.{peer}: observer state (ownership enforced by Vertex)
    - ack: shared (tracks who acked what)
    - ui.key: infrastructure (bypass gating)
    """
    v = Vertex("peer-surface")

    # Shared state
    v.register("health", {"statuses": {}}, health_fold, boundary="health.close", reset=True)
    v.register("ack", {"acked": {}}, ack_fold)
    v.register("ui.key", {"keys": [], "count": 0}, keys_fold)

    # Per-peer observer state
    v.register("focus.kyle", {"index": 0}, focus_fold)
    v.register("focus.alice", {"index": 0}, focus_fold)
    v.register("focus.bob", {"index": 0}, focus_fold)

    return v


def build_peers() -> dict[str, Peer]:
    """Three peers with different permissions.

    kyle: unrestricted (root operator)
    alice: health + focus.alice
    bob: focus.bob only (can see alice's focus but not update it)
    """
    kyle = Peer("kyle")  # unrestricted

    # Alice can see and do health + her own focus + ack
    alice = delegate(
        kyle, "alice",
        potential={"health", "health.close", "focus.alice", "ack"},
        horizon={"health", "focus.alice"},
    )

    # Bob can only manage his own focus
    bob = delegate(
        kyle, "bob",
        potential={"focus.bob"},
        horizon={"focus.bob", "focus.alice"},  # can see alice's focus but not update it
    )

    return {"kyle": kyle, "alice": alice, "bob": bob}


# -- App ---------------------------------------------------------------------

DIM = Style(dim=True)
BOLD = Style(bold=True)
ACTIVE = Style(fg="cyan", bold=True)
BLOCKED = Style(fg="red", dim=True)
ALLOWED = Style(fg="green", dim=True)

STATUS_STYLE = {
    "running": Style(fg="green"),
    "unhealthy": Style(fg="yellow"),
    "stopped": Style(fg="red"),
}


class PeerSurfaceApp(Surface):
    """Peer-aware Surface: Vertex.receive(Fact, Peer) with explicit gating."""

    def __init__(self):
        super().__init__(fps_cap=60, on_emit=self._make_bridge(), on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        self.vertex = build_vertex()
        self.peers = build_peers()
        self.peer_names = ["kyle", "alice", "bob"]
        self.peer_idx = 0

        self.log: deque[str] = deque(maxlen=10)
        self._trace: deque[tuple[str, str, bool]] = deque(maxlen=15)  # (peer, kind, allowed)
        self._debug_open = True
        self._debug_width = 0

    @property
    def peer(self) -> Peer:
        return self.peers[self.peer_names[self.peer_idx]]

    def _focus_kind(self) -> str:
        """Current peer's focus kind."""
        return f"focus.{self.peer.name}"

    def _make_bridge(self):
        """Bridge: Surface.emit() -> Fact -> Vertex.receive(fact, peer).

        This is where the model connects to the TUI. Every user action
        becomes a Fact with explicit Peer, routed through the Vertex.
        """
        def on_emit(kind: str, data: dict) -> None:
            fact = Fact.of(kind, **data)
            result = self.vertex.receive(fact, self.peer)

            # Track for visualization
            allowed = self._was_allowed(kind, result)
            self._trace.append((self.peer.name, kind, allowed))

            if allowed:
                self.log.append(f"{self.peer.name}: {kind}")
            else:
                self.log.append(f"BLOCKED {self.peer.name}: {kind}")

            self.mark_dirty()
        return on_emit

    def _was_allowed(self, kind: str, result: Tick | None) -> bool:
        """Determine if a fact was allowed (folded or boundary triggered).

        If result is a Tick, a boundary fired — allowed.
        If result is None, check: was it blocked by potential or observer ownership?
        """
        # If a Tick was returned, it was definitely allowed (boundary fired)
        if result is not None:
            return True

        # Check potential
        if self.peer.potential is not None and kind not in self.peer.potential:
            return False

        # Check observer-state ownership
        import re
        match = re.match(r"^(focus|scroll|selection)\.(.+)$", kind)
        if match:
            owner = match.group(2)
            if owner != self.peer.name:
                return False

        # Otherwise it was allowed (no boundary, but folded)
        return True

    # -- Lifecycle -----------------------------------------------------------

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        """External health facts — system source, uses root peer."""
        root = self.peers["kyle"]
        try:
            while True:
                for c in CONTAINERS:
                    status = random.choice(STATUSES)
                    fact = Fact.of("health", container=c, status=status)
                    self.vertex.receive(fact, root)
                self.mark_dirty()
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass

    # -- Input ---------------------------------------------------------------

    def on_key(self, key: str) -> None:
        # Infrastructure: raw key capture, direct to vertex as root (no gating)
        root = self.peers["kyle"]
        self.vertex.receive(Fact.of("ui.key", key=key), root)

        focus_state = self.vertex.state(self._focus_kind())
        current = focus_state.get("index", 0)
        max_idx = len(CONTAINERS) - 1

        if key == "j":
            # Emit to this peer's focus kind
            self.emit(self._focus_kind(), index=min(current + 1, max_idx))
        elif key == "k":
            self.emit(self._focus_kind(), index=max(current - 1, 0))
        elif key in ("enter", "return"):
            idx = min(current, max_idx)
            self.emit("ack", container=CONTAINERS[idx], peer=self.peer.name)
        elif key == "c":
            # Try to fire health boundary (only some peers can)
            self.emit("health.close")
        elif key in ("1", "2", "3"):
            self._select_peer(int(key) - 1)
        elif key == "d":
            self._debug_open = not self._debug_open
            self.mark_dirty()
        elif key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    def _select_peer(self, idx: int):
        """Number key selects peer. Meta action — not a Fact."""
        if idx < 0 or idx >= len(self.peer_names):
            return
        if idx == self.peer_idx:
            return
        self.peer_idx = idx
        self.log.append(f"-> {self.peer.name}")
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
        target = min(self._w * 2 // 5, 50) if self._debug_open else 0
        if self._debug_width != target:
            step = 6
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

        header = self._render_header(w, peer)
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
        for i, name in enumerate(self.peer_names):
            tag = f" {i + 1}:{name} "
            if i == self.peer_idx:
                selector_parts.append(f"[{tag}]")
            else:
                selector_parts.append(f" {tag} ")
        line1 = Block.text(f" peer_surface {''.join(selector_parts)}", BOLD, width=w)

        # Line 2: potential
        potential_str = "*" if peer.potential is None else ", ".join(sorted(peer.potential)) or "none"
        line2 = Block.text(f" potential: {{{potential_str}}}", Style(fg="cyan"), width=w)

        # Line 3: horizon
        horizon_str = "*" if peer.horizon is None else ", ".join(sorted(peer.horizon)) or "none"
        line3 = Block.text(f" horizon:   {{{horizon_str}}}", Style(fg="magenta"), width=w)

        return join_vertical(line1, line2, line3)

    def _render_body(self, w: int, peer: Peer) -> Block:
        inner = w - 4
        blocks: list[Block] = []

        # -- Container list with per-peer focus --
        focus_state = self.vertex.state(self._focus_kind())
        current = focus_state.get("index", 0)
        health = self.vertex.state("health")
        statuses = health.get("statuses", {})
        ack_state = self.vertex.state("ack")
        acked = ack_state.get("acked", {})

        container_lines: list[Block] = []
        for i, name in enumerate(CONTAINERS):
            cursor = ">" if i == current else " "
            status = statuses.get(name, "unknown")
            style = STATUS_STYLE.get(status, DIM)

            ack_mark = ""
            if name in acked:
                ack_mark = f"  [acked: {acked[name]}]"

            text = f" {cursor} {name:<12} {status:<12}{ack_mark}"
            container_lines.append(Block.text(text, style, width=inner))

        blocks.append(border(
            join_vertical(*container_lines),
            title=f"containers (focus.{peer.name})",
            style=DIM,
        ))

        # -- Log --
        if self.log:
            log_lines = []
            for e in self.log:
                style = BLOCKED if e.startswith("BLOCKED") else DIM
                log_lines.append(Block.text(f" {e}", style, width=inner))
            blocks.append(border(join_vertical(*log_lines), title="log", style=DIM))

        # -- Footer --
        blocks.append(Block.text(
            " j/k nav  enter ack  c close  1/2/3 peer  d debug  q quit",
            DIM, width=w,
        ))

        return join_vertical(*blocks)

    def _render_debug(self, w: int, peer: Peer, target_h: int) -> Block:
        """Debug panel: gating trace + fold state."""
        inner = w - 2
        content_h = max(target_h - 2, 1)
        lines: list[Block] = []

        # Per-peer focus state
        lines.append(Block.text(" focus state:", BOLD, width=inner))
        for name in self.peer_names:
            focus = self.vertex.state(f"focus.{name}")
            idx = focus.get("index", 0)
            marker = " *" if name == peer.name else ""
            lines.append(Block.text(f"  focus.{name}: {idx}{marker}", DIM, width=inner))

        lines.append(Block.text("", DIM, width=inner))

        # Gating trace
        lines.append(Block.text(" gating trace:", BOLD, width=inner))
        for (pname, kind, allowed) in self._trace:
            mark = "+" if allowed else "X"
            style = ALLOWED if allowed else BLOCKED
            lines.append(Block.text(f"  {mark} {pname}: {kind}", style, width=inner))

        # Pad
        while len(lines) < content_h:
            lines.append(Block.text("", DIM, width=inner))

        return border(join_vertical(*lines), title="debug", style=DIM)


# -- Main --------------------------------------------------------------------

async def main():
    app = PeerSurfaceApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
