"""Ordering — the declared read order for a stream of records.

Ordering is DECLARED, never inferred. Two variants:

- ``Arrival()`` — the substrate's native per-store order. The store yields it;
  this module never synthesizes it from record fields.
- ``ByKey(field)`` — a projection ordered by one flat payload field, with the
  record id as tie-break only.

``totalize()`` is the ONLY definition of the sort key. Readers (StoreReader,
the combined read, the conformance lens generator) import it rather than
growing near-copies of the same ``sort(key=...)`` line.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeVar


class OrderingError(Exception):
    """Raised when records cannot be ordered under the declared Ordering.

    A declaration error against the data — mixed key types under one declared
    key, or key values that do not compare — not something a comparator may
    paper over with a coercion.
    """

    pass


@dataclass(frozen=True)
class Arrival:
    """The substrate's native per-store order.

    Arrival ordinals are dense PER-LOG, so this names an order the store
    already yields; ``totalize`` returns the records as given, untouched. It
    is not expressible across a combined view of several stores.
    """


@dataclass(frozen=True)
class ByKey:
    """Order by one flat payload field, id ascending as tie-break.

    Attributes:
        field: Flat payload field name. Dotted paths are not this cut.

    Example:
        ByKey(field="ts")
    """

    field: str


Ordering = Arrival | ByKey

R = TypeVar("R")


def is_suffix_stable(ordering: Ordering) -> bool:
    """Does appending a record extend this projection at its END?

    A projection is suffix-stable when a newly appended record can only land
    after every record already in it. `Arrival()` is: the substrate's native
    order IS append order, so what arrives later sorts later, always.

    `ByKey(K)` is NOT. A record's position is its key value, and a record
    arriving now may carry any key — so an append is an INSERTION into the
    middle of the projection, not an extension of its tail.

    Consumers that hold a result computed over a prefix and want to extend it
    with the newly arrived records — rather than recomputing over the whole
    history — are sound only over a suffix-stable ordering. Engine's
    incremental fold path is the consumer; this predicate is the taxonomy
    fact it dispatches on.

    Raises:
        OrderingError: Unknown `Ordering` variant. A new variant must be
            RULED suffix-stable or not, never defaulted.
    """
    match ordering:
        case Arrival():
            return True
        case ByKey():
            return False
        case _:
            raise OrderingError(f"unknown Ordering variant: {ordering!r}")


def _default_get_field(record: Any, field: str) -> Any:
    if isinstance(record, Mapping):
        return record.get(field)
    return getattr(record, field, None)


def _default_get_id(record: Any) -> Any:
    if isinstance(record, Mapping):
        return record["id"]
    return record.id


def totalize(
    records: Iterable[R],
    ordering: Ordering,
    *,
    get_field: Callable[[R, str], Any] = _default_get_field,
    get_id: Callable[[R], Any] = _default_get_id,
) -> list[R]:
    """Order records under a declared Ordering. The one sort-key definition.

    ``ByKey(K)``: sort key ``(K(record), record.id)``, id ascending. **The id
    is a TIE-BREAK ONLY — never semantic time.**

    A record without ``K`` is NOT in the ``ByKey(K)`` projection: a key names
    what it projects, and absence is non-membership. A ``None`` value counts
    as absent. This is exclusion-by-declaration — the caller named K — not
    silent loss.

    Key values of mixed types under one declared key (``"5"`` and ``5``, or
    ``True`` and ``1``) are REFUSED with ``OrderingError``. Same-typed values
    that do not compare (dicts, say) are refused the same way.

    ``Arrival()`` returns the records as given — the store's native order is
    the store's job to yield, never synthesized here. Both accessors are
    ignored for ``Arrival()``.

    Args:
        records: The records to order.
        ordering: ``Arrival()`` or ``ByKey(field)``.
        get_field: Reads a named field off a record. The default reads a
            Mapping key or an attribute, missing → None. Row-tuple callers
            pass their own.
        get_id: Reads the record id. The default reads the ``id`` Mapping key
            or attribute.

    Returns:
        A new list, ordered. For ``ByKey``, records missing the key are absent.

    Raises:
        OrderingError: Mixed or non-comparable key types under the declared key,
            or an unknown Ordering variant.
    """
    match ordering:
        case Arrival():
            return list(records)
        case ByKey(field=field):
            keyed: list[tuple[Any, Any, R]] = []
            key_type: type | None = None
            for record in records:
                value = get_field(record, field)
                if value is None:
                    continue
                if key_type is None:
                    key_type = type(value)
                elif type(value) is not key_type:
                    raise OrderingError(
                        f"mixed key types under declared key {field!r}: "
                        f"{key_type.__name__} and {type(value).__name__} "
                        f"(offending value {value!r})"
                    )
                keyed.append((value, get_id(record), record))
            try:
                keyed.sort(key=lambda entry: (entry[0], entry[1]))
            except TypeError as exc:
                raise OrderingError(
                    f"key values under declared key {field!r} do not compare: {exc}"
                ) from exc
            return [entry[2] for entry in keyed]
        case _:
            raise OrderingError(f"unknown Ordering variant: {ordering!r}")
