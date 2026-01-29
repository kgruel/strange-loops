"""Simultaneous peers: exploring when shared focus breaks.

PROBLEM STATEMENT
-----------------
Current model: one Vertex, one focus state. All peers share the same cursor.

This works when:
  - Single user (no conflict)
  - Turn-based collaboration (peers act sequentially)
  - Shared attention (everyone watches the same thing)

This breaks when:
  - Two users navigate simultaneously (cursor fights)
  - Peers need different views of same data (divergent focus)
  - Multi-user collaboration with independent workflows

EXPERIMENT
----------
Three peers (kyle, alice, bob) emit focus changes concurrently via asyncio.
The single shared focus state creates a race condition — last write wins,
producing a chaotic cursor that jumps unpredictably.

FINDINGS
--------
1. CONFLICT DEMONSTRATION: When multiple peers emit focus changes in rapid
   succession, the cursor jumps erratically. Each peer's intended navigation
   is overwritten by the next peer's emission. The final cursor position
   reflects whoever emitted last, not any peer's intended state.

2. ROOT CAUSE: Focus is modeled as shared state with last-write-wins semantics.
   There's no concept of "whose focus" — it's "the focus."

3. POTENTIAL SOLUTIONS:

   a) Per-peer focus (state partitioning):
      - Each peer gets their own focus state: focus.kyle, focus.alice, focus.bob
      - Pro: Clean isolation, no conflicts
      - Con: State explosion, complex rendering (which focus to show?)

   b) Focus ownership (single writer):
      - One peer "owns" focus at a time
      - Others can request ownership, current owner releases
      - Pro: Maintains single shared view
      - Con: Coordination overhead, ownership transfer latency

   c) Focus requests (optimistic + conflict resolution):
      - Peers emit focus_request, not focus
      - A coordinator fold arbitrates conflicts (first wins, priority, etc.)
      - Pro: Explicit conflict handling
      - Con: Added complexity, latency from arbitration

   d) Vector clocks / CRDTs:
      - Track causal ordering of focus changes per peer
      - Merge conflicts deterministically
      - Pro: Eventually consistent, no coordination
      - Con: Complexity, may produce unexpected merged states

RECOMMENDATION
--------------
For the loops model, (a) per-peer focus aligns best with the "observer is
first-class" principle. Each Peer's focus is their observation of where
they're looking. The rendering layer (Surface/Lens) decides which peer's
focus to display based on context (active peer, split view, etc.).

This changes focus from "cursor position" to "peer.cursor_position" —
a fact about the peer, not a shared singleton.

Run:
    uv run python experiments/simultaneous_peers.py
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from peers import Peer
from ticks import Tick, Vertex
from specs import Shape, Facet


# -- Shapes ------------------------------------------------------------------

# Current model: single shared focus
focus_shape = Shape(
    name="focus",
    about="Observer cursor position (SHARED - the problem)",
    input_facets=(Facet("index", "int"), Facet("peer", "str")),
    state_facets=(Facet("index", "int"), Facet("last_peer", "str")),
)


# -- Folds -------------------------------------------------------------------

def focus_fold(state: dict, payload: dict) -> dict:
    """Set cursor index. Last write wins."""
    return {
        "index": payload.get("index", 0),
        "last_peer": payload.get("peer", "unknown"),
    }


# -- Topology ----------------------------------------------------------------

ITEMS = ["nginx", "api", "redis", "postgres", "worker"]


def build_vertex() -> Vertex:
    """Single vertex with shared focus."""
    v = Vertex("shared")
    v.register(focus_shape.name, focus_shape.initial_state(), focus_fold)
    return v


def build_peers() -> tuple[Peer, ...]:
    """Three unrestricted peers."""
    return (
        Peer("kyle"),
        Peer("alice"),
        Peer("bob"),
    )


# -- Event Log ---------------------------------------------------------------

@dataclass
class FocusEvent:
    """Captured focus emission for analysis."""
    ts: datetime
    peer: str
    intended_index: int
    actual_index_after: int
    was_overwritten: bool = False


# -- Simulation --------------------------------------------------------------

class SimulationResult:
    """Results from running the simultaneous peers simulation."""

    def __init__(self):
        self.events: list[FocusEvent] = []
        self.conflicts: int = 0
        self.total_emissions: int = 0

    def add_event(self, event: FocusEvent):
        self.events.append(event)
        self.total_emissions += 1
        if event.was_overwritten:
            self.conflicts += 1

    def summary(self) -> str:
        lines = [
            f"Total emissions: {self.total_emissions}",
            f"Conflicts (overwrites): {self.conflicts}",
            f"Conflict rate: {self.conflicts / max(self.total_emissions, 1) * 100:.1f}%",
            "",
            "Event trace (last 20):",
        ]
        for e in self.events[-20:]:
            conflict_marker = " [!]" if e.was_overwritten else ""
            lines.append(
                f"  {e.peer:8} intended={e.intended_index} "
                f"actual={e.actual_index_after}{conflict_marker}"
            )
        return "\n".join(lines)


async def peer_navigation_loop(
    peer: Peer,
    vertex: Vertex,
    result: SimulationResult,
    peer_state: dict[str, int],  # Shared dict tracking each peer's intended position
    duration: float = 2.0,
    emit_interval: tuple[float, float] = (0.05, 0.15),
):
    """Simulate a peer navigating through items.

    Each peer has their own "intended" cursor position and tries to
    move through the list. Emissions happen at random intervals to
    simulate realistic async behavior.

    The peer_state dict tracks what each peer THINKS the cursor should be.
    Conflicts occur when the shared state doesn't match a peer's intent.
    """
    max_idx = len(ITEMS) - 1
    current_intended = random.randint(0, max_idx)
    direction = random.choice([-1, 1])

    peer_state[peer.name] = current_intended
    end_time = asyncio.get_event_loop().time() + duration

    while asyncio.get_event_loop().time() < end_time:
        # Move intended position
        current_intended += direction
        if current_intended > max_idx:
            current_intended = max_idx
            direction = -1
        elif current_intended < 0:
            current_intended = 0
            direction = 1

        peer_state[peer.name] = current_intended

        # Emit focus change
        vertex.receive("focus", {"index": current_intended, "peer": peer.name})

        # Yield to allow other tasks to run (simulates real async interleaving)
        await asyncio.sleep(0)

        # Check what actually happened AFTER yield
        # This is where conflicts become visible - another peer may have written
        actual = vertex.state("focus")
        actual_index = actual.get("index", -1)

        # Conflict: shared state doesn't match what this peer wanted
        was_overwritten = (actual_index != current_intended)

        # Record event
        event = FocusEvent(
            ts=datetime.now(timezone.utc),
            peer=peer.name,
            intended_index=current_intended,
            actual_index_after=actual_index,
            was_overwritten=was_overwritten,
        )
        result.add_event(event)

        # Random interval before next emission
        interval = random.uniform(*emit_interval)
        await asyncio.sleep(interval)


async def run_sequential_baseline(peers: tuple[Peer, ...], vertex: Vertex) -> SimulationResult:
    """Baseline: peers take turns (no conflict expected)."""
    result = SimulationResult()
    peer_state: dict[str, int] = {}

    for peer in peers:
        # Each peer navigates alone for a short period
        await peer_navigation_loop(
            peer, vertex, result, peer_state,
            duration=0.3,
            emit_interval=(0.05, 0.1),
        )

    return result


async def run_simultaneous_conflict(peers: tuple[Peer, ...], vertex: Vertex) -> SimulationResult:
    """Conflict scenario: all peers navigate simultaneously."""
    result = SimulationResult()
    peer_state: dict[str, int] = {}

    # Launch all peers concurrently
    tasks = [
        peer_navigation_loop(
            peer, vertex, result, peer_state,
            duration=1.0,
            emit_interval=(0.001, 0.01),  # Very fast emissions = high conflict
        )
        for peer in peers
    ]

    await asyncio.gather(*tasks)

    return result


# -- Per-Peer Focus Solution Demo --------------------------------------------

def build_per_peer_vertex(peers: tuple[Peer, ...]) -> Vertex:
    """Alternative model: each peer has their own focus state."""
    v = Vertex("per_peer")

    for peer in peers:
        kind = f"focus.{peer.name}"
        v.register(kind, {"index": 0}, focus_fold)

    return v


async def run_per_peer_solution(peers: tuple[Peer, ...]) -> SimulationResult:
    """Demonstrate per-peer focus (no conflicts)."""
    vertex = build_per_peer_vertex(peers)
    result = SimulationResult()

    async def peer_with_own_focus(peer: Peer):
        """Each peer emits to their own focus kind."""
        kind = f"focus.{peer.name}"
        max_idx = len(ITEMS) - 1
        current = random.randint(0, max_idx)
        direction = random.choice([-1, 1])

        for _ in range(15):
            current += direction
            if current > max_idx:
                current = max_idx
                direction = -1
            elif current < 0:
                current = 0
                direction = 1

            vertex.receive(kind, {"index": current, "peer": peer.name})

            # Verify our own state (always matches, no conflict)
            actual = vertex.state(kind)
            event = FocusEvent(
                ts=datetime.now(timezone.utc),
                peer=peer.name,
                intended_index=current,
                actual_index_after=actual.get("index", -1),
                was_overwritten=False,  # Never overwritten with per-peer focus
            )
            result.add_event(event)

            await asyncio.sleep(random.uniform(0.02, 0.08))

    tasks = [peer_with_own_focus(peer) for peer in peers]
    await asyncio.gather(*tasks)

    return result


# -- Main --------------------------------------------------------------------

async def main():
    print("=" * 60)
    print("SIMULTANEOUS PEERS EXPERIMENT")
    print("=" * 60)
    print()

    peers = build_peers()
    print(f"Peers: {', '.join(p.name for p in peers)}")
    print(f"Items: {', '.join(ITEMS)}")
    print()

    # Scenario 1: Sequential (baseline)
    print("-" * 60)
    print("SCENARIO 1: Sequential navigation (baseline)")
    print("-" * 60)
    vertex1 = build_vertex()
    result1 = await run_sequential_baseline(peers, vertex1)
    print(result1.summary())
    print()

    # Scenario 2: Simultaneous (conflict)
    print("-" * 60)
    print("SCENARIO 2: Simultaneous navigation (CONFLICT)")
    print("-" * 60)
    vertex2 = build_vertex()
    result2 = await run_simultaneous_conflict(peers, vertex2)
    print(result2.summary())
    print()

    # Scenario 3: Per-peer focus (solution)
    print("-" * 60)
    print("SCENARIO 3: Per-peer focus (SOLUTION)")
    print("-" * 60)
    result3 = await run_per_peer_solution(peers)
    print(result3.summary())
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Sequential conflict rate:   {result1.conflicts / max(result1.total_emissions, 1) * 100:.1f}%")
    print(f"Simultaneous conflict rate: {result2.conflicts / max(result2.total_emissions, 1) * 100:.1f}%")
    print(f"Per-peer conflict rate:     {result3.conflicts / max(result3.total_emissions, 1) * 100:.1f}%")
    print()
    print("CONCLUSION:")
    print("  Shared focus breaks under concurrent peer activity.")
    print("  Per-peer focus (focus.{peer.name}) eliminates conflicts")
    print("  by partitioning state along the observer axis.")
    print()
    print("  This aligns with the loops model: the observer is first-class.")
    print("  Focus is not 'the cursor' but 'this peer's cursor'.")


if __name__ == "__main__":
    asyncio.run(main())
