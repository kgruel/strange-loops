"""sdk — Loops apex composition library.

The single headless composition layer over engine, custody, lang, store, atoms, and sign.
Provides high-level, transport-agnostic read, emit, and kind mutation operations
returning typed result models.
"""

from .declare import init_vertex, inspect_declaration
from .emit import CustodyCredentialProvider, emit_batch, emit_fact, preview_emission
from .kind import (
    add_kind,
    edit_kind,
    grant_observer,
    plan_kind_mutation,
    recover_ceremony,
    remove_kind,
    revoke_observer,
)
from .read import (
    read_fact_by_id,
    read_facts,
    read_state,
    read_summary,
    read_ticks,
    read_timeline,
    resolve_entity,
    search_facts,
    sync_target,
)
from .target import TargetInfo, discover_targets, resolve_target
from .types import (
    AdmissionFailed,
    CeremonyFailed,
    CommittedEmissionError,
    DeclarationInspectionResult,
    DeclarationPlanResult,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    InitVertexResult,
    InvalidEmissionRequest,
    KindMutationResult,
    ReadSummary,
    SdkError,
    SdkValueError,
    SearchResult,
    SearchResultItem,
    SyncResult,
    TargetError,
    TargetNotFound,
    TargetNotWritable,
    TargetUnsupported,
    TimelineEvent,
    TimelineResult,
)

__all__ = [
    # Operations
    "resolve_target",
    "discover_targets",
    "init_vertex",
    "inspect_declaration",
    "read_summary",
    "read_facts",
    "read_state",
    "read_ticks",
    "read_fact_by_id",
    "search_facts",
    "resolve_entity",
    "read_timeline",
    "sync_target",
    "emit_fact",
    "emit_batch",
    "preview_emission",
    "add_kind",
    "edit_kind",
    "remove_kind",
    "grant_observer",
    "revoke_observer",
    "plan_kind_mutation",
    "recover_ceremony",
    # Providers
    "CustodyCredentialProvider",
    # Models
    "TargetInfo",
    "InitVertexResult",
    "DeclarationInspectionResult",
    "DeclarationPlanResult",
    "ReadSummary",
    "FactPageResult",
    "FoldStateResult",
    "EmitReceipt",
    "EmitPreviewResult",
    "SearchResult",
    "SearchResultItem",
    "TimelineResult",
    "TimelineEvent",
    "SyncResult",
    "KindMutationResult",
    # Exceptions
    "SdkError",
    "SdkValueError",
    "TargetError",
    "TargetNotFound",
    "TargetUnsupported",
    "TargetNotWritable",
    "AdmissionFailed",
    "EmissionFailed",
    "InvalidEmissionRequest",
    "CommittedEmissionError",
    "CeremonyFailed",
]
