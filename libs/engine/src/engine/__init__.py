"""engine — Temporal infrastructure and identity.

Consolidates:
- ticks: Tick, Vertex, Store, Stream, Projection (temporal primitives)
- peers: Peer, Grant (identity and policy)

The respiratory system: Tick atom + Vertex + Store + fold engine.

Example:
    from engine import Tick, Vertex, Peer, Grant

    v = Vertex("main")
    v.register("count", 0, lambda s, p: s + 1)
    peer = Peer("alice", potential=frozenset({"count"}))
"""

# Atoms
from .tick import Tick

# Core
from .loop import Loop
from .projection import Projection
from .stream import Consumer, Stream, Tap
from .vertex import Vertex

# Persistence
from .file_store import FileStore
from .file_writer import FileWriter
from .replay import replay
from .sqlite_store import SqliteStore
from .store import EventStore, Store
from .store_reader import StoreReader
from .tailer import Tailer

# Utilities
from .forward import Forward
from .lens import Lens
from .source_protocol import ClosableSource
from .source_protocol import Source as VertexSource

# Identity & Policy
from .peer import (
    Grant,
    Peer,
    delegate,
    expand_grant,
    grant,
    grant_of,
    restrict,
    restrict_grant,
)

# Compiler (DSL → runtime)
from .compiler import (
    CircularVertexError,
    CompiledVertex,
    FoldOverride,
    collect_all_sources,
    compile_loop,
    compile_sources,
    compile_vertex,
    compile_vertex_recursive,
    instantiate_template,
    materialize_vertex,
    substitute_vars,
)
from .program import VertexProgram, load_vertex_program

# Vertex read path (query-time fold materialization)
from .vertex_reader import vertex_facts, vertex_read, vertex_summary, vertex_ticks

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
    "SqliteStore",
    # StoreReader: internal to vertex_read. Use vertex_read/vertex_facts instead.
    # Still importable via `from engine import StoreReader` for backward compat.
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
    # Compiler (DSL → runtime)
    "CircularVertexError",
    "CompiledVertex",
    "FoldOverride",
    "collect_all_sources",
    "compile_loop",
    "compile_sources",
    "compile_vertex",
    "compile_vertex_recursive",
    "instantiate_template",
    "materialize_vertex",
    "substitute_vars",
    # Program helpers
    "VertexProgram",
    "load_vertex_program",
    # Vertex read path
    "vertex_read",
    "vertex_facts",
    "vertex_ticks",
    "vertex_summary",
]
