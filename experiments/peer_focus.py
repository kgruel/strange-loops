"""Per-peer focus: observer state belongs to the observer.

Building on simultaneous_peers.py findings. This experiment implements:

1. Per-peer focus state (`focus.{peer}`)
2. Multiple concurrent peers navigating independently
3. Rendering that displays the active peer's focus
4. Generalization to other observer state (scroll, selection, collapse)

KEY INSIGHT
-----------
Focus is not "the cursor" — it's "this peer's cursor." Observer state
tracks where an observer is looking, what they've selected, how they've
configured their view. This state belongs to the observer, not to the
shared world model.

Pattern: `{state_kind}.{peer_name}`
- `focus.kyle`, `focus.alice` — cursor position per peer
- `scroll.kyle`, `scroll.alice` — scroll offset per peer
- `selection.kyle` — selected items per peer
- `collapse.kyle` — collapsed tree nodes per peer

Run:
    uv run python experiments/peer_focus.py
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass

from peers import Peer, delegate
from ticks import Tick, Vertex
from specs import Shape, Facet


# -- Shapes ------------------------------------------------------------------

# Per-peer focus: each peer has their own cursor state
def focus_shape_for(peer_name: str) -> Shape:
    """Generate a focus shape for a specific peer."""
    return Shape(
        name=f"focus.{peer_name}",
        about=f"Cursor position for peer {peer_name}",
        input_facets=(Facet("index", "int"),),
        state_facets=(Facet("index", "int"),),
    )


# Per-peer scroll: scroll offset per peer
def scroll_shape_for(peer_name: str) -> Shape:
    """Generate a scroll shape for a specific peer."""
    return Shape(
        name=f"scroll.{peer_name}",
        about=f"Scroll offset for peer {peer_name}",
        input_facets=(Facet("offset", "int"),),
        state_facets=(Facet("offset", "int"),),
    )


# Per-peer selection: what items are selected
def selection_shape_for(peer_name: str) -> Shape:
    """Generate a selection shape for a specific peer."""
    return Shape(
        name=f"selection.{peer_name}",
        about=f"Selected items for peer {peer_name}",
        input_facets=(Facet("item", "str"), Facet("selected", "bool")),
        state_facets=(Facet("items", "set"),),
    )


# Shared domain state — not per-peer
health_shape = Shape(
    name="health",
    about="Container health status (shared state)",
    input_facets=(Facet("container", "str"), Facet("status", "str")),
    state_facets=(Facet("statuses", "dict"),),
)


# -- Folds -------------------------------------------------------------------

def focus_fold(state: dict, payload: dict) -> dict:
    """Set cursor index."""
    return {"index": payload.get("index", 0)}


def scroll_fold(state: dict, payload: dict) -> dict:
    """Set scroll offset."""
    return {"offset": payload.get("offset", 0)}


def selection_fold(state: dict, payload: dict) -> dict:
    """Toggle item selection."""
    items = set(state.get("items", set()))
    item = payload.get("item")
    selected = payload.get("selected", True)
    if selected:
        items.add(item)
    else:
        items.discard(item)
    return {"items": items}


def health_fold(state: dict, payload: dict) -> dict:
    """Accumulate container health statuses."""
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


# -- Topology ----------------------------------------------------------------

CONTAINERS = ["nginx", "api", "redis", "postgres", "worker"]
PEER_NAMES = ["kyle", "alice", "bob"]


def build_vertex() -> Vertex:
    """Build a vertex with per-peer observer state and shared domain state."""
    v = Vertex("multi_peer")

    # Shared domain state
    v.register(health_shape.name, health_shape.initial_state(), health_fold)

    # Per-peer observer state
    for name in PEER_NAMES:
        # Focus
        focus_shape = focus_shape_for(name)
        v.register(focus_shape.name, focus_shape.initial_state(), focus_fold)

        # Scroll
        scroll_shape = scroll_shape_for(name)
        v.register(scroll_shape.name, scroll_shape.initial_state(), scroll_fold)

        # Selection
        sel_shape = selection_shape_for(name)
        v.register(sel_shape.name, sel_shape.initial_state(), selection_fold)

    return v


def build_peers() -> tuple[Peer, ...]:
    """Build concurrent peers."""
    return tuple(Peer(name) for name in PEER_NAMES)


# -- Observer State Protocol -------------------------------------------------

@dataclass(frozen=True, slots=True)
class ObserverState:
    """Observer state bundle for a peer.

    Encapsulates all per-peer state kinds. This is the read-side view
    of observer state — call `load()` to get current state from vertex.
    """

    peer: str
    focus: int
    scroll: int
    selection: frozenset[str]

    @classmethod
    def load(cls, vertex: Vertex, peer: str) -> "ObserverState":
        """Load current observer state for a peer from vertex."""
        focus_state = vertex.state(f"focus.{peer}")
        scroll_state = vertex.state(f"scroll.{peer}")
        sel_state = vertex.state(f"selection.{peer}")

        return cls(
            peer=peer,
            focus=focus_state.get("index", 0),
            scroll=scroll_state.get("offset", 0),
            selection=frozenset(sel_state.get("items", set())),
        )


class ObserverActions:
    """Observer actions for a peer.

    Encapsulates all per-peer state mutations. The write-side interface
    for observer state — emit through vertex.receive().
    """

    def __init__(self, vertex: Vertex, peer: str):
        self._vertex = vertex
        self._peer = peer

    def set_focus(self, index: int) -> None:
        """Set cursor position."""
        self._vertex.receive(f"focus.{self._peer}", {"index": index})

    def set_scroll(self, offset: int) -> None:
        """Set scroll offset."""
        self._vertex.receive(f"scroll.{self._peer}", {"offset": offset})

    def select(self, item: str) -> None:
        """Add item to selection."""
        self._vertex.receive(f"selection.{self._peer}", {"item": item, "selected": True})

    def deselect(self, item: str) -> None:
        """Remove item from selection."""
        self._vertex.receive(f"selection.{self._peer}", {"item": item, "selected": False})

    def toggle_selection(self, item: str, current_selection: frozenset[str]) -> None:
        """Toggle item selection."""
        if item in current_selection:
            self.deselect(item)
        else:
            self.select(item)


# -- Simulation --------------------------------------------------------------

@dataclass
class NavigationEvent:
    """Captured navigation event for analysis."""
    peer: str
    action: str  # "focus", "scroll", "select"
    value: int | str
    state_after: ObserverState


class SimulationResult:
    """Results from running the peer focus simulation."""

    def __init__(self):
        self.events: list[NavigationEvent] = []
        self.conflicts: int = 0
        self.per_peer_events: dict[str, int] = {}

    def add_event(self, event: NavigationEvent) -> None:
        self.events.append(event)
        self.per_peer_events[event.peer] = self.per_peer_events.get(event.peer, 0) + 1

    def summary(self) -> str:
        lines = [
            f"Total events: {len(self.events)}",
            f"Per-peer breakdown:",
        ]
        for peer, count in sorted(self.per_peer_events.items()):
            lines.append(f"  {peer}: {count} events")
        lines.append("")
        lines.append("Final observer states:")

        # Group final states by peer
        final_states: dict[str, ObserverState] = {}
        for e in self.events:
            final_states[e.peer] = e.state_after

        for peer, state in sorted(final_states.items()):
            sel_str = ", ".join(sorted(state.selection)) if state.selection else "(none)"
            lines.append(
                f"  {peer:8} focus={state.focus} scroll={state.scroll} selected=[{sel_str}]"
            )

        return "\n".join(lines)


async def peer_navigation_loop(
    peer: Peer,
    vertex: Vertex,
    result: SimulationResult,
    duration: float = 2.0,
) -> None:
    """Simulate a peer navigating independently.

    Each peer has their own focus, scroll, and selection state.
    No conflicts because state is partitioned by peer.
    """
    actions = ObserverActions(vertex, peer.name)
    max_idx = len(CONTAINERS) - 1

    # Start at a random position
    current_focus = random.randint(0, max_idx)
    current_scroll = 0
    direction = random.choice([-1, 1])

    actions.set_focus(current_focus)

    end_time = asyncio.get_event_loop().time() + duration

    while asyncio.get_event_loop().time() < end_time:
        # Decide action: move focus, scroll, or select
        action_choice = random.choice(["focus", "focus", "scroll", "select"])

        if action_choice == "focus":
            # Move cursor
            current_focus += direction
            if current_focus > max_idx:
                current_focus = max_idx
                direction = -1
            elif current_focus < 0:
                current_focus = 0
                direction = 1
            actions.set_focus(current_focus)

        elif action_choice == "scroll":
            # Adjust scroll
            current_scroll = max(0, current_scroll + random.choice([-1, 0, 1]))
            actions.set_scroll(current_scroll)

        elif action_choice == "select":
            # Toggle selection on current item
            container = CONTAINERS[current_focus]
            state = ObserverState.load(vertex, peer.name)
            actions.toggle_selection(container, state.selection)

        # Yield to allow other tasks to run
        await asyncio.sleep(0)

        # Record the state AFTER our action — always matches because it's our own state
        state = ObserverState.load(vertex, peer.name)
        event = NavigationEvent(
            peer=peer.name,
            action=action_choice,
            value=current_focus if action_choice == "focus" else (
                current_scroll if action_choice == "scroll" else CONTAINERS[current_focus]
            ),
            state_after=state,
        )
        result.add_event(event)

        # Random interval before next action
        await asyncio.sleep(random.uniform(0.01, 0.05))


async def run_concurrent_navigation(
    peers: tuple[Peer, ...],
    vertex: Vertex,
) -> SimulationResult:
    """Run all peers navigating concurrently."""
    result = SimulationResult()

    # Launch all peers concurrently
    tasks = [
        peer_navigation_loop(peer, vertex, result, duration=1.0)
        for peer in peers
    ]

    await asyncio.gather(*tasks)

    return result


# -- Rendering Layer ---------------------------------------------------------

def render_for_peer(vertex: Vertex, active_peer: str) -> str:
    """Render the view for a specific peer.

    The rendering layer decides which peer's focus/selection to display.
    All peers see the same shared state (health), but their own observer state.
    """
    lines = []

    # Load shared state
    health_state = vertex.state("health")
    statuses = health_state.get("statuses", {})

    # Load this peer's observer state
    obs = ObserverState.load(vertex, active_peer)

    lines.append(f"=== View for {active_peer} ===")
    lines.append(f"Focus: {obs.focus}  Scroll: {obs.scroll}")
    lines.append("")

    for i, container in enumerate(CONTAINERS):
        cursor = ">" if i == obs.focus else " "
        status = statuses.get(container, "unknown")
        selected = "✓" if container in obs.selection else " "
        lines.append(f"  {cursor} [{selected}] {container:<12} {status}")

    lines.append("")
    selected_str = ", ".join(sorted(obs.selection)) if obs.selection else "(none)"
    lines.append(f"Selected: {selected_str}")

    return "\n".join(lines)


def render_all_peers(vertex: Vertex, peers: tuple[Peer, ...]) -> str:
    """Render a split view showing all peers' observer states."""
    lines = []
    lines.append("=" * 60)
    lines.append("SPLIT VIEW — All peers' observer states")
    lines.append("=" * 60)

    # Load shared state once
    health_state = vertex.state("health")
    statuses = health_state.get("statuses", {})

    # Show header for each peer
    header_parts = []
    for peer in peers:
        header_parts.append(f"{peer.name:^18}")
    lines.append("  " + "│".join(header_parts))
    lines.append("  " + "─" * 18 + "┼" + "─" * 18 + "┼" + "─" * 18)

    # Load all observer states
    obs_states = {p.name: ObserverState.load(vertex, p.name) for p in peers}

    # Show each container row with per-peer state
    for i, container in enumerate(CONTAINERS):
        status = statuses.get(container, "unknown")
        row_parts = []

        for peer in peers:
            obs = obs_states[peer.name]
            cursor = ">" if i == obs.focus else " "
            selected = "✓" if container in obs.selection else " "
            row_parts.append(f"{cursor}[{selected}] {container:<10}")

        lines.append("  " + "│".join(row_parts) + f"  {status}")

    lines.append("")

    # Show selection summary per peer
    for peer in peers:
        obs = obs_states[peer.name]
        sel_str = ", ".join(sorted(obs.selection)) if obs.selection else "(none)"
        lines.append(f"  {peer.name} selected: {sel_str}")

    return "\n".join(lines)


# -- Main --------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("PER-PEER FOCUS EXPERIMENT")
    print("=" * 60)
    print()
    print("Observer state belongs to the observer.")
    print("Each peer has their own: focus, scroll, selection.")
    print("Shared state (health) is common to all peers.")
    print()

    vertex = build_vertex()
    peers = build_peers()

    print(f"Peers: {', '.join(p.name for p in peers)}")
    print(f"Containers: {', '.join(CONTAINERS)}")
    print()

    # Seed some health data
    for c in CONTAINERS:
        status = random.choice(["running", "running", "running", "unhealthy"])
        vertex.receive("health", {"container": c, "status": status})

    # Run concurrent navigation
    print("-" * 60)
    print("Running concurrent navigation (1 second)...")
    print("-" * 60)

    result = await run_concurrent_navigation(peers, vertex)

    print(result.summary())
    print()

    # Show split view
    print(render_all_peers(vertex, peers))
    print()

    # Show individual peer views
    print("-" * 60)
    print("Individual peer views:")
    print("-" * 60)
    for peer in peers:
        print()
        print(render_for_peer(vertex, peer.name))

    print()
    print("=" * 60)
    print("CONCLUSIONS")
    print("=" * 60)
    print()
    print("1. Per-peer state eliminates conflicts — each peer writes to")
    print("   their own state kinds (focus.kyle, focus.alice, etc.)")
    print()
    print("2. ObserverState bundles read operations; ObserverActions bundles")
    print("   write operations. Clean protocol for observer state access.")
    print()
    print("3. Rendering layer decides which peer's state to display based on")
    print("   context (active peer, split view, follow mode, etc.)")
    print()
    print("4. Generalizes beyond focus: scroll, selection, collapse all follow")
    print("   the same {kind}.{peer} pattern.")
    print()
    print("5. Shared vs observer state is a design choice:")
    print("   - Health status: shared (objective fact about the world)")
    print("   - Focus position: per-peer (subjective view of the observer)")


if __name__ == "__main__":
    asyncio.run(main())
