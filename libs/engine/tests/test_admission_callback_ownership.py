"""The admission op does not mutate the mapping its caller hands it.

`finding:slice2-wp3-callback-mapping-mutation` (sol-LOW r1, S2WP3-L-1). The
dedup pass writes every PROPOSED id into the snapshot it is dedup'ing against
— that is how one source carrying an id twice appends it once — but it writes
them before the compare-and-swap append that would make them true. While that
code was private to ``store.merge`` the mapping was always freshly built by a
SELECT one call earlier, so the write could not reach anyone. Extraction made
the mapping a value crossing a callback boundary, and ownership of a value
that crosses a boundary is a question the boundary has to answer.

It answers it by copying. A backend that serves ``target_state`` out of an
owned, incrementally-maintained cache is a legitimate implementation of the
contract — no clause forbids it, and the second backend the contract exists
for is exactly the kind that would have one. Without the copy such a backend
loses records SILENTLY: attempt 1 injects the proposed ids into the cache,
the compare-and-swap loses a race, and attempt 2 dedups the records away
against attempt 1's own proposals and reports them SKIPPED.

The repro below is that sequence, with the interloper landing between the pin
read and the append so the first attempt is guaranteed to lose.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine.admission import SourceRows, admit_records
from engine.arrival import ArrivalLog, Entry
from engine.arrival_contract import Head
from tests.conftest import STUB_KEY as _KEY
from tests.conftest import stub_sign as _sign

# (id, kind, ts, observer, origin, payload, signature) — FACT_CONTENT_COLUMNS.
_SOURCE_ROWS = [
    ("01SRCA", "note", 1000.0, "kyle", "", json.dumps({"body": "a"}), None),
    ("01SRCB", "note", 1001.0, "kyle", "", json.dumps({"body": "b"}), None),
]

# One row the target genuinely holds, so "unmutated" asserts both directions:
# nothing was injected, and nothing the caller put there was removed.
_ALREADY_HELD = {"01HELD": ("fact", "note", 900.0, "kyle", "", "{}", None)}


def _source() -> SourceRows:
    return SourceRows(
        groups=[("fact", [("fact", row)], None) for row in _SOURCE_ROWS],
        fact_count=len(_SOURCE_ROWS),
        tick_count=0,
    )


def _head(log: ArrivalLog) -> Head:
    record = log.head()
    return Head(
        lineage=record["lin"], ordinal=record["ord"], record_hash=record["rh"]
    )


def _interloper(log: ArrivalLog) -> None:
    """Another writer lands a record, making any pin taken before it stale."""
    log.append_marked_many(
        [
            Entry(
                k="fact",
                body={"id": "01OTHER", "k": "note", "at": 999.0, "p": "{}"},
                observer="kyle",
                origin="",
                at=999.0,
            )
        ],
        following=None,
    )


def test_an_owned_target_mapping_is_not_mutated_across_a_retry(tmp_path: Path):
    """Sol's repro: owned cache + a compare-and-swap interloper.

    Both records must land on the retry, and the caller's mapping must come
    back exactly as it went in. Without the defensive copy this reports
    ``facts_added=0, facts_skipped=2`` after a single append attempt, with
    both source ids left injected in the caller's cache.
    """
    log = ArrivalLog.mint(
        tmp_path / "t.arrival", observer="target-custodian", signer=_sign, key=_KEY
    )
    owned = dict(_ALREADY_HELD)  # THE SAME object is returned every call
    attempts = []
    rederives = []

    def target_state() -> tuple[dict[str, tuple], Head | None]:
        attempts.append(1)
        pin = _head(log)
        if len(attempts) == 1:
            # Between the pin read and the append, so attempt 1 must lose.
            _interloper(log)
        return owned, pin

    result = admit_records(
        log,
        _source(),
        target_state=target_state,
        rederive=lambda: rederives.append(1),
    )

    assert len(attempts) == 2, "the interloper must force exactly one retry"
    assert (result.facts_added, result.facts_skipped) == (2, 0)
    assert rederives == [1]

    landed = {
        record["body"]["id"]
        for record in log.walk()
        if record["k"] == "fact"
    }
    assert {"01SRCA", "01SRCB"} <= landed, "both records must reach the log"

    assert owned == _ALREADY_HELD, (
        "the op dedups against a copy — the caller's mapping is the caller's"
    )
