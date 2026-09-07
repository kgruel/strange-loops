"""Narrow process-boundary regressions for the mapped writer commands."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from sdk import MappedCredentialProvider, init_vertex

cli = importlib.import_module("loops_min.main")


@pytest.fixture(autouse=True)
def _isolated_process_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops-home"))


def _credentials(root: Path) -> list[str]:
    return [
        "--credential-root",
        str(root),
        "--credential-namespace",
        "tenant",
        "--receipt-observer",
        "alice",
    ]


@pytest.mark.parametrize(
    "transport",
    [
        ("--payload-json", '{"a":1,"a":2}'),
        ("--payload-json", '{"a":NaN}'),
        ("--payload-json", '{"a":1e999}'),
        ("--ts", "nan"),
        ("--ts", "inf"),
    ],
)
def test_invalid_numeric_or_duplicate_transport_stops_before_sdk_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    transport: tuple[str, str],
) -> None:
    reached: list[str] = []

    def resolver(*_args: Any, **_kwargs: Any) -> None:
        reached.append("resolve")

    def writer(*_args: Any, **_kwargs: Any) -> None:
        reached.append("write")

    monkeypatch.setattr(cli, "resolve_arrival_target", resolver)
    monkeypatch.setattr(cli, "emit_fact", writer)
    arguments = [
        "emit",
        str(tmp_path / "unused.vertex"),
        "item",
        "--payload-json",
        "{}",
        "--observer",
        "alice",
        *_credentials(tmp_path / "custody"),
    ]
    option, value = transport
    if option == "--payload-json":
        arguments[arguments.index(option) + 1] = value
    else:
        arguments.extend((option, value))

    assert cli.main(arguments) == cli.EXIT_USAGE
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["error"]["type"] == "UsageError"
    assert reached == []
    assert not (tmp_path / "custody").exists()


def test_declaration_recovery_passes_only_intent_and_serializes_sdk_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    intent = tmp_path / "pending.intent"
    expected = {
        "schema": "loops.sdk/declaration-edit/v2",
        "status": "recovered",
        "intent_path": str(intent),
        "commit": None,
    }
    calls: list[str] = []

    class Result:
        def as_dict(self) -> dict[str, Any]:
            return expected

    def recover(value: str) -> Result:
        calls.append(value)
        return Result()

    monkeypatch.setattr(cli, "recover_declaration", recover)
    assert cli.main(["declaration-recover", str(intent)]) == cli.EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": True, "result": expected}
    assert calls == [str(intent)]


def test_descriptor_swap_to_legacy_cannot_downgrade_mapped_emit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    custody = tmp_path / "custody"
    provider = MappedCredentialProvider(
        custody, namespace="tenant", receipt_observer="alice"
    )
    provider.create_binding("alice", token="create-alice")
    target = tmp_path / "arrival.vertex"
    ledger = (tmp_path / "arrival.arrival").resolve()
    init_vertex(
        target,
        name="arrival",
        store_type="arrival",
        location=ledger,
        observer="alice",
        credentials=provider,
    )
    ledger_before = ledger.read_bytes()
    original_resolver = cli.resolve_arrival_target

    def resolve_then_replace(value: str) -> Any:
        resolved = original_resolver(value)
        target.write_text('name "legacy"\nstore "legacy.db"\n', encoding="utf-8")
        return resolved

    monkeypatch.setattr(cli, "resolve_arrival_target", resolve_then_replace)
    result = cli.main(
        [
            "emit",
            str(target),
            "item",
            "--payload-json",
            '{"must":"refuse"}',
            "--observer",
            "alice",
            *_credentials(custody),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == cli.EXIT_UNSUPPORTED
    assert output["ok"] is False
    assert output["error"]["type"] == "TargetUnsupported"
    assert ledger.read_bytes() == ledger_before
    assert not (tmp_path / "legacy.db").exists()
