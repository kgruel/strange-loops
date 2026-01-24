"""Stream topology primitives.

The framework layer provides typed event routing:
  Stream → Consumer fan-out
  Projection → incremental fold (materialized view)
  EventStore → append-only log with version counter
  FileWriter → JSONL persistence (producer)
  Tailer → JSONL reader with offset tracking (consumer)
  Forward → typed stream-to-stream bridge
  SpecProjection → declarative projection from KDL specs
"""

from .store import EventStore
from .stream import Stream, Tap, Consumer
from .projection import Projection
from .file_writer import FileWriter
from .tailer import Tailer
from .forward import Forward
from .sim import BaseSimulator, SimState
from .instrument import metrics
from .spec import ProjectionSpec, SpecProjection, parse_projection_spec
from .app_spec import AppSpec, VMInfo, parse_app_spec

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
    "ProjectionSpec",
    "SpecProjection",
    "parse_projection_spec",
    "AppSpec",
    "VMInfo",
    "parse_app_spec",
]
