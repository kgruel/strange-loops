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
    "Receipt",
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
    "gen_id",
    "replay",
    "fact_commitment_hash",
    "tick_row_hash",
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
    # Declaration resolver (store-backed declaration seam)
    "load_declaration",
    "load_declaration_status",
    "resolve_declaration_documents",
    # Witness positions (read-path temporal cursor)
    "WitnessPosition",
    "WitnessFold",
    "TickAnchor",
    "resolve_witness_position",
    "resolve_seq",
    "resolve_tick_cursor",
    "resolve_tick_floor",
    "expand_fact_prefix",
    "durable_handle",
    "verify_position_for_store",
    "diff_interval_report",
    "WitnessResolutionError",
    "UnknownWitnessHandle",
    "MidReceiptGroupPosition",
    "WitnessAggregateUnsupported",
    "WitnessLineageMismatch",
    "SeqOutOfRange",
    "UnknownTickHandle",
    "NoWitnessAnchor",
    # VertexHandle (daemon-shaped engine access, 0.8.0 session 2)
    "open_vertex",
    "VertexHandle",
    "VertexSnapshot",
    "ChangeBatch",
    "ReceiptEvent",
    "TickEvent",
    "RowChange",
    "FoldAddress",
    "StoreProbe",
    "FactHead",
    "TickHead",
    "StoredFact",
    "StoredTick",
    "StoreIdentity",
    "CredentialProvider",
    "WriteCredentials",
    "ReceiveResult",
    "HandleError",
    "HandleClosed",
    "HandleInvalidated",
    "StoreBusy",
    "StoreReplaced",
    "CursorInvalidated",
    "AggregateHandleUnsupported",
    "ReadOnlyAggregate",
    "ConditionalEmitUnsupported",
    "ReceiveCommittedError",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Atoms
    "Tick": ("engine.tick", "Tick"),
    # Core
    "Loop": ("engine.loop", "Loop"),
    "Stream": ("engine.stream", "Stream"),
    "Tap": ("engine.stream", "Tap"),
    "Consumer": ("engine.stream", "Consumer"),
    "Receipt": ("engine.vertex", "Receipt"),
    "Vertex": ("engine.vertex", "Vertex"),
    # Persistence
    "FileStore": ("engine.file_store", "FileStore"),
    "FileWriter": ("engine.file_writer", "FileWriter"),
    "replay": ("engine.replay", "replay"),
    "SqliteStore": ("engine.sqlite_store", "SqliteStore"),
    "gen_id": ("engine.sqlite_store", "gen_id"),
    "fact_commitment_hash": ("engine.sqlite_store", "fact_commitment_hash"),
    "tick_row_hash": ("engine.sqlite_store", "tick_row_hash"),
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
    # Declaration resolver
    "load_declaration": ("engine.declaration", "load_declaration"),
    "load_declaration_status": ("engine.declaration", "load_declaration_status"),
    "resolve_declaration_documents": (
        "engine.declaration",
        "resolve_declaration_documents",
    ),
    # Witness positions (read-path temporal cursor)
    "WitnessPosition": ("engine.witness", "WitnessPosition"),
    "WitnessFold": ("engine.witness", "WitnessFold"),
    "TickAnchor": ("engine.witness", "TickAnchor"),
    "resolve_witness_position": ("engine.witness", "resolve_witness_position"),
    "resolve_seq": ("engine.witness", "resolve_seq"),
    "resolve_tick_cursor": ("engine.witness", "resolve_tick_cursor"),
    "resolve_tick_floor": ("engine.witness", "resolve_tick_floor"),
    "expand_fact_prefix": ("engine.witness", "expand_fact_prefix"),
    "durable_handle": ("engine.witness", "durable_handle"),
    "verify_position_for_store": (
        "engine.witness",
        "verify_position_for_store",
    ),
    "diff_interval_report": ("engine.witness", "diff_interval_report"),
    "WitnessResolutionError": ("engine.witness", "WitnessResolutionError"),
    "UnknownWitnessHandle": ("engine.witness", "UnknownWitnessHandle"),
    "MidReceiptGroupPosition": ("engine.witness", "MidReceiptGroupPosition"),
    "WitnessAggregateUnsupported": (
        "engine.witness",
        "WitnessAggregateUnsupported",
    ),
    "WitnessLineageMismatch": ("engine.witness", "WitnessLineageMismatch"),
    "SeqOutOfRange": ("engine.witness", "SeqOutOfRange"),
    "UnknownTickHandle": ("engine.witness", "UnknownTickHandle"),
    "NoWitnessAnchor": ("engine.witness", "NoWitnessAnchor"),
    # VertexHandle (daemon-shaped engine access, 0.8.0 session 2)
    "open_vertex": ("engine.handle", "open_vertex"),
    "VertexHandle": ("engine.handle", "VertexHandle"),
    "VertexSnapshot": ("engine.handle", "VertexSnapshot"),
    "ChangeBatch": ("engine.handle", "ChangeBatch"),
    "ReceiptEvent": ("engine.handle", "ReceiptEvent"),
    "TickEvent": ("engine.handle", "TickEvent"),
    "RowChange": ("engine.handle", "RowChange"),
    "FoldAddress": ("engine.handle", "FoldAddress"),
    "StoreProbe": ("engine.handle", "StoreProbe"),
    "FactHead": ("engine.handle", "FactHead"),
    "TickHead": ("engine.handle", "TickHead"),
    "StoredFact": ("engine.handle", "StoredFact"),
    "StoredTick": ("engine.handle", "StoredTick"),
    "StoreIdentity": ("engine.handle", "StoreIdentity"),
    "CredentialProvider": ("engine.handle", "CredentialProvider"),
    "WriteCredentials": ("engine.handle", "WriteCredentials"),
    "ReceiveResult": ("engine.handle", "ReceiveResult"),
    "HandleError": ("engine.handle", "HandleError"),
    "HandleClosed": ("engine.handle", "HandleClosed"),
    "HandleInvalidated": ("engine.handle", "HandleInvalidated"),
    "StoreBusy": ("engine.handle", "StoreBusy"),
    "StoreReplaced": ("engine.handle", "StoreReplaced"),
    "CursorInvalidated": ("engine.handle", "CursorInvalidated"),
    "AggregateHandleUnsupported": ("engine.handle", "AggregateHandleUnsupported"),
    "ReadOnlyAggregate": ("engine.handle", "ReadOnlyAggregate"),
    "ConditionalEmitUnsupported": ("engine.handle", "ConditionalEmitUnsupported"),
    "ReceiveCommittedError": ("engine.handle", "ReceiveCommittedError"),
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
