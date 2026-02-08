"""Peer-aware Vertex: the full model.

Demonstrates the collapsed framework where:
- Observer (Peer) is explicit at receive time
- Gating happens at the Vertex boundary
- Observer-state kinds enforce ownership
- Cross-peer visibility follows horizon rules

Scenario: Three peers with different potentials
  - kyle: unrestricted operator (root)
  - alice: can see health + focus.alice, can update health + focus.alice
  - bob: can only see focus.*, can only update focus.bob

Shared state: health (any peer with potential can update)
Observer state: focus.{peer} (only the owning peer can update)

Run:
    uv run python experiments/peer_aware_vertex.py
"""

from __future__ import annotations

from atoms import Fact
from engine import Peer, delegate
from engine import Lens, Tick, Vertex


# -- Folds -------------------------------------------------------------------


def health_fold(state: dict, payload: dict) -> dict:
    """Track per-container status."""
    statuses = dict(state.get("statuses", {}))
    statuses[payload["container"]] = payload["status"]
    return {"statuses": statuses}


def focus_fold(state: dict, payload: dict) -> dict:
    """Track focus index for a specific peer."""
    return {"index": payload.get("index", 0)}


def count_fold(state: int, payload: dict) -> int:
    """Simple counter."""
    return state + 1


# -- Topology ----------------------------------------------------------------


def build_vertex() -> Vertex:
    """One vertex, multiple fold engines.

    - health: shared state (any peer with potential can update)
    - focus.{peer}: observer state (ownership enforced)
    - access.denied: audit trail for rejected facts
    """
    v = Vertex("peer-demo")

    # Shared state
    v.register("health", {"statuses": {}}, health_fold, boundary="health.close", reset=True)

    # Per-peer observer state
    v.register("focus.kyle", {"index": 0}, focus_fold)
    v.register("focus.alice", {"index": 0}, focus_fold)
    v.register("focus.bob", {"index": 0}, focus_fold)

    # Audit counter for demo
    v.register("audit", 0, count_fold)

    return v


def build_peers() -> dict[str, Peer]:
    """Three peers with different permissions.

    kyle: unrestricted (root operator)
    alice: health + focus.alice
    bob: focus.bob only
    """
    kyle = Peer("kyle")  # unrestricted

    # Alice can see and do health + her own focus
    alice = delegate(
        kyle, "alice",
        potential={"health", "health.close", "focus.alice"},
        horizon={"health", "focus.alice"},
    )

    # Bob can only manage his own focus
    bob = delegate(
        kyle, "bob",
        potential={"focus.bob"},
        horizon={"focus.bob", "focus.alice"},  # can see alice's focus but not update it
    )

    return {"kyle": kyle, "alice": alice, "bob": bob}


# -- Demo --------------------------------------------------------------------


def emit(vertex: Vertex, fact: Fact, peer: Peer, log: list[str]) -> Tick | None:
    """Emit a fact and log the result."""
    result = vertex.receive(fact, peer)
    if result is not None:
        log.append(f"  {peer.name}: {fact.kind} → TICK {result.name}")
    else:
        # Check if it was actually folded by seeing if state changed
        # (a hack for demo — in production you'd track this differently)
        log.append(f"  {peer.name}: {fact.kind}")
    return result


def demo_potential_gating(vertex: Vertex, peers: dict[str, Peer]) -> list[str]:
    """Demonstrate potential gating: peer.potential restricts what facts can be emitted."""
    log = ["\n=== Potential Gating ==="]
    log.append("Alice has potential={health, health.close, focus.alice}")
    log.append("Bob has potential={focus.bob}")
    log.append("")

    kyle = peers["kyle"]
    alice = peers["alice"]
    bob = peers["bob"]

    # Alice can emit health facts
    log.append("Alice emits health facts:")
    emit(vertex, Fact.of("health", container="nginx", status="running"), alice, log)
    emit(vertex, Fact.of("health", container="api", status="healthy"), alice, log)

    # Bob cannot emit health facts (not in potential)
    log.append("\nBob tries to emit health (blocked by potential):")
    before = vertex.state("health")
    emit(vertex, Fact.of("health", container="redis", status="stopped"), bob, log)
    after = vertex.state("health")
    if before == after:
        log.append("  → Blocked: state unchanged")

    # Show current health state
    log.append(f"\nHealth state: {vertex.state('health')}")

    return log


def demo_observer_state_ownership(vertex: Vertex, peers: dict[str, Peer]) -> list[str]:
    """Demonstrate observer-state ownership: focus.{peer} can only be updated by that peer."""
    log = ["\n=== Observer-State Ownership ==="]
    log.append("focus.{peer} kinds can only be updated by the owning peer")
    log.append("")

    kyle = peers["kyle"]
    alice = peers["alice"]
    bob = peers["bob"]

    # Alice updates her own focus
    log.append("Alice updates focus.alice (allowed - owns it):")
    emit(vertex, Fact.of("focus.alice", index=5), alice, log)
    log.append(f"  → focus.alice: {vertex.state('focus.alice')}")

    # Bob updates his own focus
    log.append("\nBob updates focus.bob (allowed - owns it):")
    emit(vertex, Fact.of("focus.bob", index=3), bob, log)
    log.append(f"  → focus.bob: {vertex.state('focus.bob')}")

    # Alice tries to update Bob's focus (blocked by ownership)
    log.append("\nAlice tries to update focus.bob (blocked by ownership):")
    before = vertex.state("focus.bob")
    emit(vertex, Fact.of("focus.bob", index=99), alice, log)
    after = vertex.state("focus.bob")
    if before == after:
        log.append(f"  → Blocked: focus.bob still {after}")

    # Bob tries to update Alice's focus (blocked by ownership AND potential)
    log.append("\nBob tries to update focus.alice (blocked by potential):")
    before = vertex.state("focus.alice")
    emit(vertex, Fact.of("focus.alice", index=99), bob, log)
    after = vertex.state("focus.alice")
    if before == after:
        log.append(f"  → Blocked: focus.alice still {after}")

    # Kyle (unrestricted potential) still can't update alice's focus — ownership is absolute
    log.append("\nKyle (unrestricted potential) tries to update focus.alice:")
    before = vertex.state("focus.alice")
    emit(vertex, Fact.of("focus.alice", index=10), kyle, log)
    after = vertex.state("focus.alice")
    if before == after:
        log.append(f"  → Blocked by ownership: focus.alice still {after}")
    else:
        log.append(f"  → focus.alice: {after}")

    # But Kyle CAN update his own focus
    log.append("\nKyle updates focus.kyle (his own):")
    emit(vertex, Fact.of("focus.kyle", index=7), kyle, log)
    log.append(f"  → focus.kyle: {vertex.state('focus.kyle')}")

    return log


def demo_boundary_gating(vertex: Vertex, peers: dict[str, Peer]) -> list[str]:
    """Demonstrate boundary facts are also gated by potential."""
    log = ["\n=== Boundary Gating ==="]
    log.append("Boundary facts (health.close) also require potential")
    log.append("")

    alice = peers["alice"]
    bob = peers["bob"]

    # Add some health facts
    emit(vertex, Fact.of("health", container="worker", status="running"), alice, log)

    # Alice can fire the health boundary (has health.close in potential)
    log.append("\nAlice fires health.close (allowed):")
    tick = emit(vertex, Fact.of("health.close"), alice, log)
    if tick:
        log.append(f"  → Tick produced: {tick.name} with {tick.payload}")

    # Add more health facts
    emit(vertex, Fact.of("health", container="db", status="healthy"), alice, log)

    # Bob cannot fire health boundary (not in potential)
    log.append("\nBob tries to fire health.close (blocked):")
    tick = emit(vertex, Fact.of("health.close"), bob, log)
    if tick is None:
        log.append("  → Blocked: no tick produced")

    log.append(f"\nHealth state (not reset because Bob's boundary was blocked): {vertex.state('health')}")

    return log


def demo_cross_peer_visibility(peers: dict[str, Peer]) -> list[str]:
    """Demonstrate horizon controls what peers can see (render-time, not fold-time)."""
    log = ["\n=== Cross-Peer Visibility (Horizon) ==="]
    log.append("Horizon gates what data is visible at render time")
    log.append("")

    alice = peers["alice"]
    bob = peers["bob"]

    log.append(f"Alice's horizon: {alice.horizon or 'unrestricted'}")
    log.append(f"Bob's horizon: {bob.horizon or 'unrestricted'}")
    log.append("")
    log.append("Bob can see focus.alice (in his horizon)")
    log.append("But Bob cannot UPDATE focus.alice (not in potential + ownership)")
    log.append("")
    log.append("This is the read vs write distinction:")
    log.append("  - horizon = what you can see (read)")
    log.append("  - potential = what you can do (write)")
    log.append("  - ownership = observer-state kinds require peer match")

    return log


def demo_lens_usage() -> list[str]:
    """Demonstrate Lens as a rendering parameter (not access control)."""
    log = ["\n=== Lens (Rendering Parameters) ==="]
    log.append("Lens controls HOW data is presented, not access")
    log.append("")

    # Create various lenses
    minimal = Lens.minimal()
    summary = Lens.summary()
    detail = Lens.detail()
    scoped = Lens.summary().with_scope("health", "audit")

    log.append(f"minimal: zoom={minimal.zoom}, scope={minimal.scope}")
    log.append(f"summary: zoom={summary.zoom}, scope={summary.scope}")
    log.append(f"detail:  zoom={detail.zoom}, scope={detail.scope}")
    log.append(f"scoped:  zoom={scoped.zoom}, scope={scoped.scope}")
    log.append("")

    # Lens filtering
    log.append("Lens.includes() checks if a kind is in scope:")
    for kind in ["health", "focus.alice", "audit"]:
        log.append(f"  scoped.includes('{kind}'): {scoped.includes(kind)}")

    log.append("")
    log.append("Lens is orthogonal to Peer:")
    log.append("  - Peer.horizon gates DATA access")
    log.append("  - Lens.scope gates RENDERING (any peer can use any lens)")

    return log


def main():
    """Run all demonstrations."""
    vertex = build_vertex()
    peers = build_peers()

    print("=" * 60)
    print("PEER-AWARE VERTEX DEMONSTRATION")
    print("=" * 60)
    print("\nThe model: Vertex.receive(fact: Fact, peer: Peer)")
    print("Gating happens at receive time, not at emit time.")
    print("\nPeers:")
    for name, peer in peers.items():
        print(f"  {name}:")
        print(f"    potential: {peer.potential or 'unrestricted'}")
        print(f"    horizon:   {peer.horizon or 'unrestricted'}")

    # Run demos
    for line in demo_potential_gating(vertex, peers):
        print(line)

    for line in demo_observer_state_ownership(vertex, peers):
        print(line)

    for line in demo_boundary_gating(vertex, peers):
        print(line)

    for line in demo_cross_peer_visibility(peers):
        print(line)

    for line in demo_lens_usage():
        print(line)

    print("\n" + "=" * 60)
    print("Final state:")
    for kind in vertex.kinds:
        print(f"  {kind}: {vertex.state(kind)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
