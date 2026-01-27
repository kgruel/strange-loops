"""Boundary: declares when a fold cycle completes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Boundary:
    """Declares which fact kind completes a fold cycle.

    A Shape with a boundary produces Ticks at cycle boundaries.
    A Shape without a boundary folds continuously — no cycle, no Tick.

    Attributes:
        kind: The fact kind that triggers the boundary.
        reset: Whether state resets to initial after the boundary.
            True = state resets (each cycle starts fresh).
            False = state carries (next cycle continues from current state).
    """

    kind: str
    reset: bool = True
