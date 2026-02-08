"""Heartbeat: simplest meaningful source experiment.

Purpose: Liveness check — "Is it still alive?"

Flow:
    CommandSource → Fact("heartbeat") → Vertex → Fold(last_seen) → Query(staleness)

This proves:
    - Source produces facts on interval
    - Facts flow through Runner to Vertex
    - Fold accumulates state with purpose
    - Consumer (liveness check) gives the fold meaning
"""

import asyncio
from datetime import datetime, timezone

from vertex import Vertex
from atoms import CommandSource, Runner


def now_ts() -> float:
    """Current timestamp."""
    return datetime.now(timezone.utc).timestamp()


async def main():
    # Vertex with liveness fold
    vertex = Vertex("heartbeat")
    vertex.register(
        "heartbeat",
        initial={"last_seen": None, "count": 0},
        fold=lambda state, payload: {
            "last_seen": now_ts(),
            "count": state["count"] + 1,
        },
    )

    # Source: emit timestamp every second
    source = CommandSource(
        command="date +%s",
        kind="heartbeat",
        observer="timer",
        interval=1.0,
    )

    runner = Runner(vertex)
    runner.add(source)

    print("Heartbeat liveness check")
    print("=" * 40)
    print("Source emits every 1s, liveness checks every 2s")
    print("Will simulate stale after 5 heartbeats by stopping source")
    print()

    # Consumer: periodic liveness check
    async def check_liveness():
        stale_threshold = 3.0  # seconds
        while True:
            await asyncio.sleep(2.0)
            state = vertex.state("heartbeat")

            if state["last_seen"] is None:
                print(f"[liveness] No heartbeat yet")
                continue

            age = now_ts() - state["last_seen"]
            status = "STALE!" if age > stale_threshold else "alive"
            print(f"[liveness] count={state['count']}, age={age:.1f}s → {status}")

    # Run source for limited time, then let it go stale
    async def run_with_timeout():
        count = 0
        async for _ in runner.run():
            count += 1
            # No ticks expected (no boundary), but loop handles source lifecycle

    liveness_task = asyncio.create_task(check_liveness())

    try:
        # Run for 5 seconds, then stop source to demonstrate staleness
        await asyncio.wait_for(run_with_timeout(), timeout=5.0)
    except asyncio.TimeoutError:
        print("\n[source] Stopped after 5s — will go stale\n")

    # Keep checking liveness to see staleness
    await asyncio.sleep(6.0)

    liveness_task.cancel()
    print()
    print(f"Final state: {vertex.state('heartbeat')}")


if __name__ == "__main__":
    asyncio.run(main())
