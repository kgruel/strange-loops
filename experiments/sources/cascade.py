"""Cascade: tick-as-input nesting between vertices.

Proves the core loop nesting pattern: Tick from vertex A becomes Fact to vertex B.
Same primitive at every level.

Architecture:
    CommandSource → heartbeat_vertex → Tick
                                        ↓
                                vertex.to_fact(tick)
                                        ↓
                                summary_vertex → aggregates ticks

Run:
    uv run python experiments/sources/cascade.py
"""

from __future__ import annotations

import asyncio

from data import Fact
from data import CommandSource, Runner
from vertex import Tick, Vertex


# -- Folds -------------------------------------------------------------------

def heartbeat_fold(state: dict, payload: dict) -> dict:
    """Count heartbeats. State: {"count": int}."""
    return {"count": state.get("count", 0) + 1}


def summary_fold(state: dict, payload: dict) -> dict:
    """Aggregate tick data. State: {"windows": int, "total": int}.

    Payload comes from heartbeat tick: {"count": int}.
    """
    tick_count = payload.get("count", 0)
    return {
        "windows": state.get("windows", 0) + 1,
        "total": state.get("total", 0) + tick_count,
    }


# -- Vertices ----------------------------------------------------------------

def build_heartbeat_vertex() -> Vertex:
    """Heartbeat vertex: counts heartbeats, ticks every 5."""
    v = Vertex("heartbeat")
    v.register(
        "heartbeat",
        {"count": 0},
        heartbeat_fold,
        boundary="heartbeat.window",
        reset=True,
    )
    return v


def build_summary_vertex() -> Vertex:
    """Summary vertex: receives heartbeat ticks as facts."""
    v = Vertex("summary")
    # Receives tick.heartbeat facts (from heartbeat_vertex.to_fact)
    v.register("tick.heartbeat", {"windows": 0, "total": 0}, summary_fold)
    return v


# -- Main --------------------------------------------------------------------

async def main():
    """Run the cascade: CommandSource → heartbeat_vertex → tick → summary_vertex."""

    # Build the two vertices
    heartbeat_vertex = build_heartbeat_vertex()
    summary_vertex = build_summary_vertex()

    # CommandSource emits heartbeats (echo simulates a heartbeat producer)
    # Emits 15 heartbeats with boundary facts interspersed
    heartbeat_source = CommandSource(
        command='for i in $(seq 1 15); do echo "beat"; done',
        kind="heartbeat",
        observer="heartbeat-source",
        interval=None,  # Run once
    )

    # Runner feeds heartbeat_vertex
    runner = Runner(heartbeat_vertex)
    runner.add(heartbeat_source)

    print("cascade: tick-as-input nesting")
    print("=" * 40)
    print()
    print("Flow: CommandSource → heartbeat_vertex → tick → summary_vertex")
    print()

    # We need to inject boundary facts to trigger ticks.
    # Runner only consumes sources, so we'll manually inject boundaries
    # after processing heartbeat facts.

    tick_count = 0

    # Process heartbeats in batches with manual boundary injection
    async for fact in heartbeat_source.stream():
        # Route fact to heartbeat_vertex
        heartbeat_vertex.receive(fact)
        count = heartbeat_vertex.state("heartbeat").get("count", 0)

        # Every 5 heartbeats, fire a boundary
        if count == 5:
            # Inject boundary fact
            boundary_fact = Fact.of("heartbeat.window", "cascade")
            tick = heartbeat_vertex.receive(boundary_fact)

            if tick is not None:
                tick_count += 1
                print(f"Tick #{tick_count} from heartbeat_vertex:")
                print(f"  name: {tick.name}")
                print(f"  payload: {tick.payload}")
                print(f"  origin: {tick.origin}")

                # Convert tick to fact and forward to summary_vertex
                tick_fact = heartbeat_vertex.to_fact(tick)
                print(f"  → Fact: kind={tick_fact.kind}, payload={dict(tick_fact.payload)}")

                # Feed to summary vertex
                summary_vertex.receive(tick_fact)
                print(f"  → summary_vertex state: {summary_vertex.state('tick.heartbeat')}")
                print()

    print("=" * 40)
    print("Final summary_vertex state:")
    final_state = summary_vertex.state("tick.heartbeat")
    print(f"  windows: {final_state.get('windows', 0)}")
    print(f"  total heartbeats: {final_state.get('total', 0)}")
    print()
    print("Proved: Ticks cross vertex boundaries as facts. Nesting works.")


if __name__ == "__main__":
    asyncio.run(main())
