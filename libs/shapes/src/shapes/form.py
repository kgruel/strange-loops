"""Form: shape contracts composed of fields and fold rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .field import Field
from .fold import Fold
from .types import initial_value


@dataclass(frozen=True)
class Form:
    """Shape contract: input fields + state fields + fold rules.

    A Form defines the contract for transforming events into state:
    - input_fields: what the incoming events must contain
    - state_fields: what the accumulated state looks like
    - folds: how events update state

    Attributes:
        name: Unique identifier for this form.
        about: Human-readable description.
        input_fields: Fields expected in incoming events.
        state_fields: Fields in the accumulated state.
        folds: Transformation rules from events to state.
    """

    name: str
    about: str = ""
    input_fields: tuple[Field, ...] = ()
    state_fields: tuple[Field, ...] = ()
    folds: tuple[Fold, ...] = ()

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
