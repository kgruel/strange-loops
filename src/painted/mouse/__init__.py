"""Mouse: optional input extension for TUI.

SGR mouse protocol support for interactive applications.
"""

from .._mouse import MouseEvent, MouseButton, MouseAction

__all__ = [
    "MouseEvent",
    "MouseButton",
    "MouseAction",
]
