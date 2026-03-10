"""engine — Temporal infrastructure and identity.

Consolidates:
- ticks: Tick, Vertex, Loop, Store, Stream (temporal primitives)
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

# Cadence
from .cadence import Cadence

# Compiler (DSL → runtime)
from .compiler import (
    CircularVertexError,
    CompiledVertex,
    FoldOverride,
    collect_all_sources,
    collect_search_fields,
    compile_loop,
    compile_source,
    compile_sources,
    compile_sources_block,
    compile_vertex,
    compile_vertex_recursive,
    instantiate_template,
    materialize_vertex,
    substitute_vars,
)
from .executor import CyclicDependencyError, Executor, SkippedSource, SyncResult, validate_dependency_graph
from .program import VertexProgram, load_vertex_program

# Vertex read path (query-time fold materialization)
from .vertex_reader import emit_topology, vertex_fact_by_id, vertex_facts, vertex_fold, vertex_read, vertex_search, vertex_summary, vertex_ticks

__all__ = [
    # Atoms
    "Tick",
    # Core
    "Vertex",
    "Loop",
    "Stream",
    "Tap",
    "Consumer",
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
    # Cadence
    "Cadence",
    # Compiler (DSL → runtime)
    "CircularVertexError",
    "CompiledVertex",
    "FoldOverride",
    "collect_all_sources",
    "collect_search_fields",
    "compile_loop",
    "compile_source",
    "compile_sources",
    "compile_sources_block",
    "compile_vertex",
    "compile_vertex_recursive",
    "instantiate_template",
    "materialize_vertex",
    "substitute_vars",
    # Executor
    "CyclicDependencyError",
    "Executor",
    "SkippedSource",
    "SyncResult",
    "validate_dependency_graph",
    # Program helpers
    "VertexProgram",
    "load_vertex_program",
    # Vertex read path
    "emit_topology",
    "vertex_read",
    "vertex_fold",
    "vertex_fact_by_id",
    "vertex_facts",
    "vertex_search",
    "vertex_ticks",
    "vertex_summary",
]
