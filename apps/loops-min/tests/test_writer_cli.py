"""Process-boundary acceptance tests for the mapped Arrival writer commands."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sdk import MappedCredentialProvider, init_vertex, preview_emission
from sdk.errors import CommittedOutcomeUnknown, CommittedProjectionFailed


@pytest.fixture(autouse=True)
def _isolated_parent_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "LOOPS_HOME": str(tmp_path / "loops"),
        }
    )
    return environment


def _run(
    tmp_path: Path,
    command: str,
    target: Path,
    *arguments: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loops_min", command, str(target), *arguments],
        capture_output=True,
        input=input_text,
        text=True,
        env=_environment(tmp_path),
        check=False,
    )


def _json(process: subprocess.CompletedProcess[str]) -> dict:
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def _credentials(root: Path, *, namespace: str = "tenant") -> list[str]:
    return [
        "--credential-root",
        str(root),
        "--credential-namespace",
        namespace,
        "--receipt-observer",
        "alice",
    ]


def _provision(tmp_path: Path) -> tuple[Path, Path, MappedCredentialProvider, object, object]:
    custody = tmp_path / "mapped-custody"
    provider = MappedCredentialProvider(
        custody, namespace="tenant", receipt_observer="alice"
    )
    alice = provider.create_binding("alice", token="create-alice")
    bob = provider.create_binding("bob", token="create-bob")
    target = tmp_path / "workload.vertex"
    location = (tmp_path / "workload.arrival").resolve()
    return target, location, provider, alice, bob


def _init_mapped(
    tmp_path: Path, target: Path, location: Path, custody: Path
) -> dict:
    process = _run(
        tmp_path,
        "init",
        target,
        "--name",
        "workload",
        "--location",
        str(location),
        "--observer",
        "alice",
        *_credentials(custody),
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = _json(process)
    assert result["ok"] is True
    assert result["result"]["read_path"] == "arrival"
    assert result["result"]["phase"] == "published"
    return result["result"]


def _ledger_path(target: Path) -> Path:
    store_line = next(
        line for line in target.read_text(encoding="utf-8").splitlines() if line.startswith("store ")
    )
    return Path(store_line.split('"', 2)[1])


def _file_snapshot(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _proposal_with_bob(target: Path, bob_public_key: str) -> Path:
    current = target.read_text(encoding="utf-8")
    proposed = current.replace(
        "  }\n}\n\nloops",
        f'''  }}
  "bob" {{
    key "{bob_public_key}"
    grant {{ potential "item" }}
  }}
}}

loops''',
        1,
    )
    proposal = target.with_name("proposal.vertex")
    proposal.write_text(proposed, encoding="utf-8")
    return proposal


def test_mapped_writer_workflow_is_real_process_sdk_boundary(tmp_path: Path) -> None:
    target, location, provider, _alice, bob = _provision(tmp_path)
    init_result = _init_mapped(tmp_path, target, location, provider.root)

    first = _run(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-json",
        '{"owner":"alice","step":1}',
        "--observer",
        "alice",
        "--origin",
        "cli-test",
        "--id",
        "alice-first",
        *_credentials(provider.root),
    )
    assert first.returncode == 0, first.stdout + first.stderr
    first_result = _json(first)["result"]
    assert first_result["schema"] == "loops.sdk/emit-receipt/v2"
    assert first_result["stored"] is True
    assert first_result["witnessed"] is True
    assert first_result["commit"]["before"] == init_result["head"]

    proposal = _proposal_with_bob(target, bob.public_key)
    declaration = _run(
        tmp_path,
        "declaration",
        target,
        "--proposed-file",
        str(proposal),
        "--observer",
        "alice",
        *_credentials(provider.root),
    )
    assert declaration.returncode == 0, declaration.stdout + declaration.stderr
    declaration_result = _json(declaration)["result"]
    assert declaration_result["schema"] == "loops.sdk/declaration-edit/v2"
    assert declaration_result["status"] == "applied"
    assert any(change["subject"] == "bob" for change in declaration_result["changes"])
    assert declaration_result["commit"]["before"] == first_result["commit"]["after"]

    batch = _run(
        tmp_path,
        "emit-batch",
        target,
        "--facts-json",
        json.dumps(
            [
                {
                    "id": "alice-batch",
                    "kind": "item",
                    "payload": {"owner": "alice", "step": 2},
                    "observer": "alice",
                    "origin": "cli-test",
                    "ts": 10,
                },
                {
                    "id": "bob-batch",
                    "kind": "item",
                    "payload": {"owner": "bob", "step": 2},
                    "observer": "bob",
                    "origin": "cli-test",
                    "ts": 11,
                },
            ]
        ),
        *_credentials(provider.root),
    )
    assert batch.returncode == 0, batch.stdout + batch.stderr
    batch_result = _json(batch)["result"]
    assert batch_result["schema"] == "loops.sdk/batch-emit/v2"
    assert batch_result["atomic"] is True
    assert batch_result["atomicity"] == "single-append"
    assert [item["id"] for item in batch_result["items"]] == ["alice-batch", "bob-batch"]
    assert all(item["signed"] and item["stored"] for item in batch_result["items"])
    assert batch_result["commit"]["before"] == declaration_result["commit"]["after"]
    assert batch_result["commit"]["record_count"] == 2

    facts = _run(tmp_path, "facts", target, "--order", "oldest", "--limit", "20")
    assert facts.returncode == 0, facts.stdout + facts.stderr
    items = _json(facts)["result"]["items"]
    assert [item["id"] for item in items] == ["alice-first", "alice-batch", "bob-batch"]
    assert [(item["observer"], item["payload"]) for item in items] == [
        ("alice", {"owner": "alice", "step": 1}),
        ("alice", {"owner": "alice", "step": 2}),
        ("bob", {"owner": "bob", "step": 2}),
    ]
    facts_result = _json(facts)["result"]
    assert facts_result
    assert facts_result["truncated"] is False
    assert facts_result["basis"]["captured_head"] == batch_result["commit"]["after"]

    verified = _run(tmp_path, "verify", target)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert _json(verified)["result"]["level"] == "full"


def test_emit_file_and_stdin_transport_preserve_unicode_and_multiline_content(
    tmp_path: Path,
) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    source = tmp_path / "payload.json"
    source.write_text('{\n  "message": "héllo\\nfile"\n}\n', encoding="utf-8")

    from_file = _run(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-file",
        str(source),
        "--observer",
        "alice",
        "--id",
        "file-transport",
        *_credentials(provider.root),
    )
    assert from_file.returncode == 0, from_file.stdout + from_file.stderr
    from_stdin = _run(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-file",
        "-",
        "--observer",
        "alice",
        "--id",
        "stdin-transport",
        *_credentials(provider.root),
        input_text='{\n  "message": "λ\\nstdin"\n}\n',
    )
    assert from_stdin.returncode == 0, from_stdin.stdout + from_stdin.stderr
    facts = _run(tmp_path, "facts", target, "--order", "oldest", "--limit", "10")
    assert facts.returncode == 0, facts.stdout + facts.stderr
    assert [(item["id"], item["payload"]) for item in _json(facts)["result"]["items"]] == [
        ("file-transport", {"message": "héllo\nfile"}),
        ("stdin-transport", {"message": "λ\nstdin"}),
    ]


@pytest.mark.parametrize("transport", ["file", "stdin"])
def test_batch_file_and_stdin_transport(tmp_path: Path, transport: str) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    facts = [
        {"id": "batch-file-1", "kind": "item", "observer": "alice", "payload": {"text": "λ"}},
        {"id": "batch-file-2", "kind": "item", "observer": "alice", "payload": {"text": "two"}},
    ]
    document = json.dumps(facts, ensure_ascii=False)
    source = tmp_path / "facts.json"
    source.write_text(document, encoding="utf-8")
    process = _run(
        tmp_path, "emit-batch", target,
        "--facts-file", "-" if transport == "stdin" else str(source),
        *_credentials(provider.root),
        input_text=document if transport == "stdin" else None,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    assert _json(process)["result"]["commit"] is not None
    read = _run(tmp_path, "facts", target, "--order", "oldest", "--limit", "10")
    assert read.returncode == 0, read.stdout + read.stderr
    assert [(item["id"], item["payload"]) for item in _json(read)["result"]["items"]] == [
        (fact["id"], fact["payload"]) for fact in facts
    ]


def test_preview_is_sdk_result_without_custody_or_binding_mutation(tmp_path: Path) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    ledger = _ledger_path(target)
    payload = {"message": "héllo\\npreview"}
    custody_before = _file_snapshot(provider.root)
    ledger_before = ledger.read_bytes()

    process = _run(
        tmp_path,
        "preview",
        target,
        "item",
        "--payload-json",
        json.dumps(payload),
        "--observer",
        "alice",
        "--origin",
        "preview-test",
        "--ts",
        "10",
        "--id",
        "preview-id",
        *_credentials(provider.root),
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = _json(process)["result"]
    expected = preview_emission(
        target,
        "item",
        payload,
        observer="alice",
        origin="preview-test",
        ts=10.0,
        id_override="preview-id",
        credentials=provider,
    ).as_dict()
    assert result == expected
    assert ledger.read_bytes() == ledger_before
    assert _file_snapshot(provider.root) == custody_before


def test_strict_undeclared_preview_is_a_successful_refusal_result(tmp_path: Path) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    init_vertex(
        target, name="workload", store_type="arrival", location=str(location),
        observer="alice", strict=True, credentials=provider,
    )
    before = location.read_bytes()
    bindings = _file_snapshot(provider.root)
    process = _run(
        tmp_path, "preview", target, "undeclared-kind", "--payload-json", "{}",
        "--observer", "alice", *_credentials(provider.root),
    )
    assert process.returncode == 0, process.stdout + process.stderr
    envelope = _json(process)
    assert envelope["ok"] is True
    assert envelope["result"]["admitted"] is False
    assert envelope["result"]["kind_declared"] is False
    assert envelope["result"]["strict"] is True
    assert location.read_bytes() == before
    assert _file_snapshot(provider.root) == bindings


def test_writer_input_refusals_do_not_append_or_create_target(tmp_path: Path) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    ledger = _ledger_path(target)
    before = ledger.read_bytes()

    for malformed in (
        [{"kind": "item", "payload": {"ok": True}, "observer": "alice"},
         {"kind": "item", "payload": None, "observer": "alice"}],
        [{"kind": "item", "payload": {"ok": True}, "observer": "alice"},
         {"kind": "item", "payload": {}, "observer": "alice", "ts": "bad"}],
    ):
        process = _run(
            tmp_path,
            "emit-batch",
            target,
            "--facts-json",
            json.dumps(malformed),
            *_credentials(provider.root),
        )
        assert process.returncode == 2, process.stdout + process.stderr
        assert _json(process)["ok"] is False
        assert _json(process)["error"]["type"] == "InvalidEmissionRequest"
        assert ledger.read_bytes() == before

    absent = tmp_path / "partial.vertex"
    partial = _run(
        tmp_path,
        "init",
        absent,
        "--name",
        "partial",
        "--location",
        str((tmp_path / "partial.arrival").resolve()),
        "--observer",
        "alice",
        "--credential-root",
        str(provider.root),
    )
    assert partial.returncode == 2
    assert not absent.exists()


def test_wrong_namespace_and_legacy_writer_refuse_without_effects(tmp_path: Path) -> None:
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    ledger = _ledger_path(target)
    before = ledger.read_bytes()
    wrong_provider = MappedCredentialProvider(
        provider.root, namespace="wrong-tenant", receipt_observer="alice"
    )
    wrong_binding = wrong_provider.create_binding("alice", token="wrong-alice")
    wrong_namespace = _run(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-json",
        '{"wrong":true}',
        "--observer",
        "alice",
        *_credentials(provider.root, namespace="wrong-tenant"),
    )
    assert wrong_namespace.returncode == 4
    assert _json(wrong_namespace)["ok"] is False
    assert _json(wrong_namespace)["error"]["type"] == "ArrivalRefusal"
    assert _json(wrong_namespace)["error"]["source_type"] == "CredentialBindingRefused"
    wrong_error = _json(wrong_namespace)["error"]
    request = wrong_error["details"]["credential_binding"]["request"]
    assert request == {
        "namespace": "wrong-tenant",
        "observer": "alice",
        "domain": "fact",
        "purpose": "authorship",
    }
    assert wrong_error["details"]["credential_binding"]["reason"] == (
        "resolved public key is not authorized at the captured position"
    )
    assert wrong_error["details"]["credential_binding"]["binding"]["public_key"] == wrong_binding.public_key
    assert ledger.read_bytes() == before

    # An absent optional author binding follows the SDK's pre-signed-era rule:
    # it is an unsigned observation, and the CLI must not mint a key implicitly.
    custody_before_absent = _file_snapshot(provider.root)
    absent_namespace = _run(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-json",
        '{"optional":true}',
        "--observer",
        "alice",
        *_credentials(provider.root, namespace="absent-tenant"),
    )
    assert absent_namespace.returncode == 0, absent_namespace.stdout + absent_namespace.stderr
    absent_result = _json(absent_namespace)["result"]
    assert absent_result["signed"] is False
    assert absent_result["stored"] is True
    assert _file_snapshot(provider.root) == custody_before_absent

    missing_root_target = tmp_path / "missing-root.vertex"
    missing_root = _run(
        tmp_path,
        "init",
        missing_root_target,
        "--name",
        "missing-root",
        "--location",
        str((tmp_path / "missing-root.arrival").resolve()),
        "--observer",
        "alice",
        *_credentials(tmp_path / "does-not-exist"),
    )
    assert missing_root.returncode == 2
    assert _json(missing_root)["error"]["type"] == "SdkValueError"
    assert not missing_root_target.exists()
    assert not (tmp_path / "missing-root.arrival").exists()
    assert not (tmp_path / "does-not-exist").exists()

    legacy = tmp_path / "legacy.vertex"
    legacy_result = init_vertex(legacy, store_type="sqlite")
    legacy_before = legacy.read_bytes()
    legacy_write = _run(
        tmp_path,
        "emit",
        legacy,
        "item",
        "--payload-json",
        '{"legacy":true}',
        "--observer",
        "alice",
        *_credentials(provider.root),
    )
    assert legacy_write.returncode == 3
    assert _json(legacy_write)["error"]["type"] == "TargetUnsupported"
    assert legacy.read_bytes() == legacy_before
    assert legacy_result.store_path is not None
    assert not (legacy.parent / legacy_result.store_path).exists()


@pytest.mark.parametrize(
    ("command", "error_type", "outcome"),
    [
        ("emit", CommittedOutcomeUnknown, "unknown"),
        ("preview", CommittedOutcomeUnknown, "unknown"),
        ("emit", CommittedProjectionFailed, "committed-projection-failed"),
        ("preview", CommittedProjectionFailed, "committed-projection-failed"),
    ],
)
def test_cli_error_boundary_preserves_committed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: str,
    error_type: type[BaseException],
    outcome: str,
) -> None:
    cli = importlib.import_module("loops_min.main")
    target, location, provider, _alice, _bob = _provision(tmp_path)
    _init_mapped(tmp_path, target, location, provider.root)
    head = {"lineage": "L", "ordinal": 4, "record_hash": "H"}
    error = error_type(
        "reconcile this attempt",
        source_type="InjectedBoundary",
        details={"fact_id": "fact-1", "captured_head": head},
    )

    def fail(*_args: object, **_kwargs: object) -> dict:
        raise error

    monkeypatch.setattr(cli, "preview_emission" if command == "preview" else "emit_fact", fail)
    assert cli.main(
        [
            command,
            str(target),
            "item",
            "--payload-json",
            "{}",
            "--observer",
            "alice",
            "--credential-root",
            str(provider.root),
            "--credential-namespace",
            "tenant",
            "--receipt-observer",
            "alice",
        ]
    ) == 6
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["error"]["outcome"] == outcome
    assert output["error"]["source_type"] == "InjectedBoundary"
    assert output["error"]["details"]["fact_id"] == "fact-1"
    assert output["error"]["details"]["captured_head"] == head
