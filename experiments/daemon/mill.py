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

TODO: Update load_shape() when spec file format lands. Currently uses legacy
string-based fold format in JSON. Should migrate to typed fold serialization
once the spec file format is finalized.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from data import Fact
from data import Collect, Count, Facet, Latest, Shape, Sum, Upsert
from vertex import Tick


# --- Shape loading ---


def _fold_from_dict(f: dict):
    """Convert a JSON fold dict to a typed fold class.

    TODO: This is a stopgap. Replace when spec file format is finalized.
    """
    op = f["op"]
    target = f["target"]
    props = f.get("props", {})

    if op == "latest":
        return Latest(target=target)
    elif op == "count":
        return Count(target=target)
    elif op == "sum":
        return Sum(target=target, field=props.get("field", target))
    elif op == "collect":
        return Collect(target=target, max=props.get("max", 0))
    elif op == "upsert":
        key = props.get("key")
        if not key:
            raise ValueError(f"upsert fold requires 'key' in props (target: {target})")
        return Upsert(target=target, key=key)
    else:
        raise ValueError(f"Unknown fold op: {op}")


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
        folds=tuple(_fold_from_dict(f) for f in spec.get("folds", [])),
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
