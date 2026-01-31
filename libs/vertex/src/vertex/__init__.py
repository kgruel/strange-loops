"""vertex — Temporal infrastructure and identity.

Consolidates:
- ticks: Tick, Vertex, Store, Stream, Projection (temporal primitives)
- peers: Peer, Grant (identity and policy)

The respiratory system: Tick atom + Vertex + Store + fold engine.

Example:
    from vertex import Tick, Vertex, Peer, Grant

    v = Vertex("main")
    v.register("count", 0, lambda s, p: s + 1)
    peer = Peer("alice", potential=frozenset({"count"}))
"""

# Atoms
from vertex.tick import Tick

# Core
from vertex.vertex import Vertex
from vertex.loop import Loop
from vertex.stream import Consumer, Stream, Tap
from vertex.projection import Projection

# Persistence
from vertex.store import EventStore, Store
from vertex.file_store import FileStore
from vertex.file_writer import FileWriter
from vertex.tailer import Tailer
from vertex.replay import replay

# Utilities
from vertex.forward import Forward
from vertex.lens import Lens
from vertex.source_protocol import ClosableSource
from vertex.source_protocol import Source as VertexSource

# Identity & Policy
from vertex.peer import (
    Grant,
    Peer,
    delegate,
    expand_grant,
    grant,
    grant_of,
    restrict,
    restrict_grant,
)

__all__ = [
    # Atoms
    "Tick",
    # Core
    "Vertex",
    "Loop",
    "Stream",
    "Tap",
    "Consumer",
    "Projection",
    # Persistence
    "Store",
    "EventStore",
    "FileStore",
    "FileWriter",
    "Tailer",
    "replay",
    # Utilities
    "Forward",
    "Lens",
    "VertexSource",
    "ClosableSource",
    # Identity & Policy
    "Peer",
    "Grant",
    "grant",
    "restrict",
    "delegate",
    "grant_of",
    "expand_grant",
    "restrict_grant",
]
