"""Observer flow: demonstrates observer model.

Shows the full cycle:
1. Multiple observers emit facts (observer intrinsic to Fact)
2. Vertex routes facts to loops
3. Loop fires tick with origin stamp
4. Vertex converts tick to fact (vertex as observer)
5. Second vertex receives that fact

Run:
    uv run python experiments/observer_flow.py
"""

from __future__ import annotations

from datetime import datetime, timezone

from facts import Fact
from peers import Grant
from ticks import Tick, Vertex


def count_fold(state: int, payload: dict) -> int:
    """Simple count fold."""
    return state + 1


def sum_fold(state: int, payload: dict) -> int:
    """Sum values from payload."""
    return state + payload.get("value", 0)


def collect_fold(state: list, payload) -> list:
    """Collect payloads from ticks."""
    return [*state, payload]


def main():
    print("=== Observer Flow Experiment ===\n")

    # --- Build vertices ---
    vertex_a = Vertex("vertex-a")
    vertex_a.register("metric", 0, sum_fold, boundary="flush")
    vertex_a.register("event", 0, count_fold)

    vertex_b = Vertex("vertex-b")
    vertex_b.register("tick.metric", [], collect_fold)

    # --- Multiple observers emit facts ---
    print("1. Multiple observers emit facts to vertex-a\n")

    # Alice emits metrics
    f1 = Fact.of("metric", "alice", value=10)
    print(f"   alice emits: {f1.kind} (observer={f1.observer}, value=10)")
    vertex_a.receive(f1)

    # Bob emits metrics
    f2 = Fact.of("metric", "bob", value=5)
    print(f"   bob emits: {f2.kind} (observer={f2.observer}, value=5)")
    vertex_a.receive(f2)

    # Sensor emits events
    f3 = Fact.of("event", "sensor", type="heartbeat")
    print(f"   sensor emits: {f3.kind} (observer={f3.observer})")
    vertex_a.receive(f3)

    print(f"\n   vertex-a state: metric={vertex_a.state('metric')}, event={vertex_a.state('event')}")

    # --- Trigger boundary, get tick ---
    print("\n2. Trigger boundary, vertex-a produces tick\n")

    flush_fact = Fact.of("flush", "system")
    print(f"   system emits: {flush_fact.kind} (observer={flush_fact.observer})")
    tick = vertex_a.receive(flush_fact)

    if tick:
        print(f"   tick fired: name={tick.name}, origin={tick.origin}, payload={tick.payload}")

    # --- Convert tick to fact (vertex as observer) ---
    print("\n3. Vertex-a converts tick to fact (vertex becomes observer)\n")

    tick_fact = vertex_a.to_fact(tick)
    print(f"   tick -> fact: kind={tick_fact.kind}, observer={tick_fact.observer}")
    print(f"   payload={tick_fact.payload}")

    # --- Forward to second vertex ---
    print("\n4. Forward fact to vertex-b\n")

    vertex_b.receive(tick_fact)
    print(f"   vertex-b received tick.metric from observer={tick_fact.observer}")
    print(f"   vertex-b state: tick.metric={vertex_b.state('tick.metric')}")

    # --- Demonstrate grant gating ---
    print("\n5. Demonstrate grant gating\n")

    # Restricted grant: can only emit "event"
    restricted = Grant(potential=frozenset({"event"}))

    # Alice tries to emit metric (blocked by grant)
    blocked_fact = Fact.of("metric", "alice", value=100)
    result = vertex_a.receive(blocked_fact, restricted)
    print(f"   alice emits metric with restricted grant: blocked={result is None}")
    print(f"   vertex-a metric state unchanged: {vertex_a.state('metric')}")

    # Alice emits event (allowed by grant)
    allowed_fact = Fact.of("event", "alice", type="click")
    result = vertex_a.receive(allowed_fact, restricted)
    print(f"   alice emits event with restricted grant: accepted")
    print(f"   vertex-a event state: {vertex_a.state('event')}")

    # --- Demonstrate observer-state ownership ---
    print("\n6. Demonstrate observer-state ownership\n")

    vertex_c = Vertex("vertex-c")
    vertex_c.register("focus.alice", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})
    vertex_c.register("focus.bob", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

    # Alice can update her own focus
    f_alice = Fact.of("focus.alice", "alice", index=5)
    vertex_c.receive(f_alice)
    print(f"   alice updates focus.alice: {vertex_c.state('focus.alice')}")

    # Alice cannot update Bob's focus (observer doesn't match)
    f_bob_by_alice = Fact.of("focus.bob", "alice", index=10)
    vertex_c.receive(f_bob_by_alice)
    print(f"   alice tries focus.bob (blocked): {vertex_c.state('focus.bob')}")

    # Bob can update his own focus
    f_bob = Fact.of("focus.bob", "bob", index=3)
    vertex_c.receive(f_bob)
    print(f"   bob updates focus.bob: {vertex_c.state('focus.bob')}")

    print("\n=== Complete ===")


if __name__ == "__main__":
    main()
