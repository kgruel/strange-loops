"""Fold overrides for hlab — domain computation at fold time.

Each fold override receives (state, payload) where payload is the Fact's
payload dict from the DSL source. Most commands now use DSL-native folds
(collect, latest, etc.) declared in .loop/.vertex files. Only health_fold
remains as a Python override because it computes derived metrics (healthy/total)
that aren't expressible as a single fold op.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Status: health computation
# ---------------------------------------------------------------------------

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
