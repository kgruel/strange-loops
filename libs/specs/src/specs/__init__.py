"""specs — Data contracts for the reactive data ecosystem.

specs = data contracts (how), defining:
- Facet: atomic face (name + kind)
- Fold vocabulary: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max
- Spec: composed contract (facets + folds)
- Parse vocabulary: Split, Pick, Rename, Transform, Coerce, Skip

Part of the ecosystem:
- facts = semantic atoms (what)
- ticks = temporal atoms (when)
- specs = data contracts (how)
- cells = spatial atoms (where)
"""

from .boundary import Boundary
from .facet import Facet
from .fold import Collect, Count, Fold, FoldOp, Latest, Max, Min, Sum, TopN, Upsert
from .parse import Coerce, Pick, Rename, Skip, Split, Transform, run_parse
from .spec import Shape, Spec
from .types import ValidationError

__all__ = [
    # Core
    "Boundary",
    "Facet",
    "Shape",
    "Spec",
    "ValidationError",
    # Fold vocabulary (typed)
    "Collect",
    "Count",
    "Latest",
    "Max",
    "Min",
    "Sum",
    "TopN",
    "Upsert",
    # Fold vocabulary (legacy)
    "Fold",
    "FoldOp",
    # Parse vocabulary
    "Coerce",
    "Pick",
    "Rename",
    "Skip",
    "Split",
    "Transform",
    "run_parse",
]
