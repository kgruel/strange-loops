"""Migration sidecar for pre-Arrival legacy stores."""

from .inventory import SourceInventory, inventory
from .legacy_ids import (
    FactRow,
    Transform,
    classify_id_era,
    deterministic_ulid,
    identity,
    is_ulid,
    ulid_migration,
)
from .legacy_jsonl import (
    FACT_FIELDS,
    SIGNATURE_FIELD,
    TICK_FIELDS,
    JsonlCodecError,
    deserialize_records,
    deserialize_row,
    load_line,
    records_from_object,
)
from .legacy_sqlite import (
    _chain_head,
    _content_sha256,
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
    read_facts,
    read_ticks,
)
from .refusals import (
    AbsentObserverBatchRefused,
    MigrationRefused,
    MissingObserverBatchRefused,
    MixedObserverBatchRefused,
)

__all__ = [
    "AbsentObserverBatchRefused",
    "FACT_FIELDS",
    "FactRow",
    "JsonlCodecError",
    "MigrationRefused",
    "MissingObserverBatchRefused",
    "MixedObserverBatchRefused",
    "SIGNATURE_FIELD",
    "SourceInventory",
    "TICK_FIELDS",
    "Transform",
    "_chain_head",
    "_content_sha256",
    "_facts_have_signature",
    "_tick_columns",
    "classify_id_era",
    "deserialize_records",
    "deserialize_row",
    "deterministic_ulid",
    "identity",
    "inventory",
    "is_ulid",
    "load_line",
    "open_legacy_sqlite",
    "read_facts",
    "read_ticks",
    "records_from_object",
    "ulid_migration",
]
