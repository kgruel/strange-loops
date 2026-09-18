"""One isolated end-to-end exercise of the offline rehearsal command."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from sign import ed25519

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "arrival_rehearsal.py"


def _inputs(tmp_path: Path, *, owned_tick: bool = False) -> tuple[Path, Path, Path, Path]:
    sandbox = tmp_path / "isolated"
    source = sandbox / "input" / "legacy.jsonl"
    vertex = sandbox / "work" / ".loops" / "alice.vertex"
    source.parent.mkdir(parents=True)
    vertex.parent.mkdir(parents=True)
    rows = [{
            "t": "fact", "id": "01ARZ3NDEKTSV4RRFFQ69G5FA0", "kind": "concept",
            "ts": 1000.0, "observer": "alice", "origin": "legacy",
            "payload": '{"text":"migrated"}',
    }]
    if owned_tick:
        rows.append({
            "t": "tick", "id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
            "name": "alice", "ts": 1001.0, "since": 1000.0,
            "origin": "alice", "payload": "{}", "prev_hash": None,
            "window_start": None, "fact_cursor": None, "window_hash": None,
        })
    source.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    keys = vertex.parent / "keys"
    pair = ed25519.load_or_generate(keys)
    vertex.write_text(
        f'''name "alice"
store "../../input/legacy.jsonl"

observers {{
  alice {{
    key "{pair.public_b64}"
  }}
}}

loops {{
  {('boundary when="seal"' if owned_tick else '')}
  concept {{ fold {{ items "collect" 100 }} }}
}}
''',
        encoding="utf-8",
    )
    return sandbox, vertex, source, keys


def _command(sandbox: Path, vertex: Path, source: Path, keys: Path, output: Path) -> list[str]:
    return [
        sys.executable, str(RUNNER), "--sandbox", str(sandbox),
        "--vertex", str(vertex), "--source", str(source),
        "--legacy-key-dir", str(keys), "--output", str(output),
        "--observer", "alice", "--emit-kind", "concept",
        "--emit-payload-json", '{"text":"rehearsal"}',
    ]


def test_rehearsal_migrates_adopts_reads_emits_and_exactly_exports(tmp_path: Path) -> None:
    sandbox, vertex, source, keys = _inputs(tmp_path)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    output = sandbox / "output"
    result = subprocess.run(
        _command(sandbox, vertex, source, keys, output),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads((output / "evidence.json").read_text())
    assert evidence["status"] == "complete"
    assert evidence["source_sha256_before"] == source_hash
    assert evidence["source_unchanged"] is True
    assert evidence["report_verified_at_S"] is True
    assert evidence["migration"]["prefix_unchanged_after_emit"] is True
    assert evidence["migration"]["report_unchanged_after_emit"] is True
    assert evidence["adoption"]["fact_id_equals_lineage"] is True
    assert evidence["rehearsal_emit"]["signed_fact_and_arrival"] is True
    assert evidence["export"]["exact_stream_match"] is True
    assert (output / "reviewed.vertex").is_file()
    assert (output / "final.arrival-jsonl").is_file()


def test_rehearsal_refuses_paths_outside_sandbox_before_writing(tmp_path: Path) -> None:
    sandbox, vertex, source, keys = _inputs(tmp_path)
    output = tmp_path / "escaped-output"
    result = subprocess.run(
        _command(sandbox, vertex, source, keys, output),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    assert not output.exists()
    assert "refused: RehearsalRefused" in result.stderr


def test_owned_legacy_period_tick_remains_a_write_refusal(tmp_path: Path) -> None:
    """Adoption preserves the tick; it cannot license its pre-genesis role."""
    sandbox, vertex, source, keys = _inputs(tmp_path, owned_tick=True)
    output = sandbox / "output"
    before = source.read_bytes()
    result = subprocess.run(
        _command(sandbox, vertex, source, keys, output),
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    evidence = json.loads((output / "evidence.json").read_text())
    assert evidence["stage"] == "rehearsal-only-emit"
    assert evidence["report_verified_at_S"] is True
    assert evidence["adoption"]["head"]["ordinal"] == 3
    assert evidence["refusal"] == {
        "type": "ArrivalRefusal",
        "source_type": "BoundaryContinuityRefused",
        "captured_head": evidence["adoption"]["head"],
        "phase": "prepare",
        "effects": {"custody": {"attempt": "not-entered", "state": "not-attempted"}},
        "boundary_reason": "ambiguous-tick-role",
        "tick_id": "01ARZ3NDEKTSV4RRFFQ69G5FT1",
        "tick_ordinal": 2,
    }
    assert evidence["source_unchanged"] is True
    assert evidence["target_unchanged_after_refusal"] is True
    assert source.read_bytes() == before
    target = Path(evidence["migration"]["target_path"])
    kinds = [json.loads(line)["k"] for line in target.read_text().splitlines()]
    assert kinds == ["genesis", "fact", "tick", "fact"]
