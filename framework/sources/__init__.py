"""Source implementations for event production.

Sources implement the Source[T] protocol from rill, producing events
as async iterators. Framework owns the IO implementations.

Available sources:
  TailerSource  - reads from JSONL files (replay mode)
  PollSource    - runs poll collector over SSH at interval
  StreamSource  - runs streaming collector over SSH
"""

from .tailer import TailerSource
from .poll import PollSource
from .stream import StreamSource

__all__ = [
    "TailerSource",
    "PollSource",
    "StreamSource",
]
