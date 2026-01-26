"""ticks — Personal-scale event infrastructure.

Kafka concepts (append-only logs, offset-tracking consumers, materialized views)
at individual/homelab scale, using files instead of brokers.

Core primitives:
  Stream      Typed async fan-out
  EventStore  Append-only log with optional JSONL persistence
  Projection  Incremental fold (materialized view)
  FileWriter  JSONL append (persistence tap)
  Tailer      JSONL reader with byte-offset tracking
  Forward     Stream-to-stream bridge with transform
"""

from .stream import Stream, Tap, Consumer
from .store import EventStore
from .projection import Projection
from .file_writer import FileWriter
from .tailer import Tailer
from .forward import Forward
from .source import Source, ClosableSource

__all__ = [
    "Stream",
    "Tap",
    "Consumer",
    "EventStore",
    "Projection",
    "FileWriter",
    "Tailer",
    "Forward",
    "Source",
    "ClosableSource",
]
