"""Mouse: optional input extension for TUI.

SGR mouse protocol support for interactive applications.
"""

from .._mouse import MouseAction, MouseButton, MouseEvent

__all__ = [
    "MouseEvent",
    "MouseButton",
    "MouseAction",
]
