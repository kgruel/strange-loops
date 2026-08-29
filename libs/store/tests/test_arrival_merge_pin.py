"""The merge's compare-and-swap pin, where completing it can fail.

F1 (``design:arrival-break-slice2-backend-contract`` SD-2) widened the append
pin from an ordinal to a full head. The merge target's resume mark carries no
record hash, so ``store.merge._pinned_head`` completes the pin by reading the
record the mark names — and that read can come back empty, when the index's
recorded position is one the log will not confirm.

There is a fork there that no type signature shows: refuse, or quietly pass
``following=None``. The second is a silent downgrade to an UNPINNED append,
which is the weakening F1 exists to prevent, and it would hide in a green
suite because an unpinned append succeeds. Hence this file. Separate from
``test_arrival_merge.py`` because that file is one of the fourteen the slice-2
brief holds unmodified.
"""

from __future__ import annotations

import pytest
from engine.arrival import ArrivalLog, ResumeMark

from store.merge import _pinned_head
from tests.conftest import STUB_KEY, stub_sign


@pytest.fixture
def log(tmp_path) -> ArrivalLog:
    return ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=stub_sign, key=STUB_KEY
    )


def test_an_unanchorable_mark_refuses_rather_than_unpinning_the_append(log):
    """A mark the log will not vouch for stops the merge.

    The offset lands mid-record rather than on a boundary, so no record ends
    there and the anchor is rejected — the shape a real index/log
    disagreement takes. Appending onto that disagreement under a pin the
    caller could not complete is what this refusal prevents.
    """
    unanchorable = ResumeMark(
        arrival_lineage=log.lineage(), arrival_offset=3, arrival_ordinal=0
    )
    with pytest.raises(RuntimeError, match="does not vouch"):
        _pinned_head(log, unanchorable)


def test_no_mark_is_still_no_pin(log):
    """The refusal must not over-fire — scope the claim.

    An index with no mark has nothing to be stale about, and F1 refuses a
    WEAKER pin rather than the absence of one. If this returned a refusal
    too, a first merge into an unmarked target would be impossible.
    """
    assert _pinned_head(log, None) is None


def test_a_vouched_mark_completes_into_the_full_head(log):
    """The positive case, so the two above cannot pass by refusing always."""
    record = log.append("note", {"i": 1}, observer="kyle")
    mark = ResumeMark(
        arrival_lineage=log.lineage(),
        arrival_offset=log.path.stat().st_size,
        arrival_ordinal=record["ord"],
    )
    head = _pinned_head(log, mark)
    assert head is not None
    assert (head.lineage, head.ordinal, head.record_hash) == (
        record["lin"], record["ord"], record["rh"],
    )
