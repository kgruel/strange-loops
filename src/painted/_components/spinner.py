"""Spinner component: animated frame-based indicator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..cell import Style
from ..block import Block
from ..cursor import Cursor, CursorMode

if TYPE_CHECKING:
    from ..icon_set import IconSet


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
    icons: "IconSet | None" = None,
) -> Block:
    """Render current spinner frame as a 1x1 block.

    Args:
        state: Current spinner state with frame index.
        style: Optional style override.
        icons: Optional IconSet override (uses ambient if None). If state uses the
            default DOTS frames and icons is non-default, uses icons.spinner.

    Returns:
        1-character Block with the spinner frame.
    """
    from ..icon_set import IconSet, current_icons

    ic = icons or current_icons()

    # Determine frames to use
    if state.frames is DOTS and ic != IconSet():
        frames = ic.spinner
    else:
        frames = state.frames.frames

    # Determine style (caller chooses role)
    style = style or Style()

    char = frames[state.frame % len(frames)]
    return Block.text(char, style)
