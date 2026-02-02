"""Fold overrides for hlab — health computation at fold time."""

from __future__ import annotations

# Initial state for health_fold
HEALTH_INITIAL: dict = {"containers": [], "healthy": 0, "total": 0}


def health_fold(state: dict, payload: dict) -> dict:
    """Accumulate containers, compute healthy/total.

    Args:
        state: Current state with containers, healthy, total
        payload: Incoming container dict (Name, State, Health, RunningFor, etc.)

    Returns:
        Updated state with recomputed health metrics
    """
    containers = state.get("containers", []) + [payload]
    containers = containers[-50:]  # cap to match DSL spec

    healthy = sum(
        1 for c in containers
        if c.get("State") == "running"
        and c.get("Health") in ("healthy", "")
    )

    return {
        "containers": containers,
        "healthy": healthy,
        "total": len(containers),
    }
