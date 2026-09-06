"""Descriptor-first Full custody verification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from engine.arrival_contract import Full, Head
from engine.arrival_file_backend import FileLedger
from engine.arrival_head_seam import AttestedLedger
from engine.arrival_registry import BackendRegistry
from engine.residence import index_path_for

from sdk import init_vertex, verify_target
from sdk.errors import ArrivalRefusal
from sdk.target import _arrival_descriptor


def _target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, ArrivalLog]:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    vertex = tmp_path / "kyle.vertex"
    initialized = init_vertex(vertex, store_type="arrival", observer="kyle")
    return vertex, ArrivalLog(vertex.parent / str(initialized.store_path))


@pytest.mark.parametrize("projection", ["missing", "behind"])
def test_verify_target_fully_verifies_initialized_prefix_without_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, projection: str
) -> None:
    vertex, log = _target(tmp_path, monkeypatch)
    index = index_path_for(log.path)
    if projection == "missing":
        index.unlink()
    else:
        log.append(
            "fact",
            body_of_fact_row(
                ("unprojected", "item", 3.0, "kyle", "test", json.dumps({"id": "u"}), None)
            ),
            observer="kyle",
            origin="test",
            at=3.0,
        )
    before = log.path.read_bytes()
    index_before = None if projection == "missing" else index.read_bytes()

    result = verify_target(vertex)

    assert result.store is not None and result.store.backend == "file"
    assert result.captured_head == result.verified_through
    assert result.level == "full"
    assert result.claims == ("grammar", "density", "lineage", "hash-chain")
    assert "signature-authorship" in result.excludes
    assert "projection" in result.excludes
    assert log.path.read_bytes() == before
    if projection == "missing":
        assert not index.exists()
    else:
        assert index.read_bytes() == index_before
    json.dumps(result.as_dict(), allow_nan=False)


def test_verify_target_refuses_an_incorrect_explicit_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, _log = _target(tmp_path, monkeypatch)
    captured = verify_target(vertex).captured_head
    assert captured is not None
    forged = Head(captured.lineage, captured.ordinal, "0" * 64)

    with pytest.raises(ArrivalRefusal) as raised:
        verify_target(vertex, through=forged)
    assert raised.value.source_type == "HeadMismatch"


def test_verify_target_stays_at_captured_prefix_after_later_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vertex, log = _target(tmp_path, monkeypatch)
    original_verify = AttestedLedger.verify
    captured: list[Head] = []
    injected = False

    def append_before_full(ledger: AttestedLedger, scope):
        nonlocal injected
        if isinstance(scope, Full) and not injected:
            injected = True
            captured.append(scope.through)
            log.append(
                "fact",
                body_of_fact_row(
                    ("later", "item", 3.0, "kyle", "test", json.dumps({"id": "later"}), None)
                ),
                observer="kyle",
                origin="test",
                at=3.0,
            )
        return original_verify(ledger, scope)

    monkeypatch.setattr(AttestedLedger, "verify", append_before_full)

    result = verify_target(vertex)

    assert injected and captured == [result.captured_head]
    assert result.verified_through == result.captured_head
    assert log.head()["ord"] > result.captured_head.ordinal



def test_verify_target_explicit_prefix_is_bounded_by_its_open_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An append after compare cannot become an explicit verification target."""
    vertex, log = _target(tmp_path, monkeypatch)
    resolved = _arrival_descriptor(vertex)
    assert resolved is not None
    _path, _ast, descriptor = resolved
    base = BackendRegistry.with_builtin_backends()
    captured_ledger, captured_query = base.open(descriptor)
    captured = captured_ledger.opened.comparison.presented
    log.append(
        "fact",
        body_of_fact_row(("future", "item", 3.0, "kyle", "test", json.dumps({}), None)),
        observer="kyle",
        origin="test",
        at=3.0,
    )
    future = FileLedger(log).head()

    class CapturedRegistry:
        def open(self, _descriptor):
            return captured_ledger, captured_query

    with pytest.raises(ArrivalRefusal) as raised:
        verify_target(vertex, through=future, registry=CapturedRegistry())
    assert raised.value.source_type == "HeadMismatch"
    assert raised.value.details["source_type"] == "HeadMismatch"

    # A new open may attest the later head, but can still verify the known
    # earlier prefix and report the distinction explicitly.
    older = verify_target(vertex, through=captured)
    assert older.captured_head == future
    assert older.verified_through == captured
