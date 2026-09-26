"""Isolated process coverage for complete history and vertex sealing."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from engine.arrival import ArrivalLog
from engine.arrival_body import body_of_batch, body_of_fact_row
from sdk import MappedCredentialProvider, init_vertex, sync_target
from sdk.errors import CommittedOutcomeUnknown, CommittedProjectionFailed


@pytest.fixture(autouse=True)
def _isolated_parent_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LOOPS_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))


def _environment(root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "XDG_STATE_HOME": str(root / "state"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "LOOPS_HOME": str(root / "loops"),
        }
    )
    return environment


def _run(
    root: Path, command: str, target: Path, *arguments: str, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loops_min", command, str(target), *arguments],
        capture_output=True,
        input=input_text,
        text=True,
        env=_environment(root),
        check=False,
    )


def _json(process: subprocess.CompletedProcess[str]) -> dict:
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def _history_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("XDG_STATE_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "LOOPS_HOME"):
        monkeypatch.setenv(name, str(tmp_path / name.lower()))
    target = tmp_path / "history.vertex"
    initialized = init_vertex(target, name="history", store_type="arrival", observer="alice")
    log = ArrivalLog(target.parent / str(initialized.store_path))
    packed = [
        (f"packed-{number}", "item", float(number), "alice", "test", json.dumps({"n": number}), None)
        for number in range(55)
    ]
    log.append("batch", body_of_batch(packed), observer="alice", origin="test", at=55.0)
    log.append(
        "fact",
        body_of_fact_row(("separate", "item", 56.0, "alice", "test", '{"n":56}', None)),
        observer="alice",
        origin="test",
        at=56.0,
    )
    log.append(
        "fact",
        body_of_fact_row(("bob-note", "note", 57.0, "bob", "test", '{"n":57}', None)),
        observer="bob",
        origin="test",
        at=57.0,
    )
    sync_target(target)
    return target


def _credentials(root: Path) -> list[str]:
    return [
        "--credential-root", str(root), "--credential-namespace", "tenant",
        "--receipt-observer", "alice",
    ]


def _mapped_target(tmp_path: Path) -> tuple[Path, Path, Path]:
    custody = tmp_path / "custody"
    provider = MappedCredentialProvider(custody, namespace="tenant", receipt_observer="alice")
    provider.create_binding("alice", token="alice")
    target = tmp_path / "seal.vertex"
    ledger = tmp_path / "seal.arrival"
    init_vertex(
        target, name="seal-target", store_type="arrival", location=str(ledger), observer="alice",
        credentials=provider,
    )
    return target, ledger, custody


def _proposal(target: Path, loops: str) -> Path:
    current = target.read_text(encoding="utf-8")
    assert current.endswith("}\n")
    proposal = target.with_name("seal-proposal.vertex")
    proposal.write_text(current[:-2] + loops + "}\n", encoding="utf-8")
    return proposal


def test_facts_all_is_one_complete_process_history_and_default_stays_paged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _history_target(tmp_path, monkeypatch)
    default = _run(tmp_path / "cli", "facts", target, "--order", "oldest")
    assert default.returncode == 0, default.stdout + default.stderr
    page = _json(default)["result"]
    assert len(page["items"]) == 50
    assert page["truncated"] is True

    expected = [*(f"packed-{number}" for number in range(55)), "separate", "bob-note"]
    for order, ids in (("oldest", expected), ("newest", list(reversed(expected)))):
        process = _run(tmp_path / "cli", "facts", target, "--all", "--order", order)
        assert process.returncode == 0, process.stdout + process.stderr
        result = _json(process)["result"]
        assert result["complete"] is True
        assert result["item_count"] == 57
        assert [item["id"] for item in result["items"]] == ids
        assert result["basis"]["captured_head"] == result["basis"]["projected_through"]

    selected = _run(
        tmp_path / "cli", "facts", target, "--all", "--kind", "item", "--observer", "alice",
        "--order", "oldest",
    )
    assert selected.returncode == 0, selected.stdout + selected.stderr
    assert [item["id"] for item in _json(selected)["result"]["items"]] == expected[:-1]
    hidden = _run(tmp_path / "cli", "facts", target, "--all", "--kind", "_decl")
    visible = _run(
        tmp_path / "cli", "facts", target, "--all", "--kind", "_decl", "--include-internal"
    )
    assert _json(hidden)["result"]["items"] == []
    assert _json(visible)["result"]["item_count"] >= 1

    conflict = _run(tmp_path / "cli", "facts", target, "--all", "--limit", "2")
    assert conflict.returncode == 2
    assert _json(conflict)["error"]["type"] == "UsageError"


def test_facts_all_refuses_legacy_and_never_returns_partial_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy = tmp_path / "legacy.vertex"
    legacy.write_text('name "legacy"\nstore "legacy.db"\nloops { }\n', encoding="utf-8")
    refused = _run(tmp_path / "cli", "facts", legacy, "--all")
    assert refused.returncode == 3
    assert _json(refused)["error"]["type"] == "TargetUnsupported"

    cli = importlib.import_module("loops_min.main")

    def broken(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected complete read failure")

    monkeypatch.setattr(cli, "read_all_facts", broken)
    assert cli.main(["facts", str(legacy), "--all"]) == 70
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is False
    assert result["error"]["message"] == "injected complete read failure"


def test_seal_process_requires_boundary_and_reports_own_vertex_tick(
    tmp_path: Path,
) -> None:
    target, ledger, custody = _mapped_target(tmp_path)
    before = ledger.read_bytes()
    no_boundary = _run(
        tmp_path / "cli", "seal", target, "--payload-json", "{}", "--observer", "alice",
        *_credentials(custody),
    )
    assert no_boundary.returncode == 4
    assert ledger.read_bytes() == before

    proposal = _proposal(target, '  boundary when="seal" status="closed"\n')
    declared = _run(
        tmp_path / "cli", "declaration", target, "--proposed-file", str(proposal),
        "--observer", "alice", *_credentials(custody),
    )
    assert declared.returncode == 0, declared.stdout + declared.stderr
    payload = tmp_path / "seal.json"
    payload.write_text("{}", encoding="utf-8")
    sealed = _run(
        tmp_path / "cli", "seal", target, "--payload-file", str(payload), "--observer", "alice",
        "--id", "seal-file", *_credentials(custody),
    )
    assert sealed.returncode == 0, sealed.stdout + sealed.stderr
    receipt = _json(sealed)["result"]
    assert receipt["sealed"] is True
    assert receipt["vertex_name"] == "seal-target"
    assert receipt["receipt"]["tick_mark"] == "seal-target"
    assert receipt["boundary_match"] == {"status": "closed"}

    invalid_stdin = _run(
        tmp_path / "cli", "seal", target, "--payload-file", "-", "--observer", "alice",
        *_credentials(custody), input_text="[]",
    )
    assert invalid_stdin.returncode == 2
    conflict = _run(
        tmp_path / "cli", "seal", target, "--payload-json", "{}", "--payload-file", str(payload),
        "--observer", "alice", *_credentials(custody),
    )
    assert conflict.returncode == 2


def test_seal_process_can_commit_without_sealing_when_condition_is_false(tmp_path: Path) -> None:
    target, _ledger, custody = _mapped_target(tmp_path)
    proposal = _proposal(
        target,
        '  seal { fold { count "inc" } }\n'
        '  boundary when="seal" { condition "count" ">=" 2 }\n',
    )
    declared = _run(
        tmp_path / "cli", "declaration", target, "--proposed-file", str(proposal),
        "--observer", "alice", *_credentials(custody),
    )
    assert declared.returncode == 0, declared.stdout + declared.stderr
    first = _run(
        tmp_path / "cli", "seal", target, "--payload-json", "{}", "--observer", "alice",
        *_credentials(custody),
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_result = _json(first)["result"]
    assert first_result["receipt"]["stored"] is True
    assert first_result["sealed"] is False
    assert first_result["receipt"]["tick_id"] is None

    second = _run(
        tmp_path / "cli", "seal", target, "--payload-json", "{}", "--observer", "alice",
        *_credentials(custody),
    )
    assert second.returncode == 0, second.stdout + second.stderr
    second_result = _json(second)["result"]
    assert second_result["receipt"]["stored"] is True
    assert second_result["sealed"] is True
    assert second_result["receipt"]["tick_mark"] == "seal-target"
    assert second_result["receipt"]["tick_id"] is not None


@pytest.mark.parametrize(
    ("error_type", "outcome"),
    [
        (CommittedOutcomeUnknown, "unknown"),
        (CommittedProjectionFailed, "committed-projection-failed"),
    ],
)
def test_seal_preserves_commit_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error_type: type[BaseException],
    outcome: str,
) -> None:
    cli = importlib.import_module("loops_min.main")

    target, _ledger, custody = _mapped_target(tmp_path)
    head = {"lineage": "L", "ordinal": 4, "record_hash": "H"}
    error = error_type(
        "reconcile seal", source_type="InjectedSeal", details={"fact_id": "seal-1", "captured_head": head}
    )
    monkeypatch.setattr(cli, "seal_fact", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))
    assert cli.main([
        "seal", str(target), "--payload-json", "{}", "--observer", "alice", *_credentials(custody),
    ]) == 6
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["outcome"] == outcome
    assert result["error"]["details"]["fact_id"] == "seal-1"
    assert result["error"]["details"]["captured_head"] == head
