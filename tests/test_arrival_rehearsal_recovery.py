"""Synthetic subprocess proof for the offline adoption-recovery rehearsal."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sign import ed25519

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "arrival_rehearsal.py"
RECOVERY = ROOT / "scripts" / "arrival_rehearsal_recovery.py"


@pytest.mark.parametrize("runtime_epoch", ["strict", "fresh"])
def test_recovery_rehearsal_forks_s_and_recovers_both_durable_boundaries(
    tmp_path: Path,
    monkeypatch,
    runtime_epoch: str,
) -> None:
    outside = tmp_path / "must-stay-unused"
    for name in (
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "LOOPS_HOME",
    ):
        monkeypatch.setenv(name, str(outside / name.lower()))
    sandbox = tmp_path / "isolated"
    source = sandbox / "input" / "legacy.jsonl"
    vertex = sandbox / "work" / ".loops" / "alice.vertex"
    source.parent.mkdir(parents=True)
    vertex.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "t": "fact",
                "id": "01ARZ3NDEKTSV4RRFFQ69G5FA0",
                "kind": "concept",
                "ts": 1000.0,
                "observer": "alice",
                "origin": "legacy",
                "payload": '{"text":"migrated"}',
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    keys = vertex.parent / "keys"
    pair = ed25519.load_or_generate(keys)
    vertex.write_text(
        f'''name "alice"
store "../../input/legacy.jsonl"

observers {{
  alice {{ key "{pair.public_b64}" }}
}}

loops {{ concept {{ fold {{ items "collect" 100 }} }} }}
''',
        encoding="utf-8",
    )
    rehearsal_output = sandbox / "output"
    rehearsal = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            "--sandbox",
            str(sandbox),
            "--vertex",
            str(vertex),
            "--source",
            str(source),
            "--legacy-key-dir",
            str(keys),
            "--output",
            str(rehearsal_output),
            "--observer",
            "alice",
            "--runtime-epoch",
            runtime_epoch,
            "--emit-kind",
            "concept",
            "--emit-payload-json",
            '{"text":"rehearsal"}',
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert rehearsal.returncode == 0, rehearsal.stderr
    rehearsal_evidence = json.loads((rehearsal_output / "evidence.json").read_text())
    state_epoch = rehearsal_evidence["reads_at_A"]["runtime_state"]["runtime_epoch"]
    assert state_epoch["mode"] == runtime_epoch
    assert isinstance(rehearsal_evidence["reads_at_A"]["runtime_state"]["sections_sha256"], str)
    if runtime_epoch == "fresh":
        assert state_epoch["anchor_ordinal"] == rehearsal_evidence["adoption"]["head"]["ordinal"]

    recovery_output = sandbox / "recovery"
    recovered = subprocess.run(
        [
            sys.executable,
            str(RECOVERY),
            "--sandbox",
            str(sandbox),
            "--evidence",
            str(rehearsal_output / "evidence.json"),
            "--output",
            str(recovery_output),
            "--observer",
            "alice",
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )
    assert recovered.returncode == 0, recovered.stderr
    evidence = json.loads((recovery_output / "recovery-evidence.json").read_text())
    assert evidence["status"] == "complete"
    assert [fork["phase"] for fork in evidence["forks"]] == [
        "after-intent",
        "after-append",
    ]
    for fork in evidence["forks"]:
        assert fork["head"]["ordinal"] == fork["selected_head"]["ordinal"] + 1
        assert fork["pre_adoption_error"] == "SdkError"
        assert fork["runtime_epoch"] == runtime_epoch
        assert fork["second_recovery_error"]
    assert not outside.exists()
