"""Boundary: declares when a fold cycle completes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Boundary:
    """Declares when a fold cycle completes.

    A Shape with a boundary produces Ticks at cycle boundaries.
    A Shape without a boundary folds continuously — no cycle, no Tick.

    Two trigger modes:
    - Kind-based (mode="when"): fire when fact of `kind` arrives
    - Count-based (mode="after" or "every"): fire after `count` facts

    Attributes:
        kind: The fact kind that triggers the boundary (for mode="when").
        count: Number of facts before boundary fires (for mode="after"/"every").
        mode: Trigger mode - "when", "after", or "every".
        reset: Whether state resets to initial after the boundary.
            True = state resets (each cycle starts fresh).
            False = state carries (next cycle continues from current state).
    """

    kind: str | None = None
    count: int | None = None
    mode: Literal["when", "after", "every"] = "when"
    reset: bool = True

    def __post_init__(self) -> None:
        if self.kind is None and self.count is None:
            raise ValueError("Boundary must have kind or count")
        if self.kind is not None and self.count is not None:
            raise ValueError("Boundary cannot have both kind and count")
        if self.mode == "when" and self.kind is None:
            raise ValueError("mode='when' requires kind")
        if self.mode in ("after", "every") and self.count is None:
            raise ValueError(f"mode='{self.mode}' requires count")
