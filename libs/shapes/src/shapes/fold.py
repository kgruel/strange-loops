"""Fold: transformation rules for how facts become state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Fold:
    """A transformation rule: how facts become state.

    Fold operations define how incoming events update accumulated state.

    Attributes:
        op: The operation type (latest, collect, count, upsert, sum).
        target: The state field name to update.
        props: Additional properties (key=, max=, etc.).

    Operations:
        - latest: state[target] = event timestamp or value
        - collect: append event to state[target] list (bounded by max=)
        - count: increment state[target] counter
        - upsert: update-or-insert into dict (key=), or add to set
        - sum: add event value to state[target]
    """

    op: str  # latest, collect, count, upsert, sum
    target: str  # state field name
    props: dict[str, Any] = field(default_factory=dict)
