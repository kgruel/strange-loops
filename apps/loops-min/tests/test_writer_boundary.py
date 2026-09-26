"""Narrow process-boundary regressions for the mapped writer commands."""

from __future__ import annotations

import importlib
import io
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
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
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


def test_transport_file_and_stdin_preserve_unicode_and_multiline_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: list[dict[str, Any]] = []

    class Result:
        def as_dict(self) -> dict[str, Any]:
            return {"ok": "sdk"}

    def writer(*_args: Any, **kwargs: Any) -> Result:
        captured.append(kwargs["payload"] if "payload" in kwargs else _args[2])
        return Result()

    monkeypatch.setattr(cli, "resolve_arrival_target", lambda _target: None)
    monkeypatch.setattr(cli, "emit_fact", writer)
    source = tmp_path / "payload.json"
    source.write_text('{\n  "message": "héllo\\nworld"\n}', encoding="utf-8")
    common = [
        str(tmp_path / "unused.vertex"),
        "item",
        "--observer",
        "alice",
        *_credentials(tmp_path / "custody"),
    ]
    assert cli.main(["emit", *common, "--payload-file", str(source)]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["ok"] is True

    monkeypatch.setattr(cli.sys, "stdin", io.StringIO('{"message":"λ\\nstdin"}'))
    assert cli.main(["emit", *common, "--payload-file", "-"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert captured == [{"message": "héllo\nworld"}, {"message": "λ\nstdin"}]


@pytest.mark.parametrize(
    ("command", "source_option", "source"),
    [
        ("emit", "--payload-file", "missing.json"),
        ("emit", "--payload-file", "bad.json"),
        ("emit-batch", "--facts-file", "batch.json"),
    ],
)
def test_bad_transport_files_stop_before_target_or_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    source_option: str,
    source: str,
) -> None:
    reached: list[str] = []
    path = tmp_path / source
    if source == "bad.json":
        path.write_bytes(b'{"invalid":"\xff"}')
    elif source == "batch.json":
        path.write_text('[{"kind":"item"}, 1]', encoding="utf-8")

    monkeypatch.setattr(cli, "resolve_arrival_target", lambda *_args: reached.append("target"))
    monkeypatch.setattr(cli, "MappedCredentialProvider", lambda *_args, **_kwargs: reached.append("credentials"))
    arguments = [command, str(tmp_path / "unused.vertex"), source_option, str(path)]
    if command == "emit":
        arguments[2:2] = ["item", "--observer", "alice"]
    arguments.extend(_credentials(tmp_path / "custody"))

    assert cli.main(arguments) == cli.EXIT_USAGE
    output = json.loads(capsys.readouterr().out)
    assert output["error"]["type"] == "UsageError"
    assert reached == []
    assert not (tmp_path / "custody").exists()


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--facts-json", '[{"kind":"item","payload":{"a":1,"a":2}}]'),
        ("--facts-json", '[{"kind":"item","payload":{"a":1e999}}]'),
        ("--facts-json", '[{"kind":"item"}'),
        ("--facts-json", '[{"kind":"item"}, false]'),
    ],
)
def test_invalid_batch_transport_stops_before_target_or_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    option: str,
    value: str,
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(cli, "resolve_arrival_target", lambda *_args: reached.append("target"))
    monkeypatch.setattr(cli, "emit_batch", lambda *_args: reached.append("write"))
    assert cli.main(
        [
            "emit-batch",
            str(tmp_path / "unused.vertex"),
            option,
            value,
            *_credentials(tmp_path / "custody"),
        ]
    ) == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "UsageError"
    assert reached == []


def test_invalid_utf8_stdin_stops_before_target_or_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(cli, "resolve_arrival_target", lambda *_args: reached.append("target"))
    monkeypatch.setattr(cli, "MappedCredentialProvider", lambda *_args, **_kwargs: reached.append("credentials"))
    monkeypatch.setattr(cli.sys, "stdin", io.TextIOWrapper(io.BytesIO(b'{"x":"\xff"}')))

    assert cli.main(
        [
            "emit",
            str(tmp_path / "unused.vertex"),
            "item",
            "--payload-file",
            "-",
            "--observer",
            "alice",
            *_credentials(tmp_path / "custody"),
        ]
    ) == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "UsageError"
    assert reached == []


@pytest.mark.parametrize("stdin_state", ["missing", "closed"])
def test_unavailable_stdin_is_usage_without_target_or_credential_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stdin_state: str,
) -> None:
    reached: list[str] = []
    stream = io.TextIOWrapper(io.BytesIO())
    stream.close()
    monkeypatch.setattr(cli.sys, "stdin", None if stdin_state == "missing" else stream)
    monkeypatch.setattr(cli, "resolve_arrival_target", lambda *_args: reached.append("target"))
    monkeypatch.setattr(cli, "MappedCredentialProvider", lambda *_args, **_kw: reached.append("keys"))
    code = cli.main([
        "emit", str(tmp_path / "unused.vertex"), "item", "--payload-file", "-",
        "--observer", "alice", *_credentials(tmp_path / "custody"),
    ])
    assert code == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "UsageError"
    assert reached == []


@pytest.mark.parametrize(
    ("command", "arguments"),
    [
        ("emit", ("item", "--observer", "alice")),
        (
            "emit",
            ("item", "--payload-json", "{}", "--payload-file", "payload.json", "--observer", "alice"),
        ),
        ("emit-batch", ()),
        ("emit-batch", ("--facts-json", "[]", "--facts-file", "facts.json")),
    ],
)
def test_transport_requires_exactly_one_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    arguments: tuple[str, ...],
) -> None:
    reached: list[str] = []
    monkeypatch.setattr(cli, "resolve_arrival_target", lambda *_args: reached.append("target"))
    result = cli.main(
        [command, str(tmp_path / "unused.vertex"), *arguments, *_credentials(tmp_path / "custody")]
    )
    assert result == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "UsageError"
    assert reached == []


def test_preview_delegates_to_sdk_without_turning_refusal_into_transport_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class Result:
        def as_dict(self) -> dict[str, Any]:
            return {"admitted": False, "reason": "strict kind"}

    def preview(*args: Any, **kwargs: Any) -> Result:
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(cli, "resolve_arrival_target", lambda _target: None)
    monkeypatch.setattr(cli, "preview_emission", preview)
    assert cli.main(
        [
            "preview",
            str(tmp_path / "unused.vertex"),
            "item",
            "--payload-json",
            '{"normal":true}',
            "--observer",
            "alice",
            "--origin",
            "test",
            "--ts",
            "10",
            "--id",
            "stable-id",
            *_credentials(tmp_path / "custody"),
        ]
    ) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "ok": True,
        "result": {"admitted": False, "reason": "strict kind"},
    }
    assert len(calls) == 1
    positional, keyword = calls[0]
    assert positional == (str(tmp_path / "unused.vertex"), "item", {"normal": True})
    assert keyword | {"credentials": None} == {
        "observer": "alice",
        "origin": "test",
        "ts": 10.0,
        "id_override": "stable-id",
        "credentials": None,
    }
    assert isinstance(keyword["credentials"], MappedCredentialProvider)


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
