"""Process-boundary acceptance tests for the mapped Arrival writer commands."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sdk import MappedCredentialProvider, init_vertex
from sdk.errors import CommittedOutcomeUnknown, CommittedProjectionFailed


@pytest.fixture(autouse=True)
def _isolated_parent_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops"))


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "LOOPS_HOME": str(tmp_path / "loops"),
        }
    )
    return environment


def _run(
    tmp_path: Path, command: str, target: Path, *arguments: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loops_min", command, str(target), *arguments],
        capture_output=True,
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
    ("error_type", "outcome"),
    [
        (CommittedOutcomeUnknown, "unknown"),
        (CommittedProjectionFailed, "committed-projection-failed"),
    ],
)
def test_cli_error_boundary_preserves_committed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
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

    monkeypatch.setattr(cli, "emit_fact", fail)
    assert cli.main(
        [
            "emit",
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
