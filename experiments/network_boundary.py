"""Network boundary: vertices across process/network boundaries.

EXPLORATION: How do vertices discover and communicate across processes?

VOCABULARY.md mentions 'Connection' as a Vertex capability: "bridge across
process/network boundaries." This experiment explores what that means.

FINDINGS:
---------

1. SERIALIZATION: Ticks serialize naturally to JSON.
   - Tick is frozen dataclass with: name (str), ts (datetime), payload (dict), origin (str)
   - datetime needs ISO format conversion
   - payload is already dict-shaped in most cases

2. BRIDGE PRIMITIVE: asyncio.Queue simulates a network boundary.
   - In-process: Stream.emit() is direct async call
   - Cross-process: need serialize → transport → deserialize
   - Queue[bytes] models this: producer serializes, consumer deserializes

3. DISCOVERY: This experiment uses explicit wiring.
   - Producer vertex knows the queue to write to
   - Consumer vertex taps a stream fed from queue
   - Real discovery would need: registry, announcement, subscription protocol
   - Defer: "later, if patterns emerge"

4. FAILURE MODES:
   - Queue full: producer blocks (backpressure) or drops (lossy)
   - Consumer crash: producer doesn't know (fire-and-forget)
   - Connection drop: needs heartbeat or reconnect logic
   - This experiment: happy path only, notes failure modes

5. SAME MODEL WORKS:
   - Producer vertex: Facts in → fold → Tick out
   - Tick serializes, crosses boundary
   - Consumer vertex: Tick deserializes → becomes Fact (kind from tick.name)
   - Consumer folds, can emit its own Ticks
   - Loops nest across boundaries. The topology doesn't care about process.

ARCHITECTURE:
-------------

    Process A (producer)              Process B (consumer)
    ┌─────────────────────┐           ┌─────────────────────┐
    │ facts ──→ Vertex A  │           │ Vertex B ←── facts  │
    │            │        │           │    │                │
    │         boundary    │           │  (folds tick as     │
    │            │        │           │   input fact)       │
    │         Tick ───────┼──JSON──→──┼─→ Tick becomes Fact │
    └─────────────────────┘           └─────────────────────┘

    Queue[bytes] models the network pipe.

Run:
    uv run python experiments/network_boundary.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ticks import Tick, Vertex, Stream
from specs import Shape, Facet, Boundary


# -- Serialization -----------------------------------------------------------

def tick_to_json(tick: Tick) -> bytes:
    """Serialize Tick to JSON bytes for transport."""
    return json.dumps({
        "name": tick.name,
        "ts": tick.ts.isoformat(),
        "payload": tick.payload,
        "origin": tick.origin,
    }).encode("utf-8")


def json_to_tick(data: bytes) -> Tick:
    """Deserialize JSON bytes to Tick."""
    obj = json.loads(data.decode("utf-8"))
    return Tick(
        name=obj["name"],
        ts=datetime.fromisoformat(obj["ts"]),
        payload=obj["payload"],
        origin=obj["origin"],
    )


# -- Connection primitive ----------------------------------------------------

@dataclass
class Connection:
    """Bridge between two async contexts via serialized messages.

    Models a network boundary: messages are serialized, sent through a
    queue (simulating socket/pipe), and deserialized on the other side.

    In real deployment: queue becomes socket, pipe, or message broker.
    The serialization boundary is explicit — anything crossing must
    serialize.
    """

    queue: asyncio.Queue[bytes]
    name: str = ""

    async def send(self, tick: Tick) -> None:
        """Serialize and enqueue a tick."""
        await self.queue.put(tick_to_json(tick))

    async def receive(self) -> Tick:
        """Dequeue and deserialize a tick."""
        data = await self.queue.get()
        return json_to_tick(data)

    def send_nowait(self, tick: Tick) -> None:
        """Non-blocking send. Raises QueueFull if buffer exceeded."""
        self.queue.put_nowait(tick_to_json(tick))


# -- Shapes ------------------------------------------------------------------

# Producer: folds heartbeats, emits tick every N beats
heartbeat_shape = Shape(
    name="heartbeat",
    about="Count heartbeats, emit tick at boundary",
    input_facets=(Facet("seq", "int"),),
    state_facets=(Facet("count", "int"), Facet("last_seq", "int")),
    boundary=Boundary("heartbeat.close", reset=True),
)

# Consumer: aggregates ticks from producer
tick_summary_shape = Shape(
    name="heartbeat.tick",
    about="Aggregate heartbeat ticks from producer",
    input_facets=(Facet("count", "int"), Facet("last_seq", "int")),
    state_facets=(
        Facet("tick_count", "int"),
        Facet("total_beats", "int"),
    ),
)


# -- Folds -------------------------------------------------------------------

def heartbeat_fold(state: dict, payload: dict) -> dict:
    """Fold heartbeat facts."""
    return {
        "count": state.get("count", 0) + 1,
        "last_seq": payload.get("seq", 0),
    }


def tick_summary_fold(state: dict, payload: dict) -> dict:
    """Fold heartbeat ticks into summary."""
    return {
        "tick_count": state.get("tick_count", 0) + 1,
        "total_beats": state.get("total_beats", 0) + payload.get("count", 0),
    }


# -- Producer task (simulates Process A) -------------------------------------

async def producer_task(conn: Connection, stop_event: asyncio.Event) -> None:
    """Vertex A: produce heartbeat facts, emit ticks across boundary."""

    vertex = Vertex("producer")
    vertex.register(
        "heartbeat",
        heartbeat_shape.initial_state(),
        heartbeat_fold,
        boundary="heartbeat.close",
        reset=True,
    )

    seq = 0
    while not stop_event.is_set():
        # Simulate 3 heartbeats per cycle
        for _ in range(3):
            seq += 1
            vertex.receive("heartbeat", {"seq": seq})
            await asyncio.sleep(0.1)

        # Fire boundary → produces Tick
        tick = vertex.receive("heartbeat.close", {})
        if tick:
            print(f"[producer] tick #{tick.payload['count']} (seq {tick.payload['last_seq']})")
            await conn.send(tick)

        await asyncio.sleep(0.2)


# -- Consumer task (simulates Process B) -------------------------------------

async def consumer_task(conn: Connection, stop_event: asyncio.Event) -> None:
    """Vertex B: receive ticks from boundary, fold into summary."""

    vertex = Vertex("consumer")
    vertex.register(
        "heartbeat.tick",
        tick_summary_shape.initial_state(),
        tick_summary_fold,
    )

    while not stop_event.is_set():
        try:
            # Wait for tick with timeout (allows checking stop_event)
            tick = await asyncio.wait_for(conn.receive(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        # Tick from producer becomes fact to consumer
        # The tick.name determines routing kind
        vertex.receive(f"{tick.name}.tick", tick.payload)

        state = vertex.state("heartbeat.tick")
        print(
            f"[consumer] received tick from {tick.origin} | "
            f"total_ticks={state['tick_count']} total_beats={state['total_beats']}"
        )


# -- Main --------------------------------------------------------------------

async def main():
    """Run producer and consumer as separate async tasks with connection bridge."""

    print("Network boundary experiment")
    print("=" * 40)
    print("Producer vertex (A) emits heartbeat ticks")
    print("Connection serializes and transports")
    print("Consumer vertex (B) folds ticks as facts")
    print("=" * 40)
    print()

    # The boundary: an async queue modeling network transport
    # maxsize simulates bounded buffer (backpressure point)
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=10)
    conn = Connection(queue=queue, name="A→B")

    stop = asyncio.Event()

    # Launch "processes" as concurrent tasks
    producer = asyncio.create_task(producer_task(conn, stop))
    consumer = asyncio.create_task(consumer_task(conn, stop))

    # Run for a few seconds
    await asyncio.sleep(3.0)

    # Shutdown
    stop.set()
    await asyncio.gather(producer, consumer)

    print()
    print("=" * 40)
    print("Observations:")
    print("- Same loop model: facts → fold → tick")
    print("- Tick crossed boundary via JSON serialization")
    print("- Consumer treated tick.payload as fact input")
    print("- Origin preserved for provenance tracking")
    print()
    print("Open questions:")
    print("- Discovery: how does B find A? (registry, announcement)")
    print("- Failure: what if connection drops? (heartbeat, reconnect)")
    print("- Ordering: what if ticks arrive out of order? (sequence numbers)")
    print("- Backpressure: what if consumer is slow? (bounded queue, drop policy)")


if __name__ == "__main__":
    asyncio.run(main())
