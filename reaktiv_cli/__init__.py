"""
reaktiv_cli - Reactive CLI framework built on reaktiv and ev.

Core components:
- ReactiveEmitter: Bridges reaktiv signals to Rich Live rendering + ev events
- Line, Segment: Minimal IR for styled text rendering

Re-exports from reaktiv for convenience:
- Signal, Computed, Effect, batch

Example:
    from reaktiv_cli import ReactiveEmitter, Line, Segment, Signal, Computed
    from ev import ListEmitter

    count = Signal(0)

    def ui():
        return Line((Segment(f"Count: {count()}"),)).to_rich()

    emitter = ListEmitter()
    with ReactiveEmitter(emitter, ui_fn=ui):
        count.set(1)
        count.set(2)
"""

from reaktiv_cli.emitter import ReactiveEmitter
from reaktiv_cli.ir import Line, Segment, lines_to_rich
from reaktiv_cli.bridges import create_notable_watcher, create_each_watcher

# Re-export reaktiv primitives for convenience
from reaktiv import Signal, Computed, Effect, batch

__all__ = [
    # Core
    "ReactiveEmitter",
    # IR
    "Line",
    "Segment",
    "lines_to_rich",
    # Bridges
    "create_notable_watcher",
    "create_each_watcher",
    # Re-exports from reaktiv
    "Signal",
    "Computed",
    "Effect",
    "batch",
]
