"""Tests for SpinnerState tick wrapping."""

from fidelis.widgets import SpinnerFrames, SpinnerState


def test_spinner_tick_wraps() -> None:
    frames = SpinnerFrames(frames=("a", "b", "c"))
    state = SpinnerState(frame=2, frames=frames)
    assert state.tick().frame == 0


def test_spinner_tick_empty_frames_is_safe() -> None:
    frames = SpinnerFrames(frames=())
    state = SpinnerState(frame=0, frames=frames)
    assert state.tick().frame == 0

