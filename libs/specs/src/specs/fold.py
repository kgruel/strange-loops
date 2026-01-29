"""Fold: transformation rules for how facts become state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class Fold:
    """A transformation rule: how facts become state.

    Fold operations define how incoming events update accumulated state.

    Attributes:
        op: The operation type (latest, collect, count, upsert, sum).
        target: The state facet name to update.
        props: Additional properties (key=, max=, etc.). Immutable after creation.

    Operations:
        - latest: state[target] = event timestamp or value
        - collect: append event to state[target] list (bounded by max=)
        - count: increment state[target] counter
        - upsert: update-or-insert into dict (key=), or add to set
        - sum: add event value to state[target]
    """

    op: str  # latest, collect, count, upsert, sum
    target: str  # state facet name
    props: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Wrap props in MappingProxyType for effective immutability."""
        object.__setattr__(self, "props", MappingProxyType(dict(self.props)))
