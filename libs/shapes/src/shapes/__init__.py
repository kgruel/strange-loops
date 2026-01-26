"""shapes — Data contracts for the reactive data ecosystem.

shapes = data contracts (how), defining:
- Facet: atomic face (name + kind)
- Fold: transformation rule (upsert, latest, collect, count, sum)
- Shape: composed contract (facets + folds)

Part of the ecosystem:
- facts = semantic atoms (what)
- ticks = temporal atoms (when)
- shapes = data contracts (how)
- cells = spatial atoms (where)
"""

from .facet import Facet
from .fold import Fold
from .shape import Shape
from .types import ValidationError

__all__ = ["Facet", "Fold", "Shape", "ValidationError"]
