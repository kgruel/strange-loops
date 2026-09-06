"""Runtime boundary consumption at the Arrival capture/write seam.

These tests exercise the public source-mode path: capture a closed
CURRENT snapshot, plan pending boundary records, append the exact batch,
sync the projection, and capture again.  Boundary event time is deliberately
separate from witness order here; a later fact may have the same event time
as an already recorded boundary.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from engine.arrival_body import body_of_tick_row
from engine.arrival_contract import ProjectionRequirement, RecordDraft, TickRequest
from engine.handle import WriteCredentials
from engine.loop import Loop
from engine.row_commitment import tick_commitment_hash, tick_row_hash
from engine.runtime_write import (
    capture_runtime,
    execute_batch_write,
    plan_batch_from_capture,
)
from engine.vertex import Vertex
from tests.test_runtime_batch_write import _make_target
from tests.test_runtime_capture import _append_fact, _sync


def _tick_credentials(signer) -> WriteCredentials:
    return WriteCredentials(tick_signer=lambda digest: signer("kyle", digest))


@pytest.mark.parametrize("timestamp", [4.0000004, 4.0000006])
def test_tick_datetime_rounding_does_not_reemit_or_hide_same_time_late_fact(
    tmp_path, monkeypatch, keys, signer, timestamp
):
    target = _make_target(
        tmp_path, monkeypatch, keys, signer, extra_loops='  boundary when="seal"\n'
    )
    _append_fact(target, "first", "seal", timestamp, signer, {"status": "first"})
    _sync(target)
    capture = capture_runtime(
        target.registry, target.descriptor, target.locator,
        source_mode=True, evaluated_at=5.0,
    )
    plan = plan_batch_from_capture(
        capture, (), credentials=_tick_credentials(signer), include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)
    recorded = capture_runtime(
        target.registry, target.descriptor, target.locator,
        source_mode=True, evaluated_at=5.0,
    )
    assert recorded.pending_boundaries == ()
    _append_fact(target, "second", "seal", timestamp, signer, {"status": "second"})
    _sync(target)
    later = capture_runtime(
        target.registry, target.descriptor, target.locator,
        source_mode=True, evaluated_at=5.0,
    )
    assert len(later.pending_boundaries) == 1
    assert later.pending_boundaries[0].payload["_boundary"] == {"status": "second"}


def test_vertex_boundary_is_consumed_after_public_pending_batch_round_trip(
    tmp_path, monkeypatch, keys, signer
):
    """A committed vertex close must not be offered again unchanged.

    This is the source-mode equivalent of ``evaluate_boundaries``'s second
    evaluation invariant.  The triggering ``seal`` remains at the boundary
    timestamp, so a timestamp-only scan can accidentally plan the same close
    tick forever.
    """
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal"\n',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "closed"})
    _sync(target)

    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert [tick.name for tick in capture.pending_boundaries] == ["batch-target"]

    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)

    recapture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recapture.pending_boundaries == ()


def test_vertex_boundary_same_timestamp_late_arrival_is_a_new_trigger(
    tmp_path, monkeypatch, keys, signer
):
    """A later same-time boundary fact remains independently eligible.

    Arrival order is the witness tie-break when event timestamps are equal.
    After the first close is committed, a second ``seal`` appended later at
    the same timestamp must be observed as a new trigger, with its own
    payload, rather than being discarded by a strict event-time cutoff.
    """
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal"\n',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _sync(target)

    first_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    first_plan = plan_batch_from_capture(
        first_capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, first_plan)
    _sync(target)

    recorded = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recorded.ticks[-1].fact_cursor == "seal-one"

    _append_fact(target, "seal-two", "seal", 4.0, signer, {"status": "second"})
    _sync(target)
    second_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )

    assert len(second_capture.pending_boundaries) == 1
    assert second_capture.pending_boundaries[0].payload["_boundary"] == {
        "status": "second"
    }


def test_loop_boundary_does_not_reconsume_equal_timestamp_edge(
    tmp_path, monkeypatch, keys, signer
):
    """Loop boundaries retain the established strict post-tick time window."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"\n',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "closed"})
    _sync(target)

    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)

    recapture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recapture.pending_boundaries == ()


def test_loop_boundary_same_timestamp_late_arrival_is_a_new_trigger(
    tmp_path, monkeypatch, keys, signer
):
    """A loop boundary also distinguishes later receipt at the same time."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"\n',
    )
    _append_fact(target, "note-one", "note", 3.0, signer, {"value": "one"})
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _sync(target)

    first_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    first_plan = plan_batch_from_capture(
        first_capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, first_plan)
    _sync(target)

    _append_fact(target, "seal-two", "seal", 4.0, signer, {"status": "second"})
    _sync(target)
    recapture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )

    assert len(recapture.pending_boundaries) == 1
    assert recapture.pending_boundaries[0].payload["_boundary"] == {
        "status": "second"
    }


def test_vertex_boundary_covers_equal_timestamp_facts_in_one_captured_period(
    tmp_path, monkeypatch, keys, signer
):
    """Facts already present at a closing timestamp belong to one period."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal"\n',
    )
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _append_fact(target, "seal-two", "seal", 4.0, signer, {"status": "second"})
    _sync(target)

    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert len(capture.pending_boundaries) == 1
    assert capture.pending_boundaries[0].payload["_boundary"] == {
        "status": "first"
    }
    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)

    recapture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recapture.pending_boundaries == ()


def test_future_vertex_boundary_is_not_consumed_by_prior_tick_cursor(
    tmp_path, monkeypatch, keys, signer
):
    """A future event present at capture remains eligible at its event time."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal"\n',
    )
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _append_fact(target, "seal-future", "seal", 10.0, signer, {"status": "future"})
    _sync(target)

    first_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    first_plan = plan_batch_from_capture(
        first_capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, first_plan)
    _sync(target)

    recorded = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recorded.ticks[-1].fact_cursor == "seal-future"

    later = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=11.0,
    )
    assert len(later.pending_boundaries) == 1
    assert later.pending_boundaries[0].payload["_boundary"] == {
        "status": "future"
    }


def test_late_earlier_vertex_boundary_does_not_reopen_closed_period(
    tmp_path, monkeypatch, keys, signer
):
    """An event earlier than the vertex closing edge is not replayed."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal"\n',
    )
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)

    _append_fact(target, "seal-late", "seal", 3.0, signer, {"status": "late"})
    _sync(target)
    recapture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    assert recapture.pending_boundaries == ()


def test_independent_loop_tick_does_not_close_vertex_period(
    tmp_path, monkeypatch, keys, signer
):
    """A loop's edge does not become the vertex boundary's closing edge."""
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops=(
            '  boundary when="seal"\n'
            "  audit {\n"
            '    fold { items "collect" 20 }\n'
            '    boundary when="close"\n'
            "  }\n"
        ),
    )
    _append_fact(target, "close-one", "close", 5.0, signer)
    _sync(target)
    loop_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=6.0,
    )
    loop_plan = plan_batch_from_capture(
        loop_capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    assert [tick.name for tick in loop_capture.pending_boundaries] == ["audit"]
    execute_batch_write(target.registry, target.descriptor, loop_plan)
    _sync(target)

    _append_fact(target, "seal-late", "seal", 4.0, signer)
    _sync(target)
    vertex_capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=6.0,
    )
    assert [tick.name for tick in vertex_capture.pending_boundaries] == ["batch-target"]


def test_same_name_foreign_tick_does_not_consume_local_vertex_boundary(
    tmp_path, monkeypatch, keys, signer
):
    """A tick from another vertex cannot close this vertex's period.

    This follows the supported capture/append/sync path.  Both vertices use
    the same tick name (``note``), which is the collision that a name-only
    edge map incorrectly treats as a local close.
    """
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        boundary='boundary when="seal"\n',
    )
    _append_fact(target, "seal-one", "seal", 4.0, signer, {"status": "first"})
    _sync(target)
    capture = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=5.0,
    )
    plan = plan_batch_from_capture(
        capture,
        (),
        credentials=_tick_credentials(signer),
        include_pending_boundaries=True,
    )
    execute_batch_write(target.registry, target.descriptor, plan)
    _sync(target)

    ledger, query = target.registry.open(target.descriptor)
    snapshot = query.open_snapshot(
        captured_head=ledger.head(), requirement=ProjectionRequirement.CURRENT
    )
    ticks = snapshot.ticks(TickRequest())
    snapshot.close()
    query.close()
    previous = ticks[-1]
    previous_hash = tick_row_hash(
        (
            previous.id,
            previous.name,
            previous.ts,
            previous.since,
            previous.origin,
            previous.payload_text,
            previous.prev_hash,
            previous.window_start,
            previous.fact_cursor,
            previous.window_hash,
            previous.signature,
        )
    )
    row = (
        "foreign-tick",
        "note",
        10.0,
        None,
        "other",
        "{}",
        previous_hash,
        previous.fact_cursor,
        previous.fact_cursor,
        hashlib.sha256().hexdigest(),
        None,
    )
    body = body_of_tick_row(
        (*row[:-1], signer("kyle", tick_commitment_hash(row)))
    )
    ledger, query = target.registry.open(target.descriptor)
    ledger.append(
        ledger.head(),
        [RecordDraft("tick", 10.0, "kyle", body=body, signature=None)],
    )
    query.close()
    ledger.close()

    _append_fact(target, "seal-late", "seal", 5.0, signer, {"status": "late"})
    _sync(target)
    recaptured = capture_runtime(
        target.registry,
        target.descriptor,
        target.locator,
        source_mode=True,
        evaluated_at=6.0,
    )
    assert len(recaptured.pending_boundaries) == 1
    assert recaptured.pending_boundaries[0].payload["_boundary"] == {
        "status": "late"
    }


@pytest.mark.parametrize("origin", ["other", "", None])
@pytest.mark.parametrize("vertex_name", ["v", ""])
def test_hydration_ignores_foreign_or_originless_same_name_ticks(origin, vertex_name):
    """Hydration requires explicit local origin for loop and vertex resets."""
    vertex = Vertex(vertex_name)
    vertex.register_loop(
        Loop(
            name="note",
            initial={"count": 0},
            fold=lambda state, _payload: {"count": state["count"] + 1},
            boundary_kind="close",
        )
    )
    vertex.register_vertex_boundary("seal")
    facts = (
        SimpleNamespace(
            kind="note",
            payload={"value": "one"},
            ts=1.0,
            arrival_ordinal=1,
            arrival_seq=0,
        ),
    )
    ticks = (
        SimpleNamespace(
            id="foreign-loop",
            name="note",
            ts=2.0,
            origin=origin,
            arrival_ordinal=2,
            arrival_seq=0,
        ),
        SimpleNamespace(
            id="foreign-vertex",
            name=vertex_name,
            ts=3.0,
            origin=origin,
            arrival_ordinal=3,
            arrival_seq=0,
        ),
    )

    vertex.hydrate_snapshot(facts, ticks)

    assert vertex.state("note") == {"count": 1}
    assert vertex._vertex_period_start is None
