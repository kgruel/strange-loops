"""atoms — Observation atoms, contracts, and ingress.

Consolidates:
- facts: Fact (the observation atom)
- specs: Spec, Field, Fold ops, Parse ops (contracts)
- sources: Source (ingress adapters)

Example:
    from atoms import Fact, Spec, Source

    f = Fact.of("heartbeat", "alice", service="api", latency=42)
    spec = Spec(name="health", about="Service health", ...)
    source = Source(command="uptime", kind="system", observer="monitor")
"""

# Atoms
from atoms.fact import Fact

# Contract
from atoms.spec import Shape, Spec
from atoms.facet import Facet, Field
from atoms.boundary import Boundary
from atoms.types import ValidationError

# Fold vocabulary
from atoms.fold import Avg, Collect, Count, FoldOp, Latest, Max, Min, Sum, TopN, Upsert, Window

# Fold output contract
from atoms.fold_state import FoldItem, FoldSection, FoldState

# Parse vocabulary
from atoms.parse import (
    Coerce,
    Explode,
    Flatten,
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
from atoms.source import CommandSource, Source
from atoms.sequential import SequentialSource
from atoms.protocol import SourceProtocol

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
    # Fold output contract
    "FoldItem",
    "FoldSection",
    "FoldState",
    # Parse vocabulary
    "Coerce",
    "Explode",
    "Flatten",
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
    "SequentialSource",
    "SourceProtocol",
]
