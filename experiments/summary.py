"""Summary loop: ticks as input.

Proves the nesting claim: what's a Tick to one loop is a Fact to the next.
Reads review.ticks.jsonl and folds tick payloads into aggregate stats.

This is a loop that consumes the output of review.py's loops. The tick
payloads become this loop's facts. Same primitive at every level.

Run:
    uv run python experiments/summary.py
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

from ticks import Tick, Vertex
from shapes import Shape, Facet, Boundary


# -- Shapes ------------------------------------------------------------------
# This loop folds ticks, not raw observations. The "facts" here are tick
# payloads from review.py.

health_summary_shape = Shape(
    name="health.tick",
    about="Aggregate stats from health ticks",
    input_facets=(
        Facet("statuses", "dict"),  # the tick payload
    ),
    state_facets=(
        Facet("tick_count", "int"),
        Facet("total_containers", "int"),
        Facet("last_statuses", "dict"),
    ),
)

review_summary_shape = Shape(
    name="review.tick",
    about="Aggregate stats from review ticks",
    input_facets=(
        Facet("acked", "dict"),  # the tick payload
    ),
    state_facets=(
        Facet("cycle_count", "int"),
        Facet("total_acks", "int"),
        Facet("peers_seen", "set"),
    ),
)

# Meta shape: fires a boundary every N ticks processed
batch_shape = Shape(
    name="batch",
    about="Batch counter for summary ticks",
    input_facets=(Facet("tick_name", "str"),),
    state_facets=(Facet("count", "int"),),
    boundary=Boundary("batch.complete", reset=True),
)


# -- Folds -------------------------------------------------------------------

def health_summary_fold(state: dict, payload: dict) -> dict:
    """Fold a health tick into aggregate stats."""
    statuses = payload.get("statuses", {})
    return {
        "tick_count": state.get("tick_count", 0) + 1,
        "total_containers": state.get("total_containers", 0) + len(statuses),
        "last_statuses": statuses,
    }


def review_summary_fold(state: dict, payload: dict) -> dict:
    """Fold a review tick into aggregate stats."""
    acked = payload.get("acked", {})
    peers_seen = set(state.get("peers_seen", set()))
    peers_seen.update(acked.values())
    return {
        "cycle_count": state.get("cycle_count", 0) + 1,
        "total_acks": state.get("total_acks", 0) + len(acked),
        "peers_seen": peers_seen,
    }


def batch_fold(state: dict, payload: dict) -> dict:
    """Count ticks processed."""
    return {"count": state.get("count", 0) + 1}


# -- Topology ----------------------------------------------------------------

SHAPES = [
    (health_summary_shape, health_summary_fold),
    (review_summary_shape, review_summary_fold),
    (batch_shape, batch_fold),
]

BATCH_SIZE = 5  # Fire summary tick every N ticks processed


def build_vertex() -> Vertex:
    """Vertex that folds ticks from review.py."""
    v = Vertex("summary")
    for shape, fold in SHAPES:
        if shape.boundary is not None:
            v.register(
                shape.name,
                shape.initial_state(),
                fold,
                boundary=shape.boundary.kind,
                reset=shape.boundary.reset,
            )
        else:
            v.register(shape.name, shape.initial_state(), fold)
    return v


# -- Main --------------------------------------------------------------------

def load_ticks(path: Path) -> list[dict]:
    """Load ticks from JSONL file."""
    if not path.exists():
        return []

    ticks = []
    for line in path.read_text().strip().split("\n"):
        if not line:
            continue
        try:
            ticks.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return ticks


def main():
    tick_path = Path("review.ticks.jsonl")
    ticks = load_ticks(tick_path)

    if not ticks:
        print("No ticks found in review.ticks.jsonl")
        print("Run review.py first to generate some ticks.")
        return

    print(f"Loaded {len(ticks)} ticks from {tick_path}")
    print()

    vertex = build_vertex()
    summary_ticks: list[Tick] = []

    for tick_data in ticks:
        name = tick_data["name"]
        payload = tick_data["payload"]

        # Route tick to appropriate fold based on its origin
        if name == "health":
            vertex.receive("health.tick", payload)
        elif name == "ack":
            vertex.receive("review.tick", payload)

        # Also count for batch boundary
        vertex.receive("batch", {"tick_name": name})

        # Check if batch boundary should fire
        batch_state = vertex.state("batch")
        if batch_state.get("count", 0) >= BATCH_SIZE:
            tick = vertex.receive("batch.complete", {})
            if tick:
                summary_ticks.append(tick)
                print(f"  → Summary tick #{len(summary_ticks)} after {BATCH_SIZE} ticks")

    print()
    print("=" * 60)
    print("SUMMARY (ticks folded into aggregate state)")
    print("=" * 60)
    print()

    health = vertex.state("health.tick")
    print("Health ticks:")
    print(f"  Total ticks: {health.get('tick_count', 0)}")
    print(f"  Total container observations: {health.get('total_containers', 0)}")
    if health.get("last_statuses"):
        print(f"  Last statuses: {health['last_statuses']}")
    print()

    review = vertex.state("review.tick")
    print("Review ticks:")
    print(f"  Completed cycles: {review.get('cycle_count', 0)}")
    print(f"  Total acks: {review.get('total_acks', 0)}")
    if review.get("peers_seen"):
        print(f"  Peers seen: {review['peers_seen']}")
    print()

    print(f"Summary ticks emitted: {len(summary_ticks)}")
    print()
    print("This loop treated review.py's Ticks as its Facts.")
    print("Same primitive at every level.")


if __name__ == "__main__":
    main()
