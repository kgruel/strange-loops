"""Captured vertex-boundary preparation stays on the ordinary Arrival CAS path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from atoms import Fact

from engine.arrival_contract import FactPage
from engine.arrival_file_backend import FileQuery
from engine.handle import WriteCredentials
from engine.runtime_write import (
    BatchFactInput,
    RuntimeWriteRefused,
    capture_runtime,
    execute_ordinary_write,
    plan_batch_from_capture,
    prepare_boundary_write,
)
from tests.test_runtime_batch_write import _make_target


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LOOPS_HOME"
    ):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


def test_prepare_boundary_write_merges_captured_match_and_fires_vertex_tick(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal" status="closed"\n',
    )
    plan = prepare_boundary_write(
        target.registry,
        target.descriptor,
        target.locator,
        Fact("seal", 3.0, {}, observer="kyle"),
        credentials=WriteCredentials(),
        fact_id="seal-one",
    )

    fact = next(draft.body for draft in plan.drafts if draft.kind == "fact")
    tick = next(draft.body for draft in plan.drafts if draft.kind == "tick")
    assert json.loads(fact["payload"]) == {"status": "closed"}
    assert plan.boundary_match == (("status", "closed"),)
    assert tick["name"] == "batch-target"
    outcome = execute_ordinary_write(target.registry, target.descriptor, plan)
    assert outcome.fact_id == "seal-one"
    assert outcome.tick_id == plan.tick_id


def test_prepare_boundary_write_refuses_conflicting_match_before_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops='  boundary when="seal" status="closed"\n',
    )
    before = target.log.path.read_bytes()

    with pytest.raises(RuntimeWriteRefused, match="conflicts"):
        prepare_boundary_write(
            target.registry,
            target.descriptor,
            target.locator,
            Fact("seal", 3.0, {"status": "open"}, observer="kyle"),
            credentials=WriteCredentials(),
        )

    assert target.log.path.read_bytes() == before


def test_prepare_boundary_write_refuses_missing_captured_boundary_before_append(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    before = target.log.path.read_bytes()

    with pytest.raises(RuntimeWriteRefused, match="no boundary"):
        prepare_boundary_write(
            target.registry,
            target.descriptor,
            target.locator,
            Fact("seal", 3.0, {}, observer="kyle"),
            credentials=WriteCredentials(),
        )

    assert target.log.path.read_bytes() == before


def test_capture_runtime_refuses_truncated_unbounded_fact_evidence(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(tmp_path, monkeypatch, keys, signer)
    before = target.log.path.read_bytes()
    original = FileQuery.open_snapshot

    class TruncatedSnapshot:
        def __init__(self, snapshot):
            self._snapshot = snapshot

        def facts(self, request):
            page = self._snapshot.facts(request)
            if request.limit is None:
                return FactPage(page.items, page.cursor, True, page.order)
            return page

        def __getattr__(self, name):
            return getattr(self._snapshot, name)

    def open_truncated(self, *args, **kwargs):
        return TruncatedSnapshot(original(self, *args, **kwargs))

    monkeypatch.setattr(FileQuery, "open_snapshot", open_truncated)
    with pytest.raises(RuntimeWriteRefused, match="complete receipt-ordered fact evidence"):
        capture_runtime(target.registry, target.descriptor, target.locator)
    assert target.log.path.read_bytes() == before


def test_frozen_conditions_are_isolated_for_ordinary_and_batch_planning(
    tmp_path, monkeypatch, keys, signer
):
    target = _make_target(
        tmp_path,
        monkeypatch,
        keys,
        signer,
        extra_loops=(
            '  seal { fold { count "inc" } }\n'
            '  boundary when="seal" { condition "count" ">=" 2 }\n'
        ),
    )
    capture = capture_runtime(target.registry, target.descriptor, target.locator)
    first = prepare_boundary_write(
        target.registry,
        target.descriptor,
        target.locator,
        Fact("seal", 3.0, {}, observer="kyle"),
        credentials=WriteCredentials(),
        fact_id="ordinary-first",
    )
    batch = plan_batch_from_capture(
        capture,
        (
            BatchFactInput(Fact("seal", 3.0, {}, observer="kyle"), fact_id="batch-one"),
            BatchFactInput(Fact("seal", 4.0, {}, observer="kyle"), fact_id="batch-two"),
        ),
        credentials=WriteCredentials(),
    )

    assert first.tick_id is None
    assert [draft.kind for draft in batch.drafts] == ["batch", "tick"]
    assert batch.items[0].tick_id is None
    assert batch.items[1].tick_name == "batch-target"
