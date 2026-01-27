"""Shape: data contracts composed of facets and fold rules."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from .boundary import Boundary
from .engine import build_fold_fns
from .facet import Facet
from .fold import Fold
from .types import initial_value


@dataclass(frozen=True)
class Shape:
    """Data contract: input facets + state facets + fold rules.

    A Shape defines the contract for transforming events into state:
    - input_facets: what the incoming events must contain
    - state_facets: what the accumulated state looks like
    - folds: how events update state

    Attributes:
        name: Unique identifier for this shape.
        about: Human-readable description.
        input_facets: Facets expected in incoming events.
        state_facets: Facets in the accumulated state.
        folds: Transformation rules from events to state.
    """

    name: str
    about: str = ""
    input_facets: tuple[Facet, ...] = ()
    state_facets: tuple[Facet, ...] = ()
    folds: tuple[Fold, ...] = ()
    boundary: Boundary | None = None

    def initial_state(self) -> dict[str, Any]:
        """Create the initial state dict from state_facets.

        Each facet gets its type's default initial value:
        - dict -> {}
        - list -> []
        - set -> set()
        - int/float -> 0
        - bool -> False
        - str -> ""
        - other -> None
        """
        state: dict[str, Any] = {}
        for f in self.state_facets:
            state[f.name] = initial_value(f.kind)
        return state

    def input_facet(self, name: str) -> Facet | None:
        """Look up an input facet by name. Returns None if not found."""
        for f in self.input_facets:
            if f.name == name:
                return f
        return None

    def state_facet(self, name: str) -> Facet | None:
        """Look up a state facet by name. Returns None if not found."""
        for f in self.state_facets:
            if f.name == name:
                return f
        return None

    def apply(self, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """Apply fold rules to state given a payload, return new state.

        Deep-copies state so fold fns (which mutate in place) never affect
        the input dict or its nested containers. Pure.
        """
        new = copy.deepcopy(state)
        for fn in build_fold_fns(self.folds):
            fn(new, payload)
        return new
