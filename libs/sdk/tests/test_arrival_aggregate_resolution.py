"""Aggregate-aware Arrival reads retain their first parsed root descriptor."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from engine.admission import fact_commitment_hash
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_fact_row
from lang import genesis_payload, parse_vertex_file

import sdk.target as sdk_target
from sdk import read_state, read_summary, read_timeline, sync_target


def _sign(_observer: str, commitment: str) -> str:
    return "test-signature:" + commitment


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every registry witness and file adapter under this fixture."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def _fact_body(
    identifier: str, kind: str, ts: float, payload: str, *, observer: str = "alice"
) -> dict[str, object]:
    return body_of_fact_row(
        (
            identifier,
            kind,
            ts,
            observer,
            "fixture",
            payload,
            _sign(observer, fact_commitment_hash(kind, ts, observer, "fixture", payload)),
        )
    )


def _root_with_adopted_plain_history(tmp_path: Path) -> tuple[Path, ArrivalLog]:
    """Build a plain adopted root, then make only its local cache aggregate."""
    log = ArrivalLog.mint(
        tmp_path / "original.arrival",
        observer="physical-custodian",
        signer=_sign,
        key=base64.b64encode(b"k" * 32).decode(),
        at=1.0,
    )
    root = tmp_path / "root.vertex"
    root.write_text(
        f'name "original"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'loops { note { fold { n "count" } } }\n',
        encoding="utf-8",
    )
    declaration = json.dumps(genesis_payload(parse_vertex_file(root)))
    log.append(
        "fact",
        _fact_body(
            log.lineage(),
            "_decl.genesis",
            2.0,
            declaration,
            observer="physical-custodian",
        ),
        observer="physical-custodian",
        origin="fixture",
        at=2.0,
        signer=_sign,
    )
    log.append(
        "fact",
        _fact_body("original-note", "note", 3.0, json.dumps({"value": "original"})),
        observer="alice",
        origin="fixture",
        at=3.0,
        signer=_sign,
    )
    sync_target(root)
    root.write_text(
        f'name "original"\nstore "{log.path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'discover "*.member.vertex"\n',
        encoding="utf-8",
    )
    return root, log


@pytest.mark.parametrize(
    ("operation", "assert_original"),
    [
        (
            read_summary,
            lambda result: (
                result.fact_total == 1 and result.unfolded_kinds == []
            ),
        ),
        (
            read_state,
            lambda result: result.sections["note"]["n"] == 1,
        ),
        (
            read_timeline,
            lambda result: [event.id for event in result.events] == ["original-note"],
        ),
    ],
)
def test_aggregate_aware_reads_keep_original_parsed_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: Callable[[Path], object],
    assert_original: Callable[[object], bool],
) -> None:
    """Replacing the locator after initial parsing cannot redirect this read."""
    root, log = _root_with_adopted_plain_history(tmp_path)
    original_parse = sdk_target.parse_vertex_file
    calls = 0

    def replace_after_parse(path: Path):
        nonlocal calls
        calls += 1
        ast = original_parse(path)
        root.write_text(
            'name "replacement"\n'
            'store "missing.arrival" backend="file" '
            'lineage="replacement" role="authority"\n'
            'discover "replacement/*.vertex"\n',
            encoding="utf-8",
        )
        return ast

    monkeypatch.setattr(sdk_target, "parse_vertex_file", replace_after_parse)

    result = operation(root)

    assert calls == 1
    assert result.read_path == "arrival"
    assert result.store is not None and result.store.location == str(log.path)
    assert result.basis is not None
    assert result.basis.captured_head.lineage == log.lineage()
    assert assert_original(result)
