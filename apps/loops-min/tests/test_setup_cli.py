"""Process conformance for mapped custody setup and recoverable initialization."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from engine.arrival_initialization import arrival_intent_path


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


def _credentials(root: Path) -> list[str]:
    return [
        "--credential-root",
        str(root),
        "--credential-namespace",
        "tenant",
        "--receipt-observer",
        "alice",
    ]


def _cli(
    tmp_path: Path, command: str, target: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "loops_min", command, str(target), *args],
        capture_output=True,
        text=True,
        env=_environment(tmp_path),
        check=False,
    )


def _json(process: subprocess.CompletedProcess[str]) -> dict:
    assert process.stdout, process.stderr
    return json.loads(process.stdout)


def test_mapped_setup_interrupted_init_recovery_then_cli_write(tmp_path: Path) -> None:
    custody = tmp_path / "mapped-custody"
    setup = subprocess.run(
        [
            sys.executable,
            "-m",
            "loops_min",
            "credential-create",
            str(custody),
            "--namespace",
            "tenant",
            "--observer",
            "alice",
            "--token",
            "setup-alice",
        ],
        capture_output=True,
        text=True,
        env=_environment(tmp_path),
        check=False,
    )
    assert setup.returncode == 0, setup.stdout + setup.stderr
    setup_result = _json(setup)["result"]
    assert setup_result["binding_created"] is True
    assert setup_result["observer"] == "alice"

    target = tmp_path / "workload.vertex"
    location = (tmp_path / "workload.arrival").resolve()
    interrupted_launcher = """
import os, sys
import engine.arrival_initialization as initialization
original = initialization.initialize_arrival
def interrupted(*args, **kwargs):
    def stop(stage):
        if stage == 'after-mint':
            os._exit(75)
    kwargs['failure_hook'] = stop
    return original(*args, **kwargs)
initialization.initialize_arrival = interrupted
from loops_min.main import main
raise SystemExit(main(sys.argv[1:]))
"""
    interrupted = subprocess.run(
        [
            sys.executable,
            "-c",
            interrupted_launcher,
            "init",
            str(target),
            "--name",
            "workload",
            "--location",
            str(location),
            "--observer",
            "alice",
            *_credentials(custody),
        ],
        capture_output=True,
        text=True,
        env=_environment(tmp_path),
        check=False,
    )
    assert interrupted.returncode == 75, interrupted.stdout + interrupted.stderr
    intent = arrival_intent_path(target)
    assert intent.exists()
    assert not target.exists()
    intent_data = json.loads(intent.read_text(encoding="utf-8"))
    assert intent_data["phase"] == "minted"
    lineage = intent_data["lineage"]
    retained_declaration = intent_data["declaration_text"]
    ledger_before_recovery = location.read_bytes()

    custody_backup = tmp_path / "mapped-custody-recovery-offline"
    custody.rename(custody_backup)
    try:
        recovered = _cli(tmp_path, "init-recover", target)
        assert recovered.returncode == 0, recovered.stdout + recovered.stderr
        assert not custody.exists()
    finally:
        custody_backup.rename(custody)
    recovered_result = _json(recovered)["result"]
    assert recovered_result["read_path"] == "arrival"
    assert recovered_result["phase"] == "published"
    assert recovered_result["lineage"] == lineage
    assert recovered_result["head"]["ordinal"] == 1
    assert target.exists()
    assert target.read_text(encoding="utf-8") == retained_declaration
    recovered_ledger = location.read_bytes()
    assert recovered_ledger.startswith(ledger_before_recovery)
    assert len(recovered_ledger) > len(ledger_before_recovery)
    assert not intent.exists()

    target_after_recovery = target.read_bytes()
    repeated = _cli(tmp_path, "init-recover", target)
    assert repeated.returncode == 4
    assert target.read_bytes() == target_after_recovery
    assert location.read_bytes() == recovered_ledger

    emitted = _cli(
        tmp_path,
        "emit",
        target,
        "item",
        "--payload-json",
        '{"after":"recovery"}',
        "--observer",
        "alice",
        "--id",
        "after-recovery",
        *_credentials(custody),
    )
    assert emitted.returncode == 0, emitted.stdout + emitted.stderr
    emitted_result = _json(emitted)["result"]
    assert emitted_result["signed"] is True
    assert emitted_result["commit"]["before"] == recovered_result["head"]

    facts = _cli(tmp_path, "facts", target, "--order", "oldest", "--limit", "10")
    assert facts.returncode == 0, facts.stdout + facts.stderr
    facts_result = _json(facts)["result"]
    assert facts_result["truncated"] is False
    assert facts_result["basis"]["captured_head"] == emitted_result["commit"]["after"]
    assert facts_result["basis"]["projected_through"] == emitted_result["commit"]["after"]
    fact_rows = facts_result["items"]
    assert len(fact_rows) == 1
    assert {
        key: fact_rows[0][key] for key in ("id", "kind", "observer", "payload")
    } == {
        "id": "after-recovery",
        "kind": "item",
        "observer": "alice",
        "payload": {"after": "recovery"},
    }

    verified = _cli(tmp_path, "verify", target)
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert _json(verified)["result"]["verified_through"] == emitted_result["commit"]["after"]
