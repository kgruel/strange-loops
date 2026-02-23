"""Spinner component: animated frame-based indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..cell import Style
from ..block import Block
from ..cursor import Cursor, CursorMode

if TYPE_CHECKING:
    from ..component_theme import ComponentTheme


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
        cursor = Cursor(index=self.frame, count=len(self.frames.frames), mode=CursorMode.WRAP).next()
        return replace(self, frame=cursor.index)


def spinner(
    state: SpinnerState,
    *,
    style: Style | None = None,
    theme: "ComponentTheme | None" = None,
) -> Block:
    """Render current spinner frame as a 1x1 block.

    Args:
        state: Current spinner state with frame index.
        style: Optional style override.
        theme: Optional ComponentTheme. If provided and state uses default frames,
            uses theme.icons.spinner instead.

    Returns:
        1-character Block with the spinner frame.
    """
    # Determine frames to use
    if theme is not None and state.frames is DOTS:
        # Use theme's spinner icons when using default frames
        frames = theme.icons.spinner
    else:
        frames = state.frames.frames

    # Determine style
    if style is None:
        if theme is not None:
            style = theme.accent
        else:
            style = Style()

    char = frames[state.frame % len(frames)]
    return Block.text(char, style)
