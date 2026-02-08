"""Heartbeat rate experiment: Source -> Fold -> Boundary -> Tick.

Proves the full egress path. A heartbeat source emits facts, a fold
accumulates count, a boundary fires every N heartbeats, and the
consumer receives Ticks.

Run:
    uv run python experiments/sources/heartbeat_rate.py
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from atoms import Fact
from atoms import Runner
from vertex import Tick, Vertex


class HeartbeatSource:
    """Source that emits heartbeat facts at a fixed interval.

    Emits N heartbeats, then a boundary fact to trigger the tick.
    """

    def __init__(
        self,
        observer: str = "heartbeat",
        *,
        interval: float = 0.2,
        window: int = 5,
        cycles: int = 3,
    ) -> None:
        self._observer = observer
        self._interval = interval
        self._window = window  # heartbeats per tick
        self._cycles = cycles  # how many ticks to emit

    @property
    def observer(self) -> str:
        return self._observer

    async def stream(self) -> AsyncIterator[Fact]:
        """Yield heartbeat facts, with boundary facts every window."""
        for cycle in range(self._cycles):
            # Emit window heartbeats
            for beat in range(self._window):
                yield Fact.of("heartbeat", self._observer, beat=beat, cycle=cycle)
                await asyncio.sleep(self._interval)

            # Emit boundary to trigger tick
            yield Fact.of("heartbeat.close", self._observer)


async def main() -> None:
    """Run the heartbeat rate experiment."""
    # Build vertex with heartbeat fold and boundary
    vertex = Vertex("rate-meter")
    vertex.register(
        "heartbeat",
        initial={"count": 0},
        fold=lambda s, p: {"count": s["count"] + 1},
        boundary="heartbeat.close",
        reset=True,
    )

    # Wire source to vertex via runner
    runner = Runner(vertex)
    runner.add(HeartbeatSource(interval=0.1, window=5, cycles=3))

    # Consume ticks as they fire
    print("Heartbeat rate experiment")
    print("=" * 40)
    print("Source emits 5 heartbeats, then boundary")
    print("Fold counts, tick emits with count, reset")
    print("=" * 40)
    print()

    tick_count = 0
    async for tick in runner.run():
        tick_count += 1
        print(f"Tick {tick_count}: {tick.payload} (origin={tick.origin})")

    print()
    print("=" * 40)
    print(f"Done. Received {tick_count} ticks.")


if __name__ == "__main__":
    asyncio.run(main())
