"""specs — Data contracts for the reactive data ecosystem.

specs = data contracts (how), defining:
- Facet: atomic face (name + kind)
- Fold: transformation rule (upsert, latest, collect, count, sum)
- Spec: composed contract (facets + folds)

Part of the ecosystem:
- facts = semantic atoms (what)
- ticks = temporal atoms (when)
- specs = data contracts (how)
- cells = spatial atoms (where)
"""

from .boundary import Boundary
from .facet import Facet
from .fold import Fold
from .spec import Shape, Spec
from .types import ValidationError

__all__ = ["Boundary", "Facet", "Fold", "Shape", "Spec", "ValidationError"]
