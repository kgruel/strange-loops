"""A real custody publication failure crosses the process boundary intact."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_binding_publication_failure_and_fresh_process_recovery(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for variable, directory in (
        ("XDG_STATE_HOME", "state"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("LOOPS_HOME", "loops"),
    ):
        environment[variable] = str(tmp_path / directory)
    root = tmp_path / "credentials"
    arguments = [str(root), "--namespace", "tenant", "--observer", "alice"]
    launcher = """
import sys
from custody.binding import MappedCredentialProvider
def interrupt(self, phase, intent):
    if phase == 'binding-published':
        raise OSError('injected failure after binding publication')
MappedCredentialProvider._hook = interrupt
from loops_min.main import main
raise SystemExit(main(sys.argv[1:]))
"""
    failed = subprocess.run(
        [sys.executable, "-c", launcher, "credential-create", *arguments,
         "--token", "setup-alice"],
        capture_output=True, text=True, env=environment, check=False,
    )
    assert failed.returncode == 6, failed.stdout + failed.stderr
    failure = json.loads(failed.stdout)
    assert failure["ok"] is False
    error = failure["error"]
    assert error == {
        "schema": "loops.sdk/error/v1",
        "type": "CredentialBindingIncomplete",
        "message": "mapped binding mutation outcome is incomplete or unknown",
        "outcome": "incomplete",
        "operation": "create",
        "namespace": "tenant",
        "observer": "alice",
        "token": "setup-alice",
        "key_ref": error["key_ref"],
        "phase": "binding-published",
        "source_type": "BindingMutationIncomplete",
        "recovery_action": "reconcile",
    }

    def files() -> dict[Path, bytes]:
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def invoke(command: str, token: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "loops_min", command, *arguments, "--token", token],
            capture_output=True, text=True, env=environment, check=False,
        )

    before = files()
    key_prefix = Path("keys-v1") / error["key_ref"]
    retained_key = {p: value for p, value in before.items() if p.is_relative_to(key_prefix)}
    assert retained_key
    wrong = invoke("credential-recover", "wrong-token")
    assert wrong.returncode == 4, wrong.stdout + wrong.stderr
    wrong_error = json.loads(wrong.stdout)["error"]
    assert wrong_error["type"] == "CredentialBindingRecoveryRequired"
    assert wrong_error["token"] == "wrong-token"
    assert files() == before

    recovered = invoke("credential-recover", "setup-alice")
    assert recovered.returncode == 0, recovered.stdout + recovered.stderr
    result = json.loads(recovered.stdout)["result"]
    assert result["operation"] == "recover"
    assert result["key_ref"] == error["key_ref"]
    assert result["token"] == "setup-alice"
    assert result["binding_created"] is False
    assert result["key_created"] is False
    after = files()
    assert {p: value for p, value in after.items() if p.parts[0] == "keys-v1"} == retained_key
    assert all(after[p] == value for p, value in before.items())

    replayed = invoke("credential-create", "setup-alice")
    assert replayed.returncode == 0, replayed.stdout + replayed.stderr
    replay_result = json.loads(replayed.stdout)["result"]
    assert replay_result == {**result, "operation": "create"}
    assert files() == after


def test_non_object_custody_record_retains_process_recovery_coordinates(tmp_path: Path) -> None:
    environment = os.environ.copy()
    for variable, directory in (
        ("XDG_STATE_HOME", "state"),
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_CACHE_HOME", "cache"),
        ("LOOPS_HOME", "loops"),
    ):
        environment[variable] = str(tmp_path / directory)
    root = tmp_path / "credentials"
    arguments = [str(root), "--namespace", "tenant", "--observer", "alice",
                 "--token", "setup-alice"]

    def invoke(command: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "loops_min", command, *arguments],
            capture_output=True, text=True, env=environment, check=False,
        )

    created = invoke("credential-create")
    assert created.returncode == 0, created.stdout + created.stderr
    pending = list((root / "pending-v1").glob("*.json"))
    assert len(pending) == 1
    pending[0].write_text("[]\n", encoding="utf-8")
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    refused = invoke("credential-recover")
    assert refused.returncode == 6, refused.stdout + refused.stderr
    result = json.loads(refused.stdout)
    assert result["ok"] is False
    error = result["error"]
    assert error["type"] == "CredentialBindingIncomplete"
    assert error["source_type"] == "TypeError"
    assert error["phase"] == "unknown"
    assert error["operation"] == "recover"
    assert error["namespace"] == "tenant"
    assert error["observer"] == "alice"
    assert error["token"] == "setup-alice"
    assert "key_ref" not in error
    assert "commit" not in error
    assert {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
