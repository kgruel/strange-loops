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
)
from .target import TargetInfo, resolve_target
from .types import (
    AdmissionFailed,
    CeremonyFailed,
    ClientError,
    CommittedEmissionError,
    EmissionFailed,
    EmitPreviewResult,
    EmitReceipt,
    FactPageResult,
    FoldStateResult,
    KindMutationResult,
    ReadSummary,
    TargetError,
    TargetNotFound,
    TargetNotWritable,
    TargetUnsupported,
)

__all__ = [
    # Operations
    "resolve_target",
    "read_summary",
    "read_facts",
    "read_state",
    "read_ticks",
    "read_fact_by_id",
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
    "KindMutationResult",
    # Exceptions
    "ClientError",
    "TargetError",
    "TargetNotFound",
    "TargetUnsupported",
    "TargetNotWritable",
    "AdmissionFailed",
    "EmissionFailed",
    "CommittedEmissionError",
    "CeremonyFailed",
]
