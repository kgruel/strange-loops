"""Network boundary extended: discovery, failure, ordering, backpressure.

EXPLORATION: Each scenario explores one open question from network_boundary.py.

Run all scenarios:
    uv run python experiments/network_boundary_extended.py

Run specific scenario:
    uv run python experiments/network_boundary_extended.py discovery
    uv run python experiments/network_boundary_extended.py failure
    uv run python experiments/network_boundary_extended.py ordering
    uv run python experiments/network_boundary_extended.py backpressure

SCENARIOS:
----------

1. DISCOVERY: How does B find A?
   - Registry pattern: producers register, consumers lookup
   - Announcement: producer publishes presence, consumers subscribe
   - The registry is just another vertex — facts in, state out

2. FAILURE: What if connection drops?
   - Heartbeat: periodic liveness signal
   - Reconnect: consumer detects timeout, attempts recovery
   - Failure is observable — it becomes a fact

3. ORDERING: What if ticks arrive out of order?
   - Sequence numbers on ticks
   - Consumer detects gaps, can request replay or proceed with warning
   - Out-of-order is a fact, not an error — the fold decides what to do

4. BACKPRESSURE: What if consumer is slow?
   - Bounded queue with explicit policy
   - Drop oldest, drop newest, or block producer
   - Dropped ticks become facts (observable)
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Any
from enum import Enum

from vertex import Tick, Vertex
from data import Shape, Facet, Boundary


# -- Serialization (from network_boundary.py) --------------------------------

def tick_to_json(tick: Tick) -> bytes:
    return json.dumps({
        "name": tick.name,
        "ts": tick.ts.isoformat(),
        "payload": tick.payload,
        "origin": tick.origin,
    }).encode("utf-8")


def json_to_tick(data: bytes) -> Tick:
    obj = json.loads(data.decode("utf-8"))
    return Tick(
        name=obj["name"],
        ts=datetime.fromisoformat(obj["ts"]),
        payload=obj["payload"],
        origin=obj["origin"],
    )


# =============================================================================
# SCENARIO 1: DISCOVERY
# =============================================================================

@dataclass
class Registry:
    """A registry is a vertex that tracks producer presence.

    Producers register by emitting 'register' facts.
    Consumers query the registry to find producers.
    The registry is just state that accumulates from facts.
    """

    _producers: dict[str, dict] = field(default_factory=dict)
    _queues: dict[str, asyncio.Queue[bytes]] = field(default_factory=dict)

    def register(self, name: str, endpoint: asyncio.Queue[bytes], metadata: dict | None = None) -> None:
        """Producer registers itself."""
        self._producers[name] = {
            "name": name,
            "registered_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        self._queues[name] = endpoint

    def unregister(self, name: str) -> None:
        """Producer unregisters (clean shutdown)."""
        self._producers.pop(name, None)
        self._queues.pop(name, None)

    def lookup(self, name: str) -> asyncio.Queue[bytes] | None:
        """Consumer looks up a producer by name."""
        return self._queues.get(name)

    def list_producers(self) -> list[dict]:
        """List all registered producers."""
        return list(self._producers.values())


async def discovery_scenario():
    """Demonstrates registry-based discovery.

    Pattern:
    1. Registry exists (could be a vertex, keeping it simple here)
    2. Producer registers with name + endpoint
    3. Consumer queries registry to find producer
    4. Connection established via looked-up endpoint
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Discovery via Registry")
    print("=" * 60)

    registry = Registry()

    # Producer registers itself
    producer_queue: asyncio.Queue[bytes] = asyncio.Queue()
    registry.register("heartbeat-producer", producer_queue, {"version": "1.0"})

    print(f"\n[registry] Producer registered: {registry.list_producers()}")

    # Consumer discovers producer
    endpoint = registry.lookup("heartbeat-producer")
    if endpoint is None:
        print("[consumer] Producer not found!")
        return

    print("[consumer] Found producer via registry")

    # Now they can communicate
    # Producer sends a tick
    tick = Tick(
        name="heartbeat",
        ts=datetime.now(timezone.utc),
        payload={"count": 1, "seq": 10},
        origin="heartbeat-producer",
    )
    await endpoint.put(tick_to_json(tick))
    print(f"[producer] Sent tick: {tick.payload}")

    # Consumer receives via the discovered endpoint
    data = await endpoint.get()
    received_tick = json_to_tick(data)
    print(f"[consumer] Received tick from {received_tick.origin}: {received_tick.payload}")

    # Clean shutdown
    registry.unregister("heartbeat-producer")
    print(f"[registry] After unregister: {registry.list_producers()}")

    print("\n--- Findings ---")
    print("- Registry is state: name → endpoint mapping")
    print("- Could be a vertex: 'register' facts fold into producer list")
    print("- Discovery before connection: consumer looks up, then connects")
    print("- Registration as fact enables: audit trail, announcements, TTL")


# =============================================================================
# SCENARIO 2: FAILURE
# =============================================================================

@dataclass
class HeartbeatConnection:
    """Connection with heartbeat for liveness detection."""

    queue: asyncio.Queue[bytes]
    name: str
    heartbeat_interval: float = 0.5
    timeout: float = 1.5
    _last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    _alive: bool = True

    async def send(self, tick: Tick) -> bool:
        """Send tick. Returns False if connection dead."""
        if not self._alive:
            return False
        try:
            await asyncio.wait_for(
                self.queue.put(tick_to_json(tick)),
                timeout=0.5
            )
            return True
        except asyncio.TimeoutError:
            self._alive = False
            return False

    async def receive(self) -> Tick | None:
        """Receive tick. Returns None if timeout (possible failure)."""
        try:
            data = await asyncio.wait_for(
                self.queue.get(),
                timeout=self.timeout
            )
            tick = json_to_tick(data)
            self._last_heartbeat = datetime.now(timezone.utc)
            return tick
        except asyncio.TimeoutError:
            # Check if we've exceeded heartbeat timeout
            elapsed = (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
            if elapsed > self.timeout:
                self._alive = False
            return None

    def is_alive(self) -> bool:
        return self._alive

    def mark_dead(self) -> None:
        self._alive = False


async def failure_scenario():
    """Demonstrates failure detection and reconnection.

    Pattern:
    1. Connection has heartbeat expectation
    2. Missing heartbeats trigger failure detection
    3. Failure is observable (becomes a fact)
    4. Consumer can attempt reconnection
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Failure Detection")
    print("=" * 60)

    queue: asyncio.Queue[bytes] = asyncio.Queue()
    conn = HeartbeatConnection(queue=queue, name="test", timeout=0.8)

    # Simulate producer sending heartbeats, then stopping
    async def flaky_producer(conn: HeartbeatConnection, fail_after: int):
        for i in range(fail_after):
            tick = Tick(
                name="heartbeat",
                ts=datetime.now(timezone.utc),
                payload={"seq": i, "type": "heartbeat"},
                origin="flaky-producer",
            )
            await conn.send(tick)
            print(f"[producer] Sent heartbeat {i}")
            await asyncio.sleep(0.3)
        print("[producer] Simulating crash (no more heartbeats)")

    # Consumer with failure detection
    async def watchful_consumer(conn: HeartbeatConnection):
        received = 0
        while conn.is_alive():
            tick = await conn.receive()
            if tick:
                received += 1
                print(f"[consumer] Got heartbeat: seq={tick.payload.get('seq')}")
            else:
                if not conn.is_alive():
                    print("[consumer] Connection failure detected!")
                    # This would be a fact: ("connection.failed", {origin: "flaky-producer"})
                    break
                print("[consumer] Timeout, but connection still alive")
        print(f"[consumer] Total received before failure: {received}")

    # Run both
    await asyncio.gather(
        flaky_producer(conn, fail_after=3),
        watchful_consumer(conn),
    )

    print("\n--- Findings ---")
    print("- Heartbeat timeout defines 'liveness'")
    print("- Failure detection at consumer: missing expected heartbeats")
    print("- Failure is a fact: 'connection.failed' could enter a vertex")
    print("- Reconnect is composition-layer: lookup registry, establish new connection")


# =============================================================================
# SCENARIO 3: ORDERING
# =============================================================================

@dataclass
class SequencedTick:
    """Tick with explicit sequence number for ordering."""
    tick: Tick
    seq: int


@dataclass
class OrderedConnection:
    """Connection that tracks sequence numbers for ordering."""

    queue: asyncio.Queue[bytes]
    name: str
    _send_seq: int = 0
    _recv_seq: int = 0
    _gaps: list[int] = field(default_factory=list)

    async def send(self, tick: Tick) -> int:
        """Send with sequence number. Returns the sequence assigned."""
        self._send_seq += 1
        envelope = {
            "seq": self._send_seq,
            "tick": {
                "name": tick.name,
                "ts": tick.ts.isoformat(),
                "payload": tick.payload,
                "origin": tick.origin,
            }
        }
        await self.queue.put(json.dumps(envelope).encode("utf-8"))
        return self._send_seq

    async def receive(self) -> tuple[Tick, int, list[int]]:
        """Receive tick. Returns (tick, seq, gaps_detected)."""
        data = await self.queue.get()
        envelope = json.loads(data.decode("utf-8"))
        seq = envelope["seq"]
        tick_data = envelope["tick"]
        tick = Tick(
            name=tick_data["name"],
            ts=datetime.fromisoformat(tick_data["ts"]),
            payload=tick_data["payload"],
            origin=tick_data["origin"],
        )

        # Detect gaps
        gaps = []
        expected = self._recv_seq + 1
        if seq > expected:
            gaps = list(range(expected, seq))
            self._gaps.extend(gaps)

        self._recv_seq = max(self._recv_seq, seq)
        return tick, seq, gaps

    def get_gaps(self) -> list[int]:
        return self._gaps.copy()


async def ordering_scenario():
    """Demonstrates sequence numbers for ordering detection.

    Pattern:
    1. Each tick gets a sequence number at send
    2. Consumer tracks expected sequence
    3. Gaps are detected and become observable
    4. Out-of-order is information, not necessarily error
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Ordering via Sequence Numbers")
    print("=" * 60)

    queue: asyncio.Queue[bytes] = asyncio.Queue()

    # Two connections for simulating out-of-order delivery
    # In reality this would be network reordering
    send_conn = OrderedConnection(queue=queue, name="sender")
    recv_conn = OrderedConnection(queue=queue, name="receiver")

    # Send ticks
    ticks_to_send = [
        Tick("event", datetime.now(timezone.utc), {"data": "first"}, "producer"),
        Tick("event", datetime.now(timezone.utc), {"data": "second"}, "producer"),
        Tick("event", datetime.now(timezone.utc), {"data": "third"}, "producer"),
    ]

    print("\n[producer] Sending 3 ticks in order...")
    for tick in ticks_to_send:
        seq = await send_conn.send(tick)
        print(f"  Sent seq={seq}: {tick.payload}")

    print("\n[consumer] Receiving ticks...")
    for _ in range(3):
        tick, seq, gaps = await recv_conn.receive()
        gap_info = f" (gaps detected: {gaps})" if gaps else ""
        print(f"  Received seq={seq}: {tick.payload}{gap_info}")

    # Now simulate out-of-order by manually manipulating the queue
    print("\n[simulating out-of-order delivery]")

    # Reset receiver
    recv_conn._recv_seq = 0
    recv_conn._gaps = []

    # Send seq 1, 2, 5 (missing 3, 4)
    for i, data in enumerate(["a", "b", "e"], start=1):
        seq_to_use = i if i <= 2 else 5
        envelope = {
            "seq": seq_to_use,
            "tick": {
                "name": "event",
                "ts": datetime.now(timezone.utc).isoformat(),
                "payload": {"data": data},
                "origin": "producer",
            }
        }
        await queue.put(json.dumps(envelope).encode("utf-8"))

    print("[consumer] Receiving with gaps...")
    for _ in range(3):
        tick, seq, gaps = await recv_conn.receive()
        gap_info = f" (gaps: {gaps})" if gaps else ""
        print(f"  Received seq={seq}: {tick.payload}{gap_info}")

    print(f"\n[consumer] All gaps detected: {recv_conn.get_gaps()}")

    print("\n--- Findings ---")
    print("- Sequence numbers make ordering explicit")
    print("- Gaps are detectable: expected vs actual")
    print("- Gap is a fact: 'sequence.gap' with missing range")
    print("- Fold decides policy: wait for replay, proceed with warning, fail")
    print("- In loop model: out-of-order is information, consumer's fold handles it")


# =============================================================================
# SCENARIO 4: BACKPRESSURE
# =============================================================================

class DropPolicy(Enum):
    BLOCK = "block"       # Block producer until space available
    DROP_OLDEST = "drop_oldest"  # Drop oldest message to make room
    DROP_NEWEST = "drop_newest"  # Drop incoming message if full


@dataclass
class BackpressureConnection:
    """Connection with explicit backpressure policy."""

    queue: asyncio.Queue[bytes]
    name: str
    max_size: int
    policy: DropPolicy
    _dropped: list[dict] = field(default_factory=list)

    async def send(self, tick: Tick) -> dict:
        """Send with backpressure handling. Returns status."""
        data = tick_to_json(tick)

        if self.policy == DropPolicy.BLOCK:
            await self.queue.put(data)
            return {"status": "sent", "dropped": None}

        if self.queue.qsize() >= self.max_size:
            if self.policy == DropPolicy.DROP_OLDEST:
                # Remove oldest to make room
                try:
                    dropped_data = self.queue.get_nowait()
                    dropped_tick = json_to_tick(dropped_data)
                    drop_info = {
                        "seq": dropped_tick.payload.get("seq"),
                        "reason": "backpressure",
                        "policy": "drop_oldest",
                    }
                    self._dropped.append(drop_info)
                    await self.queue.put(data)
                    return {"status": "sent", "dropped": drop_info}
                except asyncio.QueueEmpty:
                    pass

            elif self.policy == DropPolicy.DROP_NEWEST:
                # Drop the incoming message
                drop_info = {
                    "seq": tick.payload.get("seq"),
                    "reason": "backpressure",
                    "policy": "drop_newest",
                }
                self._dropped.append(drop_info)
                return {"status": "dropped", "dropped": drop_info}

        # Queue has room
        await self.queue.put(data)
        return {"status": "sent", "dropped": None}

    async def receive(self) -> Tick:
        data = await self.queue.get()
        return json_to_tick(data)

    def get_dropped(self) -> list[dict]:
        return self._dropped.copy()


async def backpressure_scenario():
    """Demonstrates backpressure with different policies.

    Pattern:
    1. Bounded queue has explicit capacity
    2. When full, policy determines behavior
    3. Dropped messages are observable (facts)
    4. Consumer speed determines effective throughput
    """

    print("\n" + "=" * 60)
    print("SCENARIO: Backpressure Policies")
    print("=" * 60)

    async def test_policy(policy: DropPolicy, max_size: int):
        queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max_size if policy == DropPolicy.BLOCK else 0)
        # For DROP policies, we manage size ourselves
        if policy != DropPolicy.BLOCK:
            queue = asyncio.Queue()  # Unbounded, we manage size in connection

        conn = BackpressureConnection(
            queue=queue,
            name=f"test-{policy.value}",
            max_size=max_size,
            policy=policy,
        )

        print(f"\n[Policy: {policy.value}, max_size={max_size}]")

        # Fast producer, slow consumer
        async def fast_producer():
            for i in range(8):
                tick = Tick(
                    name="data",
                    ts=datetime.now(timezone.utc),
                    payload={"seq": i},
                    origin="producer",
                )
                result = await conn.send(tick)
                status = result["status"]
                dropped = result.get("dropped")
                if dropped:
                    print(f"  [producer] seq={i} → {status}, dropped seq={dropped.get('seq')}")
                else:
                    print(f"  [producer] seq={i} → {status}")
                await asyncio.sleep(0.05)  # Fast

        async def slow_consumer():
            received = []
            for _ in range(8):
                try:
                    tick = await asyncio.wait_for(conn.receive(), timeout=0.3)
                    received.append(tick.payload.get("seq"))
                    print(f"  [consumer] received seq={tick.payload.get('seq')}")
                except asyncio.TimeoutError:
                    break
                await asyncio.sleep(0.2)  # Slow
            return received

        if policy == DropPolicy.BLOCK:
            # For blocking, we need to run differently
            print("  (block policy would block producer - showing drop policies instead)")
            return

        producer_task = asyncio.create_task(fast_producer())
        consumer_task = asyncio.create_task(slow_consumer())

        await producer_task
        received = await consumer_task

        print(f"  [summary] Sent: 8, Received: {len(received)}, Dropped: {len(conn.get_dropped())}")
        if conn.get_dropped():
            print(f"  [dropped] {[d.get('seq') for d in conn.get_dropped()]}")

    await test_policy(DropPolicy.DROP_OLDEST, max_size=3)
    await test_policy(DropPolicy.DROP_NEWEST, max_size=3)

    print("\n--- Findings ---")
    print("- Backpressure is explicit: bounded queue + policy")
    print("- Drop events are facts: 'message.dropped' with seq and reason")
    print("- Policy is composition choice: same primitives, different behavior")
    print("- Trade-off: latency (block) vs completeness (drop oldest) vs freshness (drop newest)")
    print("- In loop model: drops fold into state, observable like any other fact")


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Run all scenarios or specific one based on CLI arg."""

    scenarios = {
        "discovery": discovery_scenario,
        "failure": failure_scenario,
        "ordering": ordering_scenario,
        "backpressure": backpressure_scenario,
    }

    if len(sys.argv) > 1:
        name = sys.argv[1]
        if name in scenarios:
            await scenarios[name]()
        else:
            print(f"Unknown scenario: {name}")
            print(f"Available: {', '.join(scenarios.keys())}")
    else:
        print("Network Boundary Extended: Discovery, Failure, Ordering, Backpressure")
        print("=" * 70)
        print("Running all scenarios...")

        for name, fn in scenarios.items():
            await fn()

        print("\n" + "=" * 70)
        print("SUMMARY: Patterns that emerged")
        print("=" * 70)
        print("""
1. EVERYTHING IS A FACT
   - Registration: 'producer.registered' fact
   - Failure: 'connection.failed' fact
   - Gaps: 'sequence.gap' fact
   - Drops: 'message.dropped' fact

   The network concerns become observable through the same mechanism.
   They fold into state. They can trigger boundaries. Same model.

2. COMPOSITION LAYER DECIDES POLICY
   - Discovery: registry vs announcement vs subscription
   - Failure: timeout duration, reconnect strategy
   - Ordering: wait vs proceed vs fail on gaps
   - Backpressure: block vs drop-oldest vs drop-newest

   The primitives don't change. The wiring chooses behavior.

3. NETWORK IS JUST ANOTHER BOUNDARY
   - Same pattern: serialize → transport → deserialize
   - Tick crosses process like it crosses function call
   - The topology doesn't care about physical location
   - Composition layer handles the translation

4. FAILURE MODES ARE FACTS
   - Traditional: exceptions, error codes, retries
   - Loop model: failure is observed, becomes fact, folds
   - The consumer's fold decides what 'failure' means
   - Reconnect is just another fact entering the vertex
""")


if __name__ == "__main__":
    asyncio.run(main())
