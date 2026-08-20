"""Checkpoint dispatch on the Ordering taxonomy.

The warm path VertexHandle takes — hold a checkpoint, fold the newly received
rows onto it via ``Spec.replay_from`` — is sound only when appending can extend
the projection at its END. That is a property of the DECLARED read order, not
of the handle: ``atoms.ordering.is_suffix_stable`` is where it is decided.

These are DISPATCH tests on the taxonomy. They do not touch the checkpoint
machinery in ``engine.handle``; they pin which Ordering variants license it:

- ``Arrival()`` is suffix-stable, licenses the checkpoint, and is the ordering
  the fold path actually runs under — so the handle reports
  ``"checkpoint-suffix"`` and ``Spec.replay_from`` agrees with a cold replay.
- ``ByKey(K)`` is NOT. An append is an insertion into the middle of the
  projection, so a suffix replay onto a held state can disagree with a cold
  fold — no checkpoint, cold fold only.

The two negative facts are demonstrated against real data, not restated from
the predicate's docstring; the predicate is then asserted to agree with what
was observed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, get_args

import pytest
from atoms import Field, Spec, Upsert
from atoms.ordering import Arrival, ByKey, Ordering, OrderingError, is_suffix_stable, totalize

from engine.handle import open_vertex
from engine.sqlite_store import gen_id

# ---------------------------------------------------------------------------
# 1. The taxonomy answer, enumerated


#: The RULED licensing answer for every Ordering variant. Adding a variant to
#: the taxonomy without ruling on it fails `test_every_ordering_variant_is_ruled`.
LICENSING: dict[type, bool] = {Arrival: True, ByKey: False}


def test_every_ordering_variant_is_ruled() -> None:
    """No variant may default into (or out of) a checkpoint licence."""
    assert set(get_args(Ordering)) == set(LICENSING), (
        "an Ordering variant is unruled for checkpoint dispatch — rule it here"
    )


@pytest.mark.parametrize(
    "ordering,licensed",
    [(Arrival(), True), (ByKey("ts"), False), (ByKey("seq"), False)],
    ids=["arrival", "by-key-ts", "by-key-seq"],
)
def test_suffix_stability_licenses_the_checkpoint(ordering: Ordering, licensed: bool) -> None:
    assert is_suffix_stable(ordering) is licensed
    assert LICENSING[type(ordering)] is licensed


def test_unknown_ordering_variant_is_refused_not_defaulted() -> None:
    """A licence is never granted by falling off the end of the match."""
    with pytest.raises(OrderingError, match="unknown Ordering variant"):
        is_suffix_stable("arrival")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Why: an append extends Arrival, but INSERTS into ByKey


_RECORDS: list[dict[str, Any]] = [
    {"id": "r1", "ts": 300.0},
    {"id": "r2", "ts": 400.0},
]
#: Backdated: arrives last, but its key puts it FIRST under ByKey("ts").
_LATE_ARRIVAL: dict[str, Any] = {"id": "r3", "ts": 100.0}


def test_append_extends_the_arrival_projection_at_its_end() -> None:
    prefix = totalize(_RECORDS, Arrival())
    extended = totalize([*_RECORDS, _LATE_ARRIVAL], Arrival())

    assert extended[: len(prefix)] == prefix, "arrival prefix moved"
    assert extended[len(prefix) :] == [_LATE_ARRIVAL]
    assert is_suffix_stable(Arrival()), "observed suffix-stable; predicate must agree"


def test_append_inserts_into_the_middle_of_a_by_key_projection() -> None:
    ordering = ByKey("ts")
    prefix = totalize(_RECORDS, ordering)
    extended = totalize([*_RECORDS, _LATE_ARRIVAL], ordering)

    assert extended[0] == _LATE_ARRIVAL, "backdated record should sort first"
    assert extended[: len(prefix)] != prefix, "the held prefix is no longer a prefix"
    assert not is_suffix_stable(ordering), "observed NOT suffix-stable; predicate must agree"


def _spec() -> Spec:
    """Upsert by topic — last write wins, so the fold is order-SENSITIVE."""
    return Spec(
        name="decision",
        state_fields=(Field(name="items", kind="dict"),),
        folds=(Upsert(target="items", key="topic"),),
    )


def _payloads(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"topic": "t", "position": r["id"], "_ts": r["ts"], "_id": r["id"]} for r in records]


def test_replay_from_suffix_replay_is_sound_under_arrival_only() -> None:
    """`Spec.replay_from` onto a held state — the checkpoint's mechanism.

    Under Arrival it reproduces the cold replay exactly. Under ByKey('ts') the
    same suffix replay disagrees, because the backdated record belonged BEFORE
    the records already folded into the checkpoint.
    """
    spec = _spec()
    all_records = [*_RECORDS, _LATE_ARRIVAL]

    for ordering, sound in ((Arrival(), True), (ByKey("ts"), False)):
        prefix = totalize(_RECORDS, ordering)
        checkpoint = spec.replay(_payloads(prefix))
        warm = spec.replay_from(checkpoint, _payloads([_LATE_ARRIVAL]))
        cold = spec.replay(_payloads(totalize(all_records, ordering)))

        assert (warm == cold) is sound, (
            f"suffix replay under {ordering!r}: expected agreement={sound}"
        )
        assert is_suffix_stable(ordering) is sound


# ---------------------------------------------------------------------------
# 3. The handle runs under the licensed variant


#: The Ordering the fold path runs under. Single-store fold order IS receipt
#: order, which is exactly Arrival's native per-store order (Rule 17).
FOLD_ORDERING: Ordering = Arrival()


_VERTEX_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold(tmp_path: Path) -> tuple[Path, Path]:
    store = tmp_path / "store.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_VERTEX_KDL.format(store=store))
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS facts (id TEXT PRIMARY KEY, kind TEXT, ts REAL,"
        " observer TEXT, origin TEXT, payload TEXT, signature TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ticks (id TEXT PRIMARY KEY, name TEXT, ts REAL,"
        " payload TEXT)"
    )
    conn.commit()
    conn.close()
    return vpath, store


def _append(store: Path, ts: float, **payload: Any) -> None:
    import json

    conn = sqlite3.connect(str(store))
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (gen_id(), "decision", ts, "kyle", "", json.dumps(payload), ""),
    )
    conn.commit()
    conn.close()


def test_handle_takes_the_warm_path_under_the_licensed_ordering(tmp_path: Path) -> None:
    """The licence is not theoretical: the fold path runs under Arrival, and
    the handle's warm refresh is the checkpoint that licence permits.

    The backdated append is the discriminator — it would be an insertion under
    ByKey('ts'), and the handle still folds it as a suffix, which is only sound
    because the fold ordering is Arrival."""
    assert is_suffix_stable(FOLD_ORDERING), (
        "the fold path's ordering must license the checkpoint the handle takes"
    )

    vpath, store = _scaffold(tmp_path)
    with open_vertex(vpath) as handle:
        _append(store, 300.0, topic="t", position="first_arrival")
        handle.refresh()

        _append(store, 100.0, topic="t", position="backdated_but_later_arrival")
        batch = handle.refresh()

        assert batch is not None
        assert batch.replay_mode == "checkpoint-suffix"
