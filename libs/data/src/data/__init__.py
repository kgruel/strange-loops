"""data — Observation atoms, contracts, and ingress.

Consolidates:
- facts: Fact (the observation atom)
- specs: Spec, Field, Fold ops, Parse ops (contracts)
- sources: Source, Runner (ingress adapters)

Example:
    from data import Fact, Spec, Source

    f = Fact.of("heartbeat", "alice", service="api", latency=42)
    spec = Spec(name="health", about="Service health", ...)
    source = Source(command="uptime", kind="system", observer="monitor")
"""

# Atoms
from data.fact import Fact

# Contract
from data.spec import Shape, Spec
from data.facet import Facet, Field
from data.boundary import Boundary
from data.types import ValidationError

# Fold vocabulary
from data.fold import Avg, Collect, Count, FoldOp, Latest, Max, Min, Sum, TopN, Upsert, Window

# Parse vocabulary
from data.parse import (
    Coerce,
    Explode,
    Pick,
    Project,
    Rename,
    Select,
    Skip,
    Split,
    Transform,
    Where,
    has_explode,
    resolve_path,
    run_parse,
    run_parse_many,
)

# Ingress
from data.source import CommandSource, Source
from data.runner import Runner
from data.protocol import SourceProtocol

__all__ = [
    # Atoms
    "Fact",
    # Contract
    "Spec",
    "Shape",
    "Field",
    "Facet",
    "Boundary",
    "ValidationError",
    # Fold vocabulary
    "Avg",
    "Collect",
    "Count",
    "FoldOp",
    "Latest",
    "Max",
    "Min",
    "Sum",
    "TopN",
    "Upsert",
    "Window",
    # Parse vocabulary
    "Coerce",
    "Explode",
    "Pick",
    "Project",
    "Rename",
    "Select",
    "Skip",
    "Split",
    "Transform",
    "Where",
    "has_explode",
    "resolve_path",
    "run_parse",
    "run_parse_many",
    # Ingress
    "Source",
    "CommandSource",
    "SourceProtocol",
    "Runner",
]
