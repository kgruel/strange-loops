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
from .legacy_source import (
    BatchUnit,
    FlatFactUnit,
    LegacySource,
    LegacyUnit,
    TickUnit,
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
    BatchRegroupRefused,
    DeclarationKeyRefused,
    LegacySourceRefused,
    MigrationRefused,
    MissingCustodianKeyRefused,
)
from .transform import (
    DroppedUnit,
    GenesisRequirements,
    TransformExceptions,
    TransformResult,
    coerce_vertex,
    transform,
)

__all__ = [
    "BatchRegroupRefused",
    "BatchUnit",
    "DeclarationKeyRefused",
    "DroppedUnit",
    "FACT_FIELDS",
    "FactRow",
    "FlatFactUnit",
    "GenesisRequirements",
    "JsonlCodecError",
    "LegacySource",
    "LegacySourceRefused",
    "LegacyUnit",
    "MigrationRefused",
    "MissingCustodianKeyRefused",
    "SIGNATURE_FIELD",
    "SourceInventory",
    "TICK_FIELDS",
    "TickUnit",
    "Transform",
    "TransformExceptions",
    "TransformResult",
    "_content_sha256",
    "_facts_have_signature",
    "_tick_columns",
    "classify_id_era",
    "coerce_vertex",
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
