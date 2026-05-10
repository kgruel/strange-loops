"""Readout registry: name → (ParamsDataclass, callable).

Each readout signature:
    fn(rows, comps, ctx, params, *, E, D, sigma) -> Any

The registry validates `params` against the typed dataclass before invocation.
"""
from .components import ComponentsParams, components_readout
from .bridges import BridgesParams, bridges_readout
from .lineage import LineageParams, lineage_readout
from .antipodes import AntipodesParams, antipodes_readout
from .triage import TriageParams, triage_readout

REGISTRY = {
    "components": (ComponentsParams, components_readout),
    "bridges": (BridgesParams, bridges_readout),
    "lineage": (LineageParams, lineage_readout),
    "antipodes": (AntipodesParams, antipodes_readout),
    "triage": (TriageParams, triage_readout),
}

__all__ = [
    "REGISTRY",
    "ComponentsParams",
    "BridgesParams",
    "LineageParams",
    "AntipodesParams",
    "TriageParams",
]
