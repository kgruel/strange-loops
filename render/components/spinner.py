"""Spinner component: animated frame-based indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..cell import Style
from ..block import StyledBlock


@dataclass(frozen=True)
class SpinnerFrames:
    """A set of animation frames for a spinner."""

    frames: tuple[str, ...]


DOTS = SpinnerFrames(frames=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"))
LINE = SpinnerFrames(frames=("-", "\\", "|", "/"))
BRAILLE = SpinnerFrames(frames=("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"))


@dataclass(frozen=True)
class SpinnerState:
    """Immutable spinner state tracking current frame."""

    frame: int = 0
    frames: SpinnerFrames = DOTS

    def tick(self) -> SpinnerState:
        """Advance to the next frame, wrapping around."""
        return replace(self, frame=(self.frame + 1) % len(self.frames.frames))


def spinner(state: SpinnerState, *, style: Style = Style()) -> StyledBlock:
    """Render current spinner frame as a 1x1 block."""
    char = state.frames.frames[state.frame % len(state.frames.frames)]
    return StyledBlock.text(char, style)
