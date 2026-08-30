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
    _content_sha256,
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
    read_facts,
    read_ticks,
)
from .refusals import (
    LegacySourceRefused,
    MigrationRefused,
)
from .transform import (
    GenesisRequirements,
    TransformExceptions,
    TransformResult,
    transform,
)

__all__ = [
    "FACT_FIELDS",
    "FactRow",
    "GenesisRequirements",
    "JsonlCodecError",
    "LegacySourceRefused",
    "MigrationRefused",
    "SIGNATURE_FIELD",
    "SourceInventory",
    "TICK_FIELDS",
    "Transform",
    "TransformExceptions",
    "TransformResult",
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
    "transform",
    "ulid_migration",
]
