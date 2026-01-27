"""mill — the daemon primitive.

A running Projection with an open input. The smallest thing that turns
static atoms into a live system.

    stdin (JSON lines) → fold via Shape → stdout (JSON ticks)

Usage:
    echo '{"kind":"x","ts":1234,"payload":{"v":1}}' | uv run python experiments/daemon/mill.py shape.json

The shape spec is a JSON file:
    {
        "name": "counter",
        "about": "counts events",
        "input_facets": [{"name": "v", "kind": "int"}],
        "state_facets": [{"name": "total", "kind": "int"}],
        "folds": [{"op": "count", "target": "total"}]
    }
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from facts import Fact
from shapes import Facet, Fold, Shape
from ticks import Tick


# --- Shape loading ---


def load_shape(path: str) -> Shape:
    """Load a Shape from a JSON spec file."""
    with open(path) as f:
        spec = json.load(f)
    return Shape(
        name=spec["name"],
        about=spec.get("about", ""),
        input_facets=tuple(
            Facet(name=f["name"], kind=f["kind"], optional=f.get("optional", False))
            for f in spec.get("input_facets", [])
        ),
        state_facets=tuple(
            Facet(name=f["name"], kind=f["kind"], optional=f.get("optional", False))
            for f in spec.get("state_facets", [])
        ),
        folds=tuple(
            Fold(op=f["op"], target=f["target"], props=f.get("props", {}))
            for f in spec.get("folds", [])
        ),
    )


# --- Fact → Shape bridge ---


def bridge(fact: Fact, shape: Shape, state: dict) -> dict:
    """Extract payload from Fact and fold through Shape.

    This is the ~3-line bridge at the composition point (per CLAUDE.md
    conventions). It touches both Fact and Shape — lives here in the
    integration layer, not in either lib.
    """
    payload = dict(fact.payload) if hasattr(fact.payload, "keys") else fact.payload
    payload["_ts"] = fact.ts
    return shape.apply(state, payload)


# --- Tick emission ---


def emit_tick(ts: float, state: dict) -> None:
    """Write a Tick as a JSON line to stdout."""
    tick = Tick(
        ts=datetime.fromtimestamp(ts, tz=timezone.utc),
        payload=state,
    )
    line = json.dumps({"ts": tick.ts.isoformat(), "payload": tick.payload})
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# --- The loop ---


def run(shape: Shape) -> None:
    """The daemon loop: receive → fold → emit → repeat."""
    state = shape.initial_state()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        fact = Fact.from_dict(json.loads(line))
        state = bridge(fact, shape, state)
        emit_tick(fact.ts, state)


# --- Entry ---


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: mill.py <shape.json>", file=sys.stderr)
        sys.exit(1)

    shape = load_shape(sys.argv[1])
    run(shape)


if __name__ == "__main__":
    main()
