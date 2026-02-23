"""Layout regions — named rectangular areas of the buffer."""

from __future__ import annotations

from dataclasses import dataclass

from .buffer import Buffer, BufferView


@dataclass(frozen=True, slots=True)
class Region:
    """A named rectangular area of the buffer."""

    x: int
    y: int
    width: int
    height: int

    def view(self, buffer: Buffer) -> BufferView:
        """Get a BufferView for this region."""
        return buffer.region(self.x, self.y, self.width, self.height)
