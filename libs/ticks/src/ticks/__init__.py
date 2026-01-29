"""ticks — Personal-scale event infrastructure.

The respiratory system: Tick atom + Vertex + Store + fold engine.

Core primitives:
  Tick        Frozen temporal snapshot: name + ts + payload (the atom)
  Vertex      Where loops meet: kind-based routing + fold engines + boundary ticks
  Store       Protocol for append-only logs (append, since, close)
  EventStore  In-memory Store implementation
  FileStore   JSONL-backed Store implementation
  Stream      Typed async fan-out
  Projection  Incremental fold (materialized view, internal to Vertex)
  FileWriter  JSONL append (persistence tap)
  Tailer      JSONL reader with byte-offset tracking
  Forward     Stream-to-stream bridge with transform
"""

from .tick import Tick
from .stream import Stream, Tap, Consumer
from .store import Store, EventStore
from .projection import Projection
from .file_store import FileStore
from .file_writer import FileWriter
from .tailer import Tailer
from .forward import Forward
from .lens import Lens
from .loop import Loop
from .vertex import Vertex
from .source import Source, ClosableSource

__all__ = [
    "Tick",
    "Stream",
    "Tap",
    "Consumer",
    "Store",
    "EventStore",
    "FileStore",
    "Projection",
    "FileWriter",
    "Tailer",
    "Forward",
    "Lens",
    "Loop",
    "Vertex",
    "Source",
    "ClosableSource",
]
