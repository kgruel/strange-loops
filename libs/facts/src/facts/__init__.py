"""facts - Renderer-agnostic semantic contract for CLI output.

The missing ViewModel layer between domain logic and presentation.
Domain emits Event/Result, renderers interpret.

Example:
    from facts import Event, Result, Emitter, ListEmitter

    def my_command(emitter: Emitter) -> Result:
        emitter.emit(Event(kind="progress", message="Starting..."))
        # do work
        emitter.emit(Event(kind="progress", data={"complete": True}))
        return Result(status="ok", summary="Done")

    # For testing:
    emitter = ListEmitter()
    result = my_command(emitter)
    emitter.finish(result)
    assert len(emitter.events) == 2
"""

from facts.emitter import Emitter, ListEmitter, NullEmitter
from facts.types import Event, Result

__all__ = [
    "Event",
    "Result",
    "Emitter",
    "ListEmitter",
    "NullEmitter",
]
