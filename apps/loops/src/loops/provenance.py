"""Diff-replay provenance — per-field attribution for a single fold key.

The read-side answer to "why does this folded entry look the way it does?"
For an exact ``(kind, key)`` address, replay the key's source facts through
the kind's REAL fold op in order and diff the folded payload after each step.
Every field is attributed to the fact that last changed it; superseded values
carry the fact that set them.

Faithful by construction: it drives the actual ``Spec``/fold op (no parallel
mirror to drift). ``source_facts`` is populated only for Upsert-fold kinds
(engine gates it there), so an Upsert replay is the live case; any other fold
op degrades to chronology-is-the-provenance (the fold order already IS the
answer). O(facts x fields) — fine for a single-key drill.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from atoms.fold import FoldOp


@dataclass(frozen=True)
class FactRef:
    """A pointer back to one source fact in the key's chronology."""

    index: int  # 1-based position in fold (chronological) order
    total: int  # total facts under this key
    ts: float | str | None
    observer: str


@dataclass(frozen=True)
class FieldPrior:
    """A superseded value and the fact that set it (newest-first in history)."""

    value: Any
    fact: FactRef


@dataclass(frozen=True)
class FieldAttribution:
    """Current value of one field + who set it, with its supersession history."""

    field: str
    value: Any
    setter: FactRef  # the fact that last changed this field to ``value``
    priors: tuple[FieldPrior, ...] = ()  # older values, newest-first


@dataclass(frozen=True)
class Provenance:
    """The per-field attribution ledger for one folded ``(kind, key)`` entry.

    ``mode`` discriminates the render:
      - ``"upsert"``  — diff-replay attribution in ``fields``
      - ``"collect"`` — chronology is the provenance; ``fields`` empty,
        ``facts`` carries the ordered raw ledger
      - ``"empty"``   — no source facts for this key (drill found nothing)
    """

    kind: str
    key: str
    key_field: str | None
    mode: str
    fields: tuple[FieldAttribution, ...] = ()
    facts: tuple[dict, ...] = ()  # raw source facts, chronological
    first_ts: float | str | None = None
    last_ts: float | str | None = None
    observers: tuple[str, ...] = ()

    @property
    def total_facts(self) -> int:
        return len(self.facts)


# Fields never attributed on their own row — engine-internal metadata and the
# address field itself (mirrors the fold lens body-field skip at fold.py:1096).
_META_PREFIX = "_"


def _fact_ref(payload: dict, index: int, total: int) -> FactRef:
    return FactRef(
        index=index,
        total=total,
        ts=payload.get("_ts"),
        observer=str(payload.get("_observer", "") or ""),
    )


def replay_attribution(
    fold_op: "FoldOp | None",
    source_facts: list[dict],
    *,
    kind: str,
    key: str,
    key_field: str | None,
) -> Provenance:
    """Attribute each field of a folded key to the fact that last set it.

    ``source_facts`` is the key's raw fact list in fold (append/chronological)
    order — exactly what the engine folded. ``fold_op`` is the kind's real fold
    op; when it isn't an ``Upsert`` (or is ``None``), the chronology already IS
    the provenance and we degrade to ``mode="collect"``.
    """
    from atoms.engine import build_fold_fn
    from atoms.fold import Upsert

    facts = [f for f in source_facts if isinstance(f, dict)]
    total = len(facts)
    observers = tuple(
        dict.fromkeys(str(f.get("_observer", "") or "") for f in facts if f.get("_observer"))
    )
    first_ts = facts[0].get("_ts") if facts else None
    last_ts = facts[-1].get("_ts") if facts else None

    if total == 0:
        return Provenance(kind=kind, key=key, key_field=key_field, mode="empty")

    if not isinstance(fold_op, Upsert):
        return Provenance(
            kind=kind, key=key, key_field=key_field, mode="collect",
            facts=tuple(facts), first_ts=first_ts, last_ts=last_ts,
            observers=observers,
        )

    fold_fn = build_fold_fn(fold_op)
    target = fold_op.target
    skip = {key_field or "", ""}

    # Per-field change log: ordered list of (value, FactRef) for each field, in
    # the order the field's value actually changed. First appearance order of
    # fields is preserved for a stable, readable row order. ``fold_fn`` mutates
    # ``state`` in place (the real engine fold), so we snapshot the key's entry
    # after each step and diff against the prior snapshot.
    changes: dict[str, list[tuple[Any, FactRef]]] = {}
    field_order: list[str] = []
    prev_entry: dict[str, Any] = {}
    state: dict[str, Any] = {target: {}}

    for i, payload in enumerate(facts, start=1):
        fold_fn(state, payload)
        entry = state.get(target, {}).get(key, {})
        if not isinstance(entry, dict):
            prev_entry = {}
            continue
        fref = _fact_ref(payload, i, total)
        for fld, val in entry.items():
            if fld.startswith(_META_PREFIX) or fld in skip:
                continue
            if fld not in prev_entry or prev_entry[fld] != val:
                if fld not in changes:
                    changes[fld] = []
                    field_order.append(fld)
                changes[fld].append((val, fref))
        prev_entry = dict(entry)

    attributions: list[FieldAttribution] = []
    for fld in field_order:
        log = changes[fld]
        cur_val, cur_ref = log[-1]
        priors = tuple(
            FieldPrior(value=v, fact=r) for v, r in reversed(log[:-1])
        )
        attributions.append(
            FieldAttribution(field=fld, value=cur_val, setter=cur_ref, priors=priors)
        )

    return Provenance(
        kind=kind, key=key, key_field=key_field, mode="upsert",
        fields=tuple(attributions), facts=tuple(facts),
        first_ts=first_ts, last_ts=last_ts, observers=observers,
    )


def to_dict(prov: Provenance) -> dict:
    """JSON-clean encoding of a Provenance ledger (the ``--json`` shape)."""

    def _ref(r: FactRef) -> dict:
        return {"index": r.index, "total": r.total, "ts": r.ts, "observer": r.observer}

    return {
        "kind": prov.kind,
        "key": prov.key,
        "key_field": prov.key_field,
        "mode": prov.mode,
        "total_facts": prov.total_facts,
        "first_ts": prov.first_ts,
        "last_ts": prov.last_ts,
        "observers": list(prov.observers),
        "fields": [
            {
                "field": a.field,
                "value": a.value,
                "setter": _ref(a.setter),
                "priors": [
                    {"value": p.value, "setter": _ref(p.fact)} for p in a.priors
                ],
            }
            for a in prov.fields
        ],
        "facts": [dict(f) for f in prov.facts] if prov.mode != "upsert" else [],
    }
