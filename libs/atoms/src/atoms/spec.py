"""Spec: data contracts composed of fields and fold rules."""

from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .boundary import Boundary
from .engine import build_fold_fns
from .facet import Facet, Field
from .fold import FoldOp
from .types import initial_value


@dataclass(frozen=True)
class Spec:
    """Data contract: input fields + state fields + fold rules.

    A Spec defines the contract for transforming events into state:
    - input_fields: what the incoming events must contain
    - state_fields: what the accumulated state looks like
    - folds: how events update state

    Attributes:
        name: Unique identifier for this spec.
        about: Human-readable description.
        input_fields: Fields expected in incoming events.
        state_fields: Fields in the accumulated state.
        folds: Transformation rules from events to state.
    """

    name: str
    about: str = ""
    input_fields: tuple[Field, ...] = ()
    state_fields: tuple[Field, ...] = ()
    folds: tuple[FoldOp, ...] = ()
    boundary: Boundary | None = None

    # Backward compatibility aliases (deprecated)
    @property
    def input_facets(self) -> tuple[Field, ...]:
        """Deprecated: use input_fields instead."""
        return self.input_fields

    @property
    def state_facets(self) -> tuple[Field, ...]:
        """Deprecated: use state_fields instead."""
        return self.state_fields

    def initial_state(self) -> dict[str, Any]:
        """Create the initial state dict from state_fields.

        Each field gets its type's default initial value:
        - dict -> {}
        - list -> []
        - set -> set()
        - int/float -> 0
        - bool -> False
        - str -> ""
        - other -> None
        """
        state: dict[str, Any] = {}
        for f in self.state_fields:
            state[f.name] = initial_value(f.kind)
        return state

    def input_field(self, name: str) -> Field | None:
        """Look up an input field by name. Returns None if not found."""
        for f in self.input_fields:
            if f.name == name:
                return f
        return None

    def state_field(self, name: str) -> Field | None:
        """Look up a state field by name. Returns None if not found."""
        for f in self.state_fields:
            if f.name == name:
                return f
        return None

    # Backward compatibility aliases (deprecated)
    def input_facet(self, name: str) -> Field | None:
        """Deprecated: use input_field instead."""
        return self.input_field(name)

    def state_facet(self, name: str) -> Field | None:
        """Deprecated: use state_field instead."""
        return self.state_field(name)

    def apply(self, state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """Apply fold rules to state given a payload, return new state.

        Deep-copies state so fold fns (which mutate in place) never affect
        the input dict or its nested containers. Pure.
        """
        new = copy.deepcopy(state)
        for fn in build_fold_fns(self.folds):
            fn(new, payload)
        return new

    def replay(self, payloads: Iterable[dict[str, Any]]) -> dict[str, Any]:
        """Bulk replay: build folds once, mutate in place, return final state.

        Unlike apply() which deep-copies for purity, replay() mutates a single
        state dict across all payloads. Use when replaying stored facts where
        intermediate states are not needed.
        """
        fns = build_fold_fns(self.folds)
        state = self.initial_state()
        for payload in payloads:
            for fn in fns:
                fn(state, payload)
        return state


# Backward compatibility alias (deprecated)
Shape = Spec
