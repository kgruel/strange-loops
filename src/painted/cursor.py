"""Cursor: bounded index state for navigable widgets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class CursorMode(str, Enum):
    """Cursor boundary semantics."""

    CLAMP = "clamp"
    WRAP = "wrap"


@dataclass(frozen=True, slots=True)
class Cursor:
    """Bounded cursor position over a domain of `count` items.

    Normalization:
    - `count <= 0` normalizes to empty (`count=0`, `index=0`)
    - CLAMP: `index` clamped into [0, count-1] (or 0 when empty)
    - WRAP: `index` wrapped modulo `count` (or 0 when empty)
    """

    index: int = 0
    count: int = 0
    mode: CursorMode = CursorMode.CLAMP

    def __post_init__(self) -> None:
        count = max(0, int(self.count))
        index = int(self.index)

        if count == 0:
            index = 0
        elif self.mode == CursorMode.WRAP:
            index %= count
        else:
            index = max(0, min(index, count - 1))

        object.__setattr__(self, "count", count)
        object.__setattr__(self, "index", index)

    @property
    def is_empty(self) -> bool:
        return self.count == 0

    @property
    def max_index(self) -> int:
        return max(0, self.count - 1)

    def with_count(self, count: int) -> Cursor:
        return replace(self, count=count)

    def move(self, delta: int) -> Cursor:
        return replace(self, index=self.index + delta)

    def move_to(self, index: int) -> Cursor:
        return replace(self, index=index)

    def next(self) -> Cursor:
        return self.move(1)

    def prev(self) -> Cursor:
        return self.move(-1)

    def home(self) -> Cursor:
        return self.move_to(0)

    def end(self) -> Cursor:
        return self.move_to(self.max_index)

