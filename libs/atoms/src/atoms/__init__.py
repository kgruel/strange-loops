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

Uses lazy imports via __getattr__ so that ``from atoms import Fact``
only loads atoms.fact, not the entire package tree.
"""

from atoms.fact import Fact

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
    "TickWindow",
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
    "SourceError",
    "CommandSource",
    "SequentialSource",
    "SourceProtocol",
]

# Lazy import map: attribute name → (module, name)
_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Contract
    "Spec": ("atoms.spec", "Spec"),
    "Shape": ("atoms.spec", "Shape"),
    "Facet": ("atoms.facet", "Facet"),
    "Field": ("atoms.facet", "Field"),
    "Boundary": ("atoms.boundary", "Boundary"),
    "ValidationError": ("atoms.types", "ValidationError"),
    # Fold vocabulary
    "Avg": ("atoms.fold", "Avg"),
    "Collect": ("atoms.fold", "Collect"),
    "Count": ("atoms.fold", "Count"),
    "FoldOp": ("atoms.fold", "FoldOp"),
    "Latest": ("atoms.fold", "Latest"),
    "Max": ("atoms.fold", "Max"),
    "Min": ("atoms.fold", "Min"),
    "Sum": ("atoms.fold", "Sum"),
    "TopN": ("atoms.fold", "TopN"),
    "Upsert": ("atoms.fold", "Upsert"),
    "Window": ("atoms.fold", "Window"),
    # Fold output contract
    "FoldItem": ("atoms.fold_state", "FoldItem"),
    "FoldSection": ("atoms.fold_state", "FoldSection"),
    "FoldState": ("atoms.fold_state", "FoldState"),
    "TickWindow": ("atoms.ticks", "TickWindow"),
    # Parse vocabulary
    "Coerce": ("atoms.parse", "Coerce"),
    "Explode": ("atoms.parse", "Explode"),
    "Flatten": ("atoms.parse", "Flatten"),
    "Pick": ("atoms.parse", "Pick"),
    "Project": ("atoms.parse", "Project"),
    "Rename": ("atoms.parse", "Rename"),
    "Select": ("atoms.parse", "Select"),
    "Skip": ("atoms.parse", "Skip"),
    "Split": ("atoms.parse", "Split"),
    "Transform": ("atoms.parse", "Transform"),
    "Where": ("atoms.parse", "Where"),
    "has_explode": ("atoms.parse", "has_explode"),
    "resolve_path": ("atoms.parse", "resolve_path"),
    "run_parse": ("atoms.parse", "run_parse"),
    "run_parse_many": ("atoms.parse", "run_parse_many"),
    # Ingress
    "Source": ("atoms.source", "Source"),
    "SourceError": ("atoms.source", "SourceError"),
    "CommandSource": ("atoms.source", "CommandSource"),
    "SequentialSource": ("atoms.sequential", "SequentialSource"),
    "SourceProtocol": ("atoms.protocol", "SourceProtocol"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        # Cache on the module for subsequent access
        globals()[name] = value
        return value
    raise AttributeError(f"module 'atoms' has no attribute {name!r}")
