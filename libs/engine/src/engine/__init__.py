"""engine — Temporal infrastructure and identity.

Consolidates:
- ticks: Tick, Vertex, Loop, Store, Stream (temporal primitives)
- peers: Peer, Grant (identity and policy)

The respiratory system: Tick atom + Vertex + Store + fold engine.

Uses lazy imports via __getattr__ so that importing a single symbol
doesn't load the entire module tree.

Example:
    from engine import Tick, Vertex, Peer, Grant

    v = Vertex("main")
    v.register("count", 0, lambda s, p: s + 1)
    peer = Peer("alice", potential=frozenset({"count"}))
"""

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
    "observer_leaf",
    "observer_matches",
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
    "vertex_tick_fold",
    "vertex_fact_by_id",
    "vertex_facts",
    "vertex_search",
    "vertex_ticks",
    "vertex_summary",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Atoms
    "Tick": ("engine.tick", "Tick"),
    # Core
    "Loop": ("engine.loop", "Loop"),
    "Stream": ("engine.stream", "Stream"),
    "Tap": ("engine.stream", "Tap"),
    "Consumer": ("engine.stream", "Consumer"),
    "Vertex": ("engine.vertex", "Vertex"),
    # Persistence
    "FileStore": ("engine.file_store", "FileStore"),
    "FileWriter": ("engine.file_writer", "FileWriter"),
    "replay": ("engine.replay", "replay"),
    "SqliteStore": ("engine.sqlite_store", "SqliteStore"),
    "EventStore": ("engine.store", "EventStore"),
    "Store": ("engine.store", "Store"),
    "StoreReader": ("engine.store_reader", "StoreReader"),
    "Tailer": ("engine.tailer", "Tailer"),
    # Utilities
    "Forward": ("engine.forward", "Forward"),
    "Lens": ("engine.lens", "Lens"),
    "ClosableSource": ("engine.source_protocol", "ClosableSource"),
    "VertexSource": ("engine.source_protocol", "Source"),
    # Identity & Policy
    "observer_leaf": ("engine.observer", "observer_leaf"),
    "observer_matches": ("engine.observer", "observer_matches"),
    "Peer": ("engine.peer", "Peer"),
    "Grant": ("engine.peer", "Grant"),
    "delegate": ("engine.peer", "delegate"),
    "expand_grant": ("engine.peer", "expand_grant"),
    "grant": ("engine.peer", "grant"),
    "grant_of": ("engine.peer", "grant_of"),
    "restrict": ("engine.peer", "restrict"),
    "restrict_grant": ("engine.peer", "restrict_grant"),
    # Cadence
    "Cadence": ("engine.cadence", "Cadence"),
    # Compiler
    "CircularVertexError": ("engine.compiler", "CircularVertexError"),
    "CompiledVertex": ("engine.compiler", "CompiledVertex"),
    "FoldOverride": ("engine.compiler", "FoldOverride"),
    "collect_all_sources": ("engine.compiler", "collect_all_sources"),
    "collect_search_fields": ("engine.compiler", "collect_search_fields"),
    "compile_loop": ("engine.compiler", "compile_loop"),
    "compile_source": ("engine.compiler", "compile_source"),
    "compile_sources": ("engine.compiler", "compile_sources"),
    "compile_sources_block": ("engine.compiler", "compile_sources_block"),
    "compile_vertex": ("engine.compiler", "compile_vertex"),
    "compile_vertex_recursive": ("engine.compiler", "compile_vertex_recursive"),
    "instantiate_template": ("engine.compiler", "instantiate_template"),
    "materialize_vertex": ("engine.compiler", "materialize_vertex"),
    "substitute_vars": ("engine.compiler", "substitute_vars"),
    # Executor
    "CyclicDependencyError": ("engine.executor", "CyclicDependencyError"),
    "Executor": ("engine.executor", "Executor"),
    "SkippedSource": ("engine.executor", "SkippedSource"),
    "SyncResult": ("engine.executor", "SyncResult"),
    "validate_dependency_graph": ("engine.executor", "validate_dependency_graph"),
    # Program helpers
    "VertexProgram": ("engine.program", "VertexProgram"),
    "load_vertex_program": ("engine.program", "load_vertex_program"),
    # Vertex read path
    "emit_topology": ("engine.vertex_reader", "emit_topology"),
    "vertex_fact_by_id": ("engine.vertex_reader", "vertex_fact_by_id"),
    "vertex_facts": ("engine.vertex_reader", "vertex_facts"),
    "vertex_fold": ("engine.vertex_reader", "vertex_fold"),
    "vertex_tick_fold": ("engine.vertex_reader", "vertex_tick_fold"),
    "vertex_read": ("engine.vertex_reader", "vertex_read"),
    "vertex_search": ("engine.vertex_reader", "vertex_search"),
    "vertex_summary": ("engine.vertex_reader", "vertex_summary"),
    "vertex_ticks": ("engine.vertex_reader", "vertex_ticks"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'engine' has no attribute {name!r}")
