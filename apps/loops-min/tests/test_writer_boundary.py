"""Narrow process-boundary regressions for the mapped writer commands."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
from sdk import CredentialBindingIncomplete, MappedCredentialProvider, init_vertex

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


def test_initialization_recovery_uses_only_target_and_reserved_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "interrupted.vertex"
    expected = {"schema": "loops.sdk/init-vertex/v2", "phase": "published"}
    calls: list[tuple[str, dict[str, Any]]] = []

    class Result:
        def as_dict(self) -> dict[str, Any]:
            return expected

    def recover(value: str, **kwargs: Any) -> Result:
        calls.append((value, kwargs))
        return Result()

    monkeypatch.setattr(cli, "init_vertex", recover)
    assert cli.main(["init-recover", str(target)]) == cli.EXIT_OK
    output = json.loads(capsys.readouterr().out)
    assert output == {"ok": True, "result": expected}
    assert calls == [(str(target), {"store_type": "arrival", "recover": True})]


@pytest.mark.parametrize(
    ("command", "extra", "expected_call"),
    [
        ("credential-create", (), ("create", "alice", "operation-token")),
        ("credential-recover", (), ("recover", "alice", "operation-token")),
        (
            "credential-bind-existing-ref",
            ("--key-ref", "key-1", "--expected-public-key", "public-1"),
            ("bind", "alice", "key-1", "public-1", "operation-token"),
        ),
        (
            "credential-import-legacy",
            ("--vertex", "old.vertex"),
            ("import", "old.vertex", "alice", "operation-token"),
        ),
    ],
)
def test_binding_commands_delegate_to_sdk_and_preserve_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    extra: tuple[str, ...],
    expected_call: tuple[str, ...],
) -> None:
    root = tmp_path / "custody"
    expected = {
        "schema": "loops.sdk/credential-binding/v1",
        "operation": expected_call[0],
        "namespace": "tenant",
        "observer": "alice",
        "token": "operation-token",
        "key_ref": "opaque-ref",
        "public_key": "public-key",
    }
    constructed: list[tuple[str, str, object]] = []
    calls: list[tuple[str, ...]] = []

    class Result:
        def as_dict(self) -> dict[str, Any]:
            return expected

    class Provider:
        def create_binding(self, observer: str, *, token: str) -> Result:
            calls.append(("create", observer, token))
            return Result()

        def recover_binding(self, observer: str, *, token: str) -> Result:
            calls.append(("recover", observer, token))
            return Result()

        def bind_existing_ref(
            self, observer: str, key_ref: str, public_key: str, *, token: str
        ) -> Result:
            calls.append(("bind", observer, key_ref, public_key, token))
            return Result()

        def import_legacy(
            self, vertex: str, observer: str, *, token: str
        ) -> Result:
            calls.append(("import", vertex, observer, token))
            return Result()

    def provider(value: str, *, namespace: str, receipt_observer: object = None) -> Provider:
        constructed.append((value, namespace, receipt_observer))
        return Provider()

    monkeypatch.setattr(cli, "MappedCredentialProvider", provider)
    result = cli.main(
        [
            command,
            str(root),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
            "--token",
            "operation-token",
            *extra,
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == cli.EXIT_OK
    assert output == {"ok": True, "result": expected}
    assert constructed == [(str(root), "tenant", None)]
    assert calls == [expected_call]


def test_missing_binding_argument_stops_before_provider_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reached: list[str] = []

    def provider(*_args: Any, **_kwargs: Any) -> None:
        reached.append("provider")

    monkeypatch.setattr(cli, "MappedCredentialProvider", provider)
    result = cli.main(
        [
            "credential-create",
            str(tmp_path / "custody"),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == cli.EXIT_USAGE
    assert output["error"]["type"] == "UsageError"
    assert reached == []


def test_incomplete_binding_outcome_retains_reconciliation_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    error = CredentialBindingIncomplete(
        "binding publication outcome is incomplete",
        operation="create",
        namespace="tenant",
        observer="alice",
        token="operation-token",
        key_ref="opaque-ref",
        phase="binding-published",
        source_type="BindingMutationIncomplete",
    )

    class Provider:
        def create_binding(self, _observer: str, *, token: str) -> None:
            assert token == "operation-token"
            raise error

    monkeypatch.setattr(cli, "_binding_provider", lambda _args: Provider())
    result = cli.main(
        [
            "credential-create",
            str(tmp_path / "custody"),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
            "--token",
            "operation-token",
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert result == cli.EXIT_COMMITTED
    assert output["error"]["outcome"] == "incomplete"
    assert output["error"]["source_type"] == "BindingMutationIncomplete"
    assert output["error"]["phase"] == "binding-published"
    assert output["error"]["recovery_action"] == "reconcile"
    assert "commit" not in output["error"]


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
