"""Lens as primitive experiment.

Copy of review.py with Lens atom added. Tests the hypothesis:

    Lens = zoom + scope
    - zoom: int — detail level (0=minimal, 1=summary, 2=full)
    - scope: frozenset[str] | None — visible kinds (None=all)

The render function is NOT part of the primitive. Surface applies zoom.
Same pattern as Peer (has horizon, Vertex enforces).

New in this version:
    - scope: filters which kinds appear in trace (presentation, not access)
    - lens per peer: each peer has a default lens, switching peers applies it

Key mappings:
    d       toggle debug panel (zoom > 0)
    -/=     decrease/increase zoom
    s       cycle scope presets (all → domain → infra → all)
    1/2     switch peer (applies peer's default lens)

Run:
    uv run python experiments/review_lens.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass

import json
import time
from pathlib import Path

from facts import Fact
from peers import Peer, delegate
from ticks import Tick, Vertex
from shapes import Shape, Facet, Boundary
from cells import Block, Style, join_vertical, join_horizontal, border
from cells.tui import Surface

# System peer — unrestricted, for infrastructure facts (health timer, raw keys).
SYSTEM = Peer("system")


# -- Lens primitive ----------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Lens:
    """View configuration — how content is rendered, not what content exists.

    zoom: detail level. 0=minimal, 1=summary, 2=full, 3+=verbose
    scope: visible kinds. None=all, frozenset=filtered

    Lens is orthogonal to Peer:
        - Peer.horizon gates what data you CAN see (access)
        - Lens.scope gates what data you DO see (presentation)
        - Peer.potential gates what you can emit (capability)
        - Lens.zoom controls rendering depth (detail)
    """

    zoom: int = 1
    scope: frozenset[str] | None = None

    def with_zoom(self, zoom: int) -> Lens:
        """Return new Lens with adjusted zoom."""
        return Lens(zoom=max(0, zoom), scope=self.scope)

    def with_scope(self, scope: frozenset[str] | None) -> Lens:
        """Return new Lens with adjusted scope."""
        return Lens(zoom=self.zoom, scope=scope)

    def includes(self, kind: str) -> bool:
        """Check if kind is visible through this lens."""
        if self.scope is None:
            return True
        return kind in self.scope


# Scope presets for cycling
SCOPE_ALL: frozenset[str] | None = None
SCOPE_DOMAIN: frozenset[str] = frozenset({"health", "ack", "focus", "review.complete", "health.close"})
SCOPE_INFRA: frozenset[str] = frozenset({"ui.key", "lens"})
SCOPE_PRESETS: list[tuple[str, frozenset[str] | None]] = [
    ("all", SCOPE_ALL),
    ("domain", SCOPE_DOMAIN),
    ("infra", SCOPE_INFRA),
]


# -- Shapes ------------------------------------------------------------------

health_shape = Shape(
    name="health",
    about="Container health status per container",
    input_facets=(Facet("container", "str"), Facet("status", "str")),
    state_facets=(Facet("statuses", "dict"),),
    boundary=Boundary("health.close", reset=True),
)

focus_shape = Shape(
    name="focus",
    about="Observer cursor position",
    input_facets=(Facet("index", "int"),),
    state_facets=(Facet("index", "int"),),
)

ack_shape = Shape(
    name="ack",
    about="Acknowledged containers this review cycle",
    input_facets=(Facet("container", "str"), Facet("peer", "str")),
    state_facets=(Facet("acked", "dict"),),
    boundary=Boundary("review.complete", reset=True),
)

keys_shape = Shape(
    name="ui.key",
    about="Raw keystroke capture (infrastructure)",
    input_facets=(Facet("key", "str"),),
    state_facets=(Facet("keys", "list"), Facet("count", "int")),
)

# NEW: lens shape — lens changes are facts
lens_shape = Shape(
    name="lens",
    about="View configuration (zoom + scope)",
    input_facets=(Facet("zoom", "int"), Facet("scope", "str")),  # scope as preset name
    state_facets=(Facet("zoom", "int"), Facet("scope_name", "str")),
)


# -- Folds -------------------------------------------------------------------

def health_fold(state: dict, payload: dict) -> dict:
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


def focus_fold(state: dict, payload: dict) -> dict:
    return {"index": payload.get("index", 0)}


def ack_fold(state: dict, payload: dict) -> dict:
    acked = dict(state.get("acked", {}))
    acked[payload["container"]] = payload["peer"]
    return {"acked": acked}


def keys_fold(state: dict, payload: dict) -> dict:
    keys = list(state.get("keys", []))
    keys.append(payload["key"])
    return {"keys": keys[-20:], "count": state.get("count", 0) + 1}


def lens_fold(state: dict, payload: dict) -> dict:
    """Lens changes fold into state. Zoom and scope are independent dimensions."""
    return {
        "zoom": payload.get("zoom", state.get("zoom", 1)),
        "scope_name": payload.get("scope", state.get("scope_name", "all")),
    }


# -- Topology ----------------------------------------------------------------

CONTAINERS = ["nginx", "api", "redis", "postgres", "worker"]
STATUSES = ["running", "running", "running", "unhealthy", "stopped"]

SHAPES: list[tuple[Shape, object]] = [
    (health_shape, health_fold),
    (focus_shape, focus_fold),
    (ack_shape, ack_fold),
    (keys_shape, keys_fold),
    (lens_shape, lens_fold),
]


def build_vertex() -> Vertex:
    v = Vertex("reviewer")
    for shape, fold in SHAPES:
        if shape.boundary is not None:
            v.register(
                shape.name,
                shape.initial_state(),
                fold,
                boundary=shape.boundary.kind,
                reset=shape.boundary.reset,
            )
        else:
            v.register(shape.name, shape.initial_state(), fold)
    return v


# -- Peers -------------------------------------------------------------------

# Default lens per peer — orthogonal to horizon/potential
# kyle (operator): full zoom, all kinds
# monitor: summary zoom, domain only (no infra noise)
PEER_LENS: dict[str, Lens] = {
    "kyle": Lens(zoom=2, scope=None),
    "kyle/monitor": Lens(zoom=1, scope=SCOPE_DOMAIN),
}


def build_peers() -> tuple[Peer, ...]:
    kyle = Peer("kyle")
    monitor = delegate(kyle, "kyle/monitor", potential={"focus", "lens"})
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

# Zoom level labels
ZOOM_LABELS = {0: "minimal", 1: "summary", 2: "full", 3: "verbose"}


class ReviewLensApp(Surface):
    """Review app with Lens as first-class primitive."""

    def __init__(self):
        super().__init__(fps_cap=100, on_emit=self._make_bridge(), on_start=self._start)
        self._w = 80
        self._h = 24
        self._task: asyncio.Task | None = None

        self.vertex = build_vertex()
        self._trace: deque[str] = deque(maxlen=20)

        self._facts_replayed = self._replay_facts()

        self._fact_log = Path("review_lens.jsonl").open("a")
        self._tick_log = Path("review_lens.ticks.jsonl").open("a")

        self._wrap_receive()

        self.peers = build_peers()
        self.peer_idx = 0
        self.log: deque[str] = deque(maxlen=8)

        # Lens state — derived from vertex, cached for rendering
        self._lens = Lens(zoom=1)

        # Debug panel animation (width slides based on zoom > 0)
        self._debug_width = 0

        self.review_ticks: list[Tick] = []
        self.health_ticks: list[Tick] = []
        self._load_ticks()
        self._tick_flash: str = ""
        self._tick_flash_ttl: int = 0

        if self._facts_replayed > 0:
            self.log.append(f"replayed {self._facts_replayed} facts")
        if self.review_ticks or self.health_ticks:
            self.log.append(f"restored {len(self.review_ticks)}r + {len(self.health_ticks)}h ticks")

    def _replay_facts(self) -> int:
        fact_path = Path("review_lens.jsonl")
        if not fact_path.exists():
            return 0

        count = 0
        for line in fact_path.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                self.vertex.receive(Fact.of(data["kind"], **data["payload"]), SYSTEM)
                count += 1
            except (json.JSONDecodeError, KeyError):
                continue

        return count

    def _load_ticks(self):
        tick_path = Path("review_lens.ticks.jsonl")
        if not tick_path.exists():
            return

        from datetime import datetime, timezone

        for line in tick_path.read_text().strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                tick = Tick(
                    name=data["name"],
                    ts=datetime.fromtimestamp(data["ts"], tz=timezone.utc),
                    payload=data["payload"],
                    origin=data.get("origin", ""),
                )
                if tick.name == "health":
                    self.health_ticks.append(tick)
                elif tick.name == "ack":
                    self.review_ticks.append(tick)
            except (json.JSONDecodeError, KeyError):
                continue

    def _wrap_receive(self):
        real_receive = self.vertex.receive

        def traced(fact: Fact, peer: Peer):
            ts = time.time()

            self._fact_log.write(json.dumps({"ts": ts, "kind": fact.kind, "payload": dict(fact.payload)}) + "\n")
            self._fact_log.flush()

            result = real_receive(fact, peer)
            if result is not None:
                self._trace.append(f"{fact.kind} → TICK {result.name}")

                self._tick_log.write(json.dumps({
                    "ts": result.ts.timestamp(),
                    "name": result.name,
                    "origin": result.origin,
                    "payload": result.payload,
                }) + "\n")
                self._tick_log.flush()
            else:
                parts = " ".join(f"{k}={v}" for k, v in fact.payload.items())
                self._trace.append(f"{fact.kind}  {parts}")
            return result

        self.vertex.receive = traced

    @property
    def peer(self) -> Peer:
        return self.peers[self.peer_idx]

    @property
    def lens(self) -> Lens:
        """Current lens from vertex state."""
        state = self.vertex.state("lens")
        zoom = state.get("zoom", 1)
        scope_name = state.get("scope_name", "all")
        # Resolve scope name to actual frozenset
        scope = next((s for name, s in SCOPE_PRESETS if name == scope_name), None)
        return Lens(zoom=zoom, scope=scope)

    @property
    def scope_name(self) -> str:
        """Current scope preset name."""
        state = self.vertex.state("lens")
        return state.get("scope_name", "all")

    def _make_bridge(self):
        def on_emit(kind: str, data: dict) -> None:
            if self.peer.potential is not None and kind not in self.peer.potential:
                self.log.append(f"blocked: {self.peer.name} cannot emit '{kind}'")
                self.mark_dirty()
                return
            self.vertex.receive(Fact.of(kind, **data, peer=self.peer.name), self.peer)
            self.log.append(f"{self.peer.name}: {kind}")

            if kind == "ack":
                acked = self.vertex.state("ack").get("acked", {})
                if len(acked) >= len(CONTAINERS) and all(
                    c in acked for c in CONTAINERS
                ):
                    tick = self.vertex.receive(Fact.of("review.complete"), self.peer)
                    if tick:
                        self.review_ticks.append(tick)
                        n = len(self.review_ticks)
                        count = len(tick.payload.get("acked", {}))
                        self.log.append(f"→ Review #{n} complete! ({count} acked)")
                        self._tick_flash = f"Review #{n} complete"
                        self._tick_flash_ttl = 8

            self.mark_dirty()
        return on_emit

    # -- Lifecycle -----------------------------------------------------------

    async def _start(self):
        self._task = asyncio.create_task(self._source())

    async def _source(self):
        try:
            while True:
                for c in CONTAINERS:
                    status = random.choice(STATUSES)
                    self.vertex.receive(Fact.of("health", container=c, status=status), SYSTEM)

                tick = self.vertex.receive(Fact.of("health.close"), SYSTEM)
                if tick:
                    self.health_ticks.append(tick)
                    n = len(self.health_ticks)
                    count = len(tick.payload.get("statuses", {}))
                    self.log.append(f"health #{n}: {count} containers")

                self.mark_dirty()
                await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            pass

    # -- Input ---------------------------------------------------------------

    def _visible_containers(self) -> list[str]:
        if self.peer.horizon is None:
            return list(CONTAINERS)
        return [c for c in CONTAINERS if c in self.peer.horizon]

    def on_key(self, key: str) -> None:
        self.vertex.receive(Fact.of("ui.key", key=key), SYSTEM)

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
        # -- Lens controls --
        elif key == "d":
            # Toggle: if zoom > 0, go to 0; else go to 2
            current_zoom = self.lens.zoom
            new_zoom = 0 if current_zoom > 0 else 2
            self.emit("lens", zoom=new_zoom)
        elif key == "-":
            self.emit("lens", zoom=max(0, self.lens.zoom - 1))
        elif key == "=":
            self.emit("lens", zoom=min(3, self.lens.zoom + 1))
        elif key == "`":
            self.emit("lens", zoom=0)
        elif key == "s":
            # Cycle scope presets
            current_name = self.scope_name
            current_idx = next((i for i, (name, _) in enumerate(SCOPE_PRESETS) if name == current_name), 0)
            next_idx = (current_idx + 1) % len(SCOPE_PRESETS)
            next_name = SCOPE_PRESETS[next_idx][0]
            self.emit("lens", scope=next_name)
            self.log.append(f"scope: {next_name}")
        elif key in ("q", "escape"):
            asyncio.ensure_future(self._shutdown())

    def _select_peer(self, idx: int):
        if idx < 0 or idx >= len(self.peers):
            return
        if idx == self.peer_idx:
            return
        self.peer_idx = idx
        visible = self._visible_containers()
        if visible:
            focus = self.vertex.state("focus")
            current = focus.get("index", 0)
            max_idx = len(visible) - 1
            if current > max_idx:
                self.emit("focus", index=max_idx)

        # Apply peer's default lens
        peer_name = self.peer.name
        if peer_name in PEER_LENS:
            default_lens = PEER_LENS[peer_name]
            scope_name = next((name for name, s in SCOPE_PRESETS if s == default_lens.scope), "all")
            self.emit("lens", zoom=default_lens.zoom, scope=scope_name)
            self.log.append(f"switched to {peer_name} (lens: z{default_lens.zoom}/{scope_name})")
        else:
            self.log.append(f"switched to {peer_name}")
        self.mark_dirty()

    async def _shutdown(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._fact_log.close()
        self._tick_log.close()
        self.quit()

    # -- Animation -----------------------------------------------------------

    def update(self) -> None:
        # Debug panel slides based on lens.zoom
        zoom = self.lens.zoom
        target = min(self._w * 2 // 5, 44) if zoom >= 2 else 0
        if self._debug_width != target:
            step = 4
            if self._debug_width < target:
                self._debug_width = min(self._debug_width + step, target)
            else:
                self._debug_width = max(self._debug_width - step, target)
            self.mark_dirty()

        if self._tick_flash_ttl > 0:
            self._tick_flash_ttl -= 1
            if self._tick_flash_ttl == 0:
                self._tick_flash = ""
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
        lens = self.lens

        header = self._render_header(w, peer, lens)

        body_left = self._render_body(body_w, peer, lens)

        if dw >= 8:
            body_right = self._render_debug(dw, peer, lens, body_left.height)
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

    def _render_header(self, w: int, peer: Peer, lens: Lens) -> Block:
        review_n = len(self.review_ticks)
        health_n = len(self.health_ticks)
        selector_parts = []
        for i, p in enumerate(self.peers):
            tag = f" {i + 1}:{p.name} "
            if i == self.peer_idx:
                selector_parts.append(f"[{tag}]")
            else:
                selector_parts.append(f" {tag} ")

        # Show lens zoom and scope in header
        zoom_label = ZOOM_LABELS.get(lens.zoom, f"z{lens.zoom}")
        scope_label = self.scope_name
        line1 = Block.text(
            f" review-lens — cycle {review_n + 1}  health #{health_n}  lens:{zoom_label}/{scope_label}{''.join(selector_parts)}",
            BOLD, width=w,
        )

        potential_str = "*" if peer.potential is None else ", ".join(sorted(peer.potential)) or "none"
        flash = f"  │ {self._tick_flash}" if self._tick_flash else ""
        line2 = Block.text(
            f" potential: {{{potential_str}}}{flash}",
            ACTIVE if self._tick_flash else Style(fg="cyan"),
            width=w,
        )

        return join_vertical(line1, line2)

    def _render_body(self, w: int, peer: Peer, lens: Lens) -> Block:
        inner = w - 6
        blocks: list[Block] = []

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

            # Lens.zoom controls detail level
            if lens.zoom == 0:
                # Minimal: just name
                text = f"  {cursor} {name}"
            elif lens.zoom == 1:
                # Summary: name + status
                text = f"  {cursor} {name:<12} {status}"
            else:
                # Full: name + status + ack info
                ack_mark = ""
                if name in acked:
                    ack_mark = f"  [acked by {acked[name]}]"
                text = f"  {cursor} {name:<12} {status:<12}{ack_mark}"

            container_lines.append(Block.text(text, style, width=inner))

        ack_progress = f"{len(acked)}/{len(CONTAINERS)}"
        if container_lines:
            blocks.append(border(
                join_vertical(*container_lines),
                title=f"containers ({len(visible)}/{len(CONTAINERS)}) acked {ack_progress}",
                style=DIM,
            ))
        else:
            blocks.append(border(
                Block.text("  (no containers in horizon)", DIM, width=inner),
                title="containers",
                style=DIM,
            ))

        # Ticks — show more at higher zoom
        all_ticks = []
        for t in self.review_ticks:
            count = len(t.payload.get("acked", {}))
            all_ticks.append((t.ts, f"review: {count} acked"))
        for t in self.health_ticks:
            count = len(t.payload.get("statuses", {}))
            all_ticks.append((t.ts, f"health: {count} containers"))
        all_ticks.sort(key=lambda x: x[0], reverse=True)

        if lens.zoom >= 1 and all_ticks:
            tick_limit = 3 if lens.zoom == 1 else 6
            tick_lines = [
                Block.text(f"  {desc}", DIM, width=inner)
                for _, desc in all_ticks[:tick_limit]
            ]
            blocks.append(border(
                join_vertical(*tick_lines),
                title=f"ticks ({len(self.review_ticks)}r + {len(self.health_ticks)}h)",
                style=DIM,
            ))

        # Log — only at zoom >= 1
        if lens.zoom >= 1 and self.log:
            log_limit = 4 if lens.zoom == 1 else 8
            log_lines = [Block.text(f"  {e}", DIM, width=inner) for e in list(self.log)[-log_limit:]]
            blocks.append(border(
                join_vertical(*log_lines), title="log", style=DIM,
            ))

        # Footer
        blocks.append(Block.text(
            " j/k nav  enter ack  1/2 peer  d toggle  -/= zoom  s scope  q quit",
            DIM, width=w,
        ))

        return join_vertical(*blocks)

    def _render_debug(self, w: int, peer: Peer, lens: Lens, target_h: int) -> Block:
        """Debug panel — visible at zoom >= 2."""
        inner = w - 2
        content_h = max(target_h - 2, 1)

        lines: list[Block] = []

        # Lens state
        scope_label = self.scope_name
        lines.append(Block.text(f" lens: z{lens.zoom} scope:{scope_label}", BOLD, width=inner))
        lines.append(Block.text("", DIM, width=inner))

        # Fold engine versions
        versions = "  ".join(
            f"{k}:v{self.vertex.version(k)}" for k in self.vertex.kinds
        )
        lines.append(Block.text(f" {versions}", DIM, width=inner))
        lines.append(Block.text("", DIM, width=inner))

        # Event trace — filtered by lens.scope, depth by lens.zoom
        scope_label = self.scope_name
        lines.append(Block.text(
            f" trace [{scope_label}]", BOLD, width=inner,
        ))
        if self._trace:
            trace_limit = 8 if lens.zoom == 2 else 15
            # Filter trace entries by scope
            filtered = []
            for entry in self._trace:
                # Extract kind from entry (format: "kind  payload" or "kind → TICK")
                kind = entry.split()[0] if entry else ""
                if lens.includes(kind):
                    filtered.append(entry)
            for entry in filtered[-trace_limit:]:
                lines.append(Block.text(
                    f"  {entry}", Style(fg="cyan", dim=True), width=inner,
                ))
            if not filtered:
                lines.append(Block.text("  (filtered out)", DIM, width=inner))
        else:
            lines.append(Block.text("  (waiting)", DIM, width=inner))

        while len(lines) < content_h:
            lines.append(Block.text("", DIM, width=inner))

        return border(
            join_vertical(*lines),
            title=f"debug (lens z{lens.zoom})", style=DIM,
        )


# -- Main --------------------------------------------------------------------

async def main():
    app = ReviewLensApp()
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
