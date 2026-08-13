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
class ApplyDelta:
    """One step of the fold replay — the fact applied and its resulting state.

    Captured during the ``Spec.apply`` walk (upsert mode only): the chronology
    the trace render draws, oldest-first. ``changed`` names the fields this fact
    moved (added or overwrote); ``status_to`` carries the resulting ``status``
    value when this apply moved it — the one transition the trace narrates
    inline (``status→review``). The trace's ``×n`` is facts-folded-so-far
    (``index``), matching what ``×n`` means everywhere else in the spine.
    """

    index: int  # 1-based position in fold (chronological) order
    total: int
    ts: float | str | None
    observer: str
    changed: tuple[str, ...]
    status_to: str | None = None


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
    applies: tuple[ApplyDelta, ...] = ()  # per-apply state deltas (upsert trace)

    @property
    def total_facts(self) -> int:
        return len(self.facts)


# Fields never attributed on their own row — engine-internal metadata and the
# address field itself (mirrors the fold lens body-field skip at fold.py:1096).
_META_PREFIX = "_"


def _winning_state_key(facts: list[dict], key_field: str | None, key: str) -> Any:
    """Resolve the ONE engine item this ``--why`` explains, BEFORE the replay.

    Contract: ``--why`` explains exactly the row read renders — one item,
    for the whole replay. The engine folds by the NATIVE payload value
    (``is not None`` acceptance — a stored JSON numeric ``0`` keys the
    state by int ``0``), while the address grammar, the source-fact buckets
    (``engine.vertex_reader``'s ``f"{kind}/{key}"``), and
    ``surface._row_key`` all carry the STRING form
    (finding:chw-sol-r5-provenance-key-lookup). When a native ``0`` and a
    string ``"0"`` coexist, STRING WINS — the same tie rule the r5 lookup
    documented — and the losing item contributes NOTHING to
    fields/changed: it is a different engine item that happens to share a
    projected address (identity held at
    thread:fold-key-identity-native-vs-string). Resolving once here, from
    the chronology's raw key values, is what makes that hold: the r6
    defect (finding:chw-sol-r6-f1-replay-identity-switch) was a per-step
    lookup that attributed the native entry early, switched to the string
    entry when it appeared, and never cleared the earlier change log —
    mixed-item output that depended on emission order.

    Returns the raw payload key value whose fold-state entry the replay
    attributes (the exact string when present; else the native value
    projecting to it; else the string itself, yielding an honest empty).
    """
    from loops.foldkey import project_fold_key

    if not key_field:
        return key
    candidates: list[Any] = []
    for payload in facts:
        val = payload.get(key_field)
        if val is None or project_fold_key(val) != key:
            continue
        if not any(v is val or v == val for v in candidates):
            candidates.append(val)
    if any(isinstance(v, str) and v == key for v in candidates):
        return key
    return candidates[0] if candidates else key


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
    # The winning identity is fixed ONCE, before the replay — no mid-replay
    # switching, no residual change log from a projected-address sibling
    # (finding:chw-sol-r6-f1-replay-identity-switch; see _winning_state_key).
    # The engine keys the replayed state by fold_op.key's raw payload value,
    # so the winner resolves over that field.
    winner = _winning_state_key(facts, fold_op.key, key)

    # Per-field change log: ordered list of (value, FactRef) for each field, in
    # the order the field's value actually changed. First appearance order of
    # fields is preserved for a stable, readable row order. ``fold_fn`` mutates
    # ``state`` in place (the real engine fold), so we snapshot the key's entry
    # after each step and diff against the prior snapshot.
    changes: dict[str, list[tuple[Any, FactRef]]] = {}
    field_order: list[str] = []
    applies: list[ApplyDelta] = []
    prev_entry: dict[str, Any] = {}
    state: dict[str, Any] = {target: {}}

    for i, payload in enumerate(facts, start=1):
        fold_fn(state, payload)
        entry = state.get(target, {}).get(winner, {})
        if not isinstance(entry, dict):
            prev_entry = {}
            continue
        fref = _fact_ref(payload, i, total)
        changed_here: list[str] = []
        for fld, val in entry.items():
            if fld.startswith(_META_PREFIX) or fld in skip:
                continue
            if fld not in prev_entry or prev_entry[fld] != val:
                changed_here.append(fld)
                if fld not in changes:
                    changes[fld] = []
                    field_order.append(fld)
                changes[fld].append((val, fref))
        status_to = (
            str(entry["status"]) if "status" in changed_here else None
        )
        applies.append(ApplyDelta(
            index=i, total=total, ts=payload.get("_ts"),
            observer=str(payload.get("_observer", "") or ""),
            changed=tuple(changed_here), status_to=status_to,
        ))
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
        applies=tuple(applies),
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
        "applies": [
            {
                "index": a.index,
                "total": a.total,
                "ts": a.ts,
                "observer": a.observer,
                "changed": list(a.changed),
                "status_to": a.status_to,
            }
            for a in prov.applies
        ],
    }
