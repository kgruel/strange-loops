"""Network + Observer: Facts crossing process boundaries.

EXPLORATION: How does observer identity flow across network boundaries?

Now that Fact carries observer intrinsically:
- Wire format = Fact.to_dict() / Fact.from_dict()
- Vertex.to_fact() converts Tick to Fact (vertex as observer)
- Grant is optional policy at the integration point

Run all scenarios:
    uv run python experiments/network_observer.py

Run specific scenario:
    uv run python experiments/network_observer.py health
    uv run python experiments/network_observer.py observer_state
    uv run python experiments/network_observer.py impersonation
    uv run python experiments/network_observer.py failure

SCENARIOS:
----------

1. HEALTH: Cross-process health updates
   - Alice produces health fact in Process A
   - Crosses network as Fact (not Tick)
   - Process B receives, folds, both have consistent state

2. OBSERVER_STATE: Observer-state kinds across network
   - Alice emits focus.alice from Process A
   - Vertex converts tick to fact before sending
   - Process B receives, observer field enables ownership check

3. IMPERSONATION: Attempted observer spoofing
   - Bob tries to send focus.alice with observer="bob"
   - Receiving vertex rejects: observer doesn't match kind owner

4. FAILURE: Connection failure with observer attribution
   - Network monitor observes connection drop
   - Emits fact with observer="network-monitor", target in payload
   - Observer = who saw it. Payload = what they saw.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from atoms import Fact
from engine import Tick, Vertex
from engine import Grant


# -- Wire format: Fact serialization ------------------------------------------

def fact_to_json(fact: Fact) -> bytes:
    """Serialize Fact for network transmission."""
    return json.dumps(fact.to_dict()).encode("utf-8")


def json_to_fact(data: bytes) -> Fact:
    """Deserialize Fact from network."""
    return Fact.from_dict(json.loads(data.decode("utf-8")))


# -- Simulated network connection ---------------------------------------------

@dataclass
class Connection:
    """Async queue simulating network connection.

    Sends/receives Facts (not Ticks). The wire format is Fact.to_dict().
    """

    queue: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    name: str = "connection"

    async def send(self, fact: Fact) -> None:
        """Send a fact over the connection."""
        await self.queue.put(fact_to_json(fact))

    async def receive(self, timeout: float = 1.0) -> Fact | None:
        """Receive a fact. Returns None on timeout."""
        try:
            data = await asyncio.wait_for(self.queue.get(), timeout=timeout)
            return json_to_fact(data)
        except asyncio.TimeoutError:
            return None


# -- Folds for the experiments ------------------------------------------------

def health_fold(state: dict, payload: Any) -> dict:
    """Fold health observations into aggregate state."""
    count = state.get("count", 0) + 1
    return {
        "count": count,
        "last_cpu": payload.get("cpu"),
        "last_observer": payload.get("_observer"),  # Track who reported
    }


def focus_fold(state: dict, payload: Any) -> dict:
    """Fold focus updates into state."""
    return {
        "index": payload.get("index", state.get("index", 0)),
        "updated_by": payload.get("_observer"),
    }


def connection_fold(state: dict, payload: Any) -> dict:
    """Fold connection events into state."""
    connections = dict(state.get("connections", {}))
    target = payload.get("target")
    status = payload.get("status", "unknown")
    connections[target] = {
        "status": status,
        "observer": payload.get("_observer"),
        "ts": payload.get("ts"),
    }
    return {"connections": connections}


# =============================================================================
# SCENARIO 1: HEALTH (Cross-process health updates)
# =============================================================================

async def health_scenario():
    """Demonstrates facts crossing process boundaries with observer intact.

    Pattern:
    1. Alice produces health fact with observer="alice"
    2. Process A vertex receives, accumulates state
    3. Periodic tick() snapshots state into Tick
    4. Vertex.to_fact(tick) creates Fact with observer=vertex.name
    5. Fact crosses network (serialized via to_dict/from_dict)
    6. Process B vertex receives fact, provenance is clear
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Health (Cross-process updates)")
    print("=" * 60)

    # Setup: Two vertices connected by network
    connection = Connection(name="a-to-b")

    # Process A: alpha vertex
    alpha = Vertex("alpha")
    alpha.register("health", {"count": 0}, health_fold)

    # Process B: beta vertex (receives tick facts)
    beta = Vertex("beta")
    beta.register("tick.health", {"count": 0}, health_fold)

    print("\n[setup] alpha and beta vertices created")

    # Alice produces health facts
    for cpu in [0.42, 0.55, 0.38]:
        alice_fact = Fact.of("health", observer="alice", cpu=cpu)
        print(f"\n[alice] Produces health fact: observer={alice_fact.observer}, cpu={cpu}")
        alpha.receive(alice_fact)

    print(f"[alpha] State after 3 facts: {alpha.state('health')}")

    # Alpha produces a tick (temporal boundary)
    tick = alpha.tick("health", datetime.now(timezone.utc))
    print(f"\n[alpha] tick() produced: name={tick.name}, origin={tick.origin}")
    print(f"[alpha] Tick payload: {tick.payload}")

    # Convert tick to fact for network transmission
    outbound = alpha.to_fact(tick)
    print(f"\n[alpha] to_fact: kind={outbound.kind}, observer={outbound.observer}")

    # Send over network
    await connection.send(outbound)
    print("[alpha] Sent fact over connection")

    # Beta receives from network
    received = await connection.receive()
    if received:
        print(f"\n[beta] Received: kind={received.kind}, observer={received.observer}")
        print(f"[beta] Payload: {received.payload}")

        # Beta folds the tick fact
        beta.receive(received)
        print(f"[beta] Observer provenance: came from '{received.observer}' vertex")

    print("\n--- Findings ---")
    print("- Fact.observer carries identity across network")
    print("- Vertex.to_fact() stamps vertex name as observer")
    print("- Provenance is clear: who observed → who forwarded")
    print("- Wire format = Fact.to_dict(), no separate peer envelope")


# =============================================================================
# SCENARIO 2: OBSERVER_STATE (Observer-state kinds across network)
# =============================================================================

async def observer_state_scenario():
    """Demonstrates observer-state kinds with ownership enforcement.

    Pattern:
    1. Alice emits focus.alice fact (observer="alice")
    2. Alpha vertex receives — ownership check passes (alice == alice)
    3. Tick snapshot via tick(), then to_fact() with observer="alpha"
    4. Beta receives — it's a tick fact from alpha, provenance clear
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Observer-State (Ownership across network)")
    print("=" * 60)

    connection = Connection(name="a-to-b")

    # Process A: alpha vertex with focus.alice loop
    alpha = Vertex("alpha")
    alpha.register("focus.alice", {"index": 0}, focus_fold)

    # Process B: beta vertex
    beta = Vertex("beta")
    beta.register("tick.focus.alice", {"index": 0}, focus_fold)  # Receives tick facts

    print("\n[setup] alpha handles focus.alice, beta handles tick.focus.alice")

    # Alice produces focus fact
    alice_fact = Fact.of("focus.alice", observer="alice", index=5)
    print(f"\n[alice] Produces focus.alice: observer={alice_fact.observer}, index={alice_fact.payload.get('index')}")

    # Alpha receives — ownership check in Vertex.receive()
    alpha.receive(alice_fact)
    print(f"[alpha] Received and folded")
    print(f"[alpha] State after fold: {alpha.state('focus.alice')}")

    # Snapshot state into tick
    tick = alpha.tick("focus.alice", datetime.now(timezone.utc))
    print(f"\n[alpha] tick() produced: name={tick.name}")

    # Convert to fact for network
    outbound = alpha.to_fact(tick)
    print(f"[alpha] to_fact: kind={outbound.kind}, observer={outbound.observer}")

    await connection.send(outbound)
    print("[alpha] Sent tick fact over connection")

    # Beta receives
    received = await connection.receive()
    if received:
        print(f"\n[beta] Received: kind={received.kind}, observer={received.observer}")

        # Beta processes the tick.focus.alice fact
        beta.receive(received)
        print(f"[beta] State: {beta.state('tick.focus.alice')}")

        print("\n[analysis]")
        print(f"  - Original observer (alice) produced focus.alice")
        print(f"  - Network observer (alpha) forwarded as tick.focus.alice")
        print(f"  - Two levels of provenance: who acted, who forwarded")

    print("\n--- Findings ---")
    print("- Observer-state ownership checked at receive time")
    print("- to_fact() changes observer to vertex name (forwarder)")
    print("- Original actor visible in payload if needed")
    print("- Network layer doesn't need special handling")


# =============================================================================
# SCENARIO 3: IMPERSONATION (Attempted observer spoofing)
# =============================================================================

async def impersonation_scenario():
    """Demonstrates observer-state ownership prevents spoofing.

    Pattern:
    1. Bob tries to send focus.alice with observer="bob"
    2. Alpha vertex rejects: bob != alice for focus.alice kinds
    3. No wire format tricks — observer is in the Fact itself
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Impersonation (Ownership enforcement)")
    print("=" * 60)

    connection = Connection(name="b-to-a")

    # Process A: alpha vertex with focus.alice loop
    alpha = Vertex("alpha")
    alpha.register("focus.alice", {"index": 0}, focus_fold)

    print("\n[setup] alpha handles focus.alice")

    # Bob tries to impersonate Alice
    bob_fake_fact = Fact.of("focus.alice", observer="bob", index=999)
    print(f"\n[bob] Attempts focus.alice: observer={bob_fake_fact.observer}, index={bob_fake_fact.payload.get('index')}")

    # Send over network (Bob's process to Alpha)
    await connection.send(bob_fake_fact)
    print("[bob] Sent impersonation attempt over connection")

    # Alpha receives
    received = await connection.receive()
    if received:
        print(f"\n[alpha] Received: kind={received.kind}, observer={received.observer}")

        # Alpha's receive() checks ownership
        result = alpha.receive(received)

        if result is None:
            print(f"[alpha] REJECTED: observer '{received.observer}' cannot write focus.alice")
            print(f"[alpha] State unchanged: {alpha.state('focus.alice')}")
        else:
            print(f"[alpha] Accepted (unexpected): {result}")

    # Now show legitimate Alice
    print("\n[legitimate alice]")
    alice_real = Fact.of("focus.alice", observer="alice", index=7)
    print(f"[alice] Sends focus.alice: observer={alice_real.observer}, index={alice_real.payload.get('index')}")

    result = alpha.receive(alice_real)
    if result is not None or alpha.state("focus.alice").get("index") == 7:
        print(f"[alpha] ACCEPTED: observer 'alice' owns focus.alice")
        print(f"[alpha] State updated: {alpha.state('focus.alice')}")

    print("\n--- Findings ---")
    print("- Observer-state ownership enforced at Vertex.receive()")
    print("- No wire format manipulation needed — observer is data")
    print("- Pattern: kind = focus.{owner}, fact.observer must equal owner")
    print("- Spoofing requires lying about observer — trust model question")


# =============================================================================
# SCENARIO 4: FAILURE (Connection failure with observer attribution)
# =============================================================================

async def failure_scenario():
    """Demonstrates failure facts with clear observer attribution.

    Pattern:
    1. Network monitor observes Alice's connection drop
    2. Emits connection.failed fact with observer="network-monitor"
    3. Payload contains target="alice" (what was observed)
    4. Observer = who saw it. Payload = what they saw.
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Failure (Observer attribution)")
    print("=" * 60)

    # Connection monitor vertex
    monitor = Vertex("network-monitor")
    monitor.register("connection.status", {"connections": {}}, connection_fold)

    print("\n[setup] network-monitor vertex tracks connection status")

    # Simulate connection events
    events = [
        ("alice", "connected"),
        ("bob", "connected"),
        ("alice", "failed"),  # Alice's connection drops
        ("charlie", "connected"),
    ]

    print("\n[events]")
    for target, status in events:
        # Network monitor observes the event
        fact = Fact.of(
            "connection.status",
            observer="network-monitor",
            target=target,
            status=status,
            ts=datetime.now(timezone.utc).isoformat(),
        )
        print(f"  [{fact.observer}] observes: {target} → {status}")
        monitor.receive(fact)

    # Check final state
    state = monitor.state("connection.status")
    print(f"\n[monitor] Connection state:")
    for target, info in state.get("connections", {}).items():
        print(f"  {target}: {info['status']} (observed by {info['observer']})")

    # Now forward failure fact to another vertex
    print("\n[forwarding failure to alert system]")

    alert_vertex = Vertex("alert-system")
    alert_vertex.register("connection.status", {"connections": {}}, connection_fold)

    # Monitor creates a fact for the alert system
    failure_fact = Fact.of(
        "connection.status",
        observer="network-monitor",  # Who observed the failure
        target="alice",
        status="failed",
        reason="heartbeat_timeout",
    )

    print(f"[network-monitor] Sends failure fact: observer={failure_fact.observer}")
    alert_vertex.receive(failure_fact)

    print(f"[alert-system] Received, state: {alert_vertex.state('connection.status')}")

    print("\n--- Findings ---")
    print("- Observer = who detected the event (network-monitor)")
    print("- Payload.target = whose connection failed (alice)")
    print("- Clear separation: observer vs subject of observation")
    print("- Same pattern works for all infrastructure facts")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all scenarios or specific one based on CLI arg."""

    scenarios = {
        "health": health_scenario,
        "observer_state": observer_state_scenario,
        "impersonation": impersonation_scenario,
        "failure": failure_scenario,
    }

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name in scenarios:
            await scenarios[name]()
        else:
            print(f"Unknown scenario: {name}")
            print(f"Available: {', '.join(scenarios.keys())}")
    else:
        print("Network + Observer: Facts crossing process boundaries")
        print("=" * 70)
        print("Running all scenarios...")

        for name, fn in scenarios.items():
            await fn()

        print("\n" + "=" * 70)
        print("SUMMARY: What the Observer model simplifies")
        print("=" * 70)
        print("""
1. WIRE FORMAT IS JUST FACT
   - Fact.to_dict() / Fact.from_dict()
   - No separate peer envelope
   - Observer field travels with the data

2. VERTEX.TO_FACT() BRIDGES BOUNDARIES
   - Tick stays internal
   - to_fact() creates Fact with vertex as observer
   - Provenance: original observer → forwarding vertex

3. OWNERSHIP IS ENFORCED AT RECEIVE
   - Observer-state kinds: focus.{name}, scroll.{name}, selection.{name}
   - Vertex.receive() checks: fact.observer == kind.owner
   - No network-layer changes needed

4. GRANT IS OPTIONAL POLICY
   - Identity (observer) is in the Fact
   - Permission (grant) is local policy
   - vertex.receive(fact, grant) — grant can be None

5. TRUST MODEL UNCHANGED
   - Trust the connection to send accurate facts
   - Verification (if needed) is composition-layer
   - Same as trusting imported code
""")


if __name__ == "__main__":
    asyncio.run(main())
