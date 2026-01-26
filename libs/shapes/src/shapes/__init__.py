"""forms - Shape contracts for the reactive data ecosystem.

forms = shape contracts (how), defining:
- Field: atomic unit (name + type)
- Form: composed contract (fields + folds)
- Fold: transformation rule (upsert, latest, collect, count, sum)

Part of the ecosystem:
- facts = semantic atoms (what)
- ticks = temporal atoms (when)
- forms = shape contracts (how)
- cells = spatial atoms (where)
"""

from .field import Field
from .fold import Fold
from .form import Form
from .types import ValidationError

__all__ = ["Field", "Fold", "Form", "ValidationError"]
