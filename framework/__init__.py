"""Stream topology primitives.

The framework layer provides typed event routing:
  Stream → Consumer fan-out
  Projection → incremental fold (materialized view)
  EventStore → append-only log with version counter
  FileWriter → JSONL persistence (producer)
  Tailer → JSONL reader with offset tracking (consumer)
  Forward → typed stream-to-stream bridge
"""

from .store import EventStore
from .stream import Stream, Tap, Consumer
from .projection import Projection
from .file_writer import FileWriter
from .tailer import Tailer
from .forward import Forward
from .sim import BaseSimulator, SimState
from .instrument import metrics

__all__ = [
    "Stream",
    "Tap",
    "Consumer",
    "EventStore",
    "Projection",
    "FileWriter",
    "Tailer",
    "Forward",
    "BaseSimulator",
    "SimState",
    "metrics",
]
