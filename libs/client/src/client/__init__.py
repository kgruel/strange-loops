"""client — Loops apex composition library.

The single headless composition layer over engine, custody, lang, store, atoms, and sign.
Provides high-level, transport-agnostic read, emit, and kind mutation operations
returning typed result models.
"""

from .emit import CustodyCredentialProvider, emit_batch, emit_fact, preview_emission
from .kind import add_kind, edit_kind, recover_ceremony, remove_kind
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
from .target import TargetInfo, resolve_target
from .types import (
    AdmissionFailed,
    CeremonyFailed,
    ClientError,
    ClientValueError,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    InvalidEmissionRequest,
    KindMutationResult,
    ReadSummary,
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
    "recover_ceremony",
    # Providers
    "CustodyCredentialProvider",
    # Models
    "TargetInfo",
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
    "ClientError",
    "ClientValueError",
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
