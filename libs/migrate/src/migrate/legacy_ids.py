"""Legacy ID migration and era knowledge — frozen transform primitives.

Historical artifact copied from ``store.rebirth`` at commit
``affe92a6fc1a034b477cbc068cc563f6e5ca69e6``.

Quarantined verbatim in ``migrate`` to preserve legacy ID era knowledge:
- uuid4 era (2026-03-15..05-16): hex IDs;
- lowercase-ULID era (sqlite-ulid C extension): lowercase Crockford base32;
- canonical ULID era (python-ulid): uppercase Crockford base32.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace

from ulid import ULID

__all__ = [
    "FactRow",
    "Transform",
    "is_ulid",
    "deterministic_ulid",
    "identity",
    "ulid_migration",
    "classify_id_era",
]

_CROCKFORD = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
_CROCKFORD_LOWER = frozenset("0123456789abcdefghjkmnpqrstvwxyz")


@dataclass(frozen=True)
class FactRow:
    """One source fact row. ``payload`` is the stored JSON TEXT, verbatim.

    ``signature`` is the fact's authorship signature (delta 3), carried
    verbatim through rebirth — it commits to content only (no id), so an
    id migration preserves its validity. The replay spine drops it to
    None when a transform alters any CONTENT field (kind, ts, observer,
    origin, payload): the original authorship claim no longer holds and
    rebirth must not re-assert it.
    """

    id: str
    kind: str
    ts: float
    observer: str
    origin: str
    payload: str
    signature: str | None = None


@dataclass(frozen=True)
class Transform:
    """A deterministic per-fact mapping.

    ``rule`` is the receipt-citable name — it is recorded in the receipt
    fact and used by verify_rebirth to reconstruct built-in transforms.
    ``map_fact`` returns the (possibly modified) row, or None to drop it.

    Determinism is load-bearing: re-running the transform over the same
    source must reproduce the target byte for byte — that re-run IS the
    receipt verification.
    """

    rule: str
    map_fact: Callable[[FactRow], FactRow | None]


def is_ulid(value: str) -> bool:
    """True when value has canonical ULID shape (26 chars, uppercase Crockford base32)."""
    return len(value) == 26 and all(c in _CROCKFORD for c in value)


def deterministic_ulid(ts: float, seed: str) -> str:
    """Build a ULID from an event timestamp and a deterministic seed.

    48-bit millisecond timestamp from ``ts``, 80-bit entropy from
    ``sha256(seed)``. Same inputs, same ULID — this is what makes
    rebirth re-runnable and therefore verifiable.
    """
    ms = int(ts * 1000)
    entropy = hashlib.sha256(seed.encode()).digest()[:10]
    return str(ULID.from_bytes(ms.to_bytes(6, "big") + entropy))


def identity() -> Transform:
    """Pass every fact through unchanged (cleanup/re-seal rebirth)."""
    return Transform(rule="identity", map_fact=lambda row: row)


def ulid_migration() -> Transform:
    """Migrate non-canonical ids to deterministic ULIDs; canonical ids pass.

    Canonical = uppercase Crockford ULID, the only form whose
    lexicographic order matches event time. One uniform rule covers
    every broken era — live stores turned out to have THREE:

    - uuid4 era (2026-03-15..05-16): hex ids sort above every ULID;
    - lowercase-ULID era (sqlite-ulid C extension): time-correct values,
      but lowercase sorts above uppercase in ASCII, so the whole era
      sorts out of order against canonical ids;
    - canonical ULIDs (python-ulid): pass through untouched — merge
      dedup and external citations key on them.

    Migrated id: ``ULID(ms(fact.ts) || sha256(old_id)[:10])`` — event-time
    sortable, so an id-ordered read finally approximates event order across
    the whole store. That is a read-lens property; the rebirth walks and
    rewrites rows in receipt order (rowid), which is what the reborn store
    folds on and what this migration preserves.
    """

    def map_fact(row: FactRow) -> FactRow:
        if is_ulid(row.id):
            return row
        return replace(row, id=deterministic_ulid(row.ts, row.id))

    return Transform(rule="ulid-migration", map_fact=map_fact)


def classify_id_era(id_str: str) -> str:
    """Classify an ID into its historical era: canonical-ulid, lowercase-ulid, or uuid4."""
    if is_ulid(id_str):
        return "canonical-ulid"
    if len(id_str) == 26 and all(c in _CROCKFORD_LOWER for c in id_str):
        return "lowercase-ulid"
    return "uuid4"
