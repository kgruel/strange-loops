"""Tick.since: fidelity traversal from tick to facts.

Demonstrates the fidelity traversal pattern: given a Tick, retrieve the
facts that were folded to produce it using Tick.since + Store.between().

Scenario: Incident monitoring
    - Facts accumulate during an incident (alerts, metrics, actions)
    - Boundary fires on resolution → Tick with summary
    - Query: "What happened during this incident?"
    - Answer: Store.between(tick.since, tick.ts) → all contributing facts

This proves:
    1. Tick.since enables period reconstruction
    2. Re-folding retrieved facts produces the same payload
    3. The pattern generalizes to any bounded accumulation

Run:
    uv run python experiments/temporal/tick_since.py
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from atoms import Fact
from engine import Peer, Tick, Vertex, Loop
from engine.projection import Projection
from engine.store import EventStore


# -- Domain Types ------------------------------------------------------------

@dataclass
class IncidentSummary:
    """What a resolved incident tick contains."""
    resolved: bool
    duration_sec: float
    alert_count: int
    action_count: int
    final_severity: str


# -- Folds -------------------------------------------------------------------

def incident_fold(state: dict, payload: dict) -> dict:
    """Accumulate incident facts into summary state."""
    kind = payload.get("_kind", "")

    if kind == "alert":
        return {
            **state,
            "alert_count": state.get("alert_count", 0) + 1,
            "severities": state.get("severities", []) + [payload.get("severity", "info")],
        }
    elif kind == "metric":
        return {
            **state,
            "metrics": state.get("metrics", []) + [{
                "name": payload.get("name"),
                "value": payload.get("value"),
            }],
        }
    elif kind == "action":
        action = payload.get("action")
        new_state = {
            **state,
            "action_count": state.get("action_count", 0) + 1,
            "actions": state.get("actions", []) + [action],
        }
        # Mark resolved when the resolve action is taken
        if action == "resolve":
            severities = state.get("severities", [])
            final = max(severities, key=lambda s: {"info": 0, "warning": 1, "critical": 2}.get(s, 0)) if severities else "info"
            new_state["resolved"] = True
            new_state["final_severity"] = final
        return new_state
    return state


# -- Experiment --------------------------------------------------------------

SYSTEM = Peer("system")
OPERATOR = Peer("operator")


def generate_incident_facts(start_time: float, observer: str) -> list[Fact]:
    """Generate a sequence of facts simulating an incident."""
    facts = []
    t = start_time

    # Alert: CPU high
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "alert", "severity": "warning", "message": "CPU usage elevated"},
        observer=observer,
    ))
    t += 30  # 30 seconds later

    # Metric: CPU at 85%
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "metric", "name": "cpu", "value": 85},
        observer=observer,
    ))
    t += 45

    # Alert: escalates to critical
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "alert", "severity": "critical", "message": "CPU critical, affecting users"},
        observer=observer,
    ))
    t += 60

    # Action: operator scales out
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "action", "action": "scale_out", "by": "operator"},
        observer=observer,
    ))
    t += 120

    # Metric: CPU recovering
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "metric", "name": "cpu", "value": 45},
        observer=observer,
    ))
    t += 30

    # Action: mark resolved
    facts.append(Fact(
        kind="incident",
        ts=t,
        payload={"_kind": "action", "action": "resolve", "by": "operator"},
        observer=observer,
    ))
    t += 5

    # Resolve boundary
    facts.append(Fact(
        kind="incident.resolve",
        ts=t,
        payload={"_kind": "resolve"},
        observer=observer,
    ))

    return facts


def reconstruct_from_tick(tick: Tick, store: EventStore) -> list[Fact]:
    """Fidelity traversal: retrieve facts that produced this tick."""
    if tick.since is None:
        print("  (no fidelity info - tick.since is None)")
        return []
    return store.between(tick.since, tick.ts)


def refold(facts: list[Fact], fold_fn, initial: dict) -> dict:
    """Re-fold facts to verify fidelity."""
    state = dict(initial)
    for fact in facts:
        if fact.kind == "incident":  # only fold the main kind, not boundary
            state = fold_fn(state, fact.payload)
    return state


def main():
    print("=" * 60)
    print("Tick.since: Fidelity Traversal Experiment")
    print("=" * 60)
    print()

    # Create store and vertex
    store: EventStore[Fact] = EventStore()
    vertex = Vertex("incident-monitor", store=store)

    # Register incident Loop (not legacy _FoldEngine) for fidelity tracking
    initial_state = {
        "resolved": False,
        "alert_count": 0,
        "action_count": 0,
        "severities": [],
        "metrics": [],
        "actions": [],
    }
    incident_loop = Loop(
        name="incident",
        projection=Projection(dict(initial_state), fold=incident_fold),
        boundary_kind="incident.resolve",
        reset=True,
    )
    vertex.register_loop(incident_loop)

    print("Scenario: Monitoring an incident")
    print("-" * 40)

    # Generate and receive facts
    start_time = time.time()
    facts = generate_incident_facts(start_time, "monitor")

    print(f"\nGenerating {len(facts)} facts over simulated time window...")
    print()

    tick = None
    for fact in facts:
        print(f"  [{fact.kind}] {fact.payload.get('_kind', 'boundary')}: ", end="")
        if fact.payload.get("_kind") == "alert":
            print(f"severity={fact.payload.get('severity')}")
        elif fact.payload.get("_kind") == "metric":
            print(f"{fact.payload.get('name')}={fact.payload.get('value')}")
        elif fact.payload.get("_kind") == "action":
            print(f"action={fact.payload.get('action')}")
        else:
            print("(boundary)")

        result = vertex.receive(fact, SYSTEM)
        if result is not None:
            tick = result

    print()
    print("=" * 60)
    print("Boundary fired → Tick produced")
    print("=" * 60)
    print()

    if tick is None:
        print("ERROR: No tick produced!")
        return

    # Display tick
    print(f"Tick.name:   {tick.name}")
    print(f"Tick.ts:     {tick.ts.isoformat()}")
    print(f"Tick.since:  {tick.since.isoformat() if tick.since else 'None'}")
    print(f"Tick.origin: {tick.origin}")
    print()
    print("Tick.payload (summary):")
    for k, v in tick.payload.items():
        if isinstance(v, list) and len(v) > 3:
            print(f"  {k}: [{len(v)} items]")
        else:
            print(f"  {k}: {v}")

    print()
    print("=" * 60)
    print("Fidelity Traversal: Tick → Facts")
    print("=" * 60)
    print()

    # Reconstruct
    reconstructed = reconstruct_from_tick(tick, store)

    print(f"Store.between({tick.since.isoformat() if tick.since else 'None'}, {tick.ts.isoformat()})")
    print(f"Retrieved {len(reconstructed)} facts:")
    print()

    for fact in reconstructed:
        ts_str = datetime.fromtimestamp(fact.ts, tz=timezone.utc).strftime("%H:%M:%S")
        kind_detail = fact.payload.get("_kind", "boundary")
        if kind_detail == "alert":
            detail = f"severity={fact.payload.get('severity')}"
        elif kind_detail == "metric":
            detail = f"{fact.payload.get('name')}={fact.payload.get('value')}"
        elif kind_detail == "action":
            detail = f"action={fact.payload.get('action')}"
        else:
            detail = "(boundary)"
        print(f"  [{ts_str}] {fact.kind}.{kind_detail}: {detail}")

    print()
    print("=" * 60)
    print("Fidelity Verification: Re-fold → Same Payload?")
    print("=" * 60)
    print()

    # Re-fold and compare
    refolded = refold(reconstructed, incident_fold, initial_state)

    # Compare relevant fields (not the final boundary effect)
    original = tick.payload

    checks = [
        ("alert_count", original.get("alert_count") == refolded.get("alert_count")),
        ("action_count", original.get("action_count") == refolded.get("action_count")),
        ("severities", original.get("severities") == refolded.get("severities")),
    ]

    all_pass = True
    for name, passed in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {name}: original={original.get(name)}, refolded={refolded.get(name)}")
        if not passed:
            all_pass = False

    print()
    if all_pass:
        print("Fidelity verified: re-folding produces equivalent state")
    else:
        print("Fidelity FAILED: mismatch detected")

    print()
    print("=" * 60)
    print("What This Proves")
    print("=" * 60)
    print()
    print("1. Tick.since enables period reconstruction")
    print("   - The tick knows when its period started")
    print("   - Store.between(since, ts) retrieves exactly the contributing facts")
    print()
    print("2. Fidelity is opt-in")
    print("   - Most consumers just need tick.payload (the summary)")
    print("   - Full detail available when needed via traversal")
    print()
    print("3. The pattern generalizes")
    print("   - Works for any bounded accumulation: incidents, deploys, reviews")
    print("   - Same primitive (Tick) at every level")
    print()


if __name__ == "__main__":
    main()
