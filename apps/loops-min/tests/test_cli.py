"""Process-boundary tests for the minimal SDK read client."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact as AtomFact
from engine.arrival import ArrivalLog
from engine.arrival_store import ArrivalStore
from engine.residence import index_path_for
from engine.tick import Tick
from lang import parse_vertex, vertex_to_documents
from sign import ed25519


def _fixture(tmp_path: Path) -> tuple[Path, str]:
    keypair = ed25519.load_or_generate(tmp_path / "keys" / "kyle")

    def signer(observer: str, digest: str) -> str:
        return ed25519.sign(keypair, digest.encode(), domain="test-arrival-v1")

    log_path = tmp_path / "ledger.arrival"
    log = ArrivalLog.mint(
        log_path,
        observer="kyle",
        signer=signer,
        key=keypair.public_b64,
    )
    vertex_path = tmp_path / "arrival.vertex"
    source = (
        f'name "arrival"\nstore "{log_path}" backend="file" '
        f'lineage="{log.lineage()}" role="authority"\n'
        'loops { note { search "message" fold { items "collect" 100 } } }\n'
    )
    vertex_path.write_text(source, encoding="utf-8")
    ast = parse_vertex(source, path=vertex_path)
    documents = [document.as_json() for document in vertex_to_documents(ast)]
    store = ArrivalStore(
        path=index_path_for(log_path),
        log_path=log_path,
        serialize=lambda fact: fact.to_dict(),
        deserialize=AtomFact.from_dict,
        fact_signer=signer,
    )
    try:
        store.absorb_genesis(documents, observer="kyle", fact_signer=signer)
        fact_id = store.append(AtomFact.of("note", "kyle", message="hello"))
        store.append(AtomFact.of("note", "kyle", message="world"))
        store.append_tick(
            Tick(
                name="checkpoint",
                ts=datetime.fromtimestamp(123, tz=UTC),
                payload={"count": 1},
                origin="test",
            )
        )
    finally:
        store.close()
    return vertex_path, fact_id


def _ledger_path(vertex: Path) -> Path:
    line = next(line for line in vertex.read_text(encoding="utf-8").splitlines() if line.startswith("store "))
    return Path(line.split('"', 2)[1])


def _run(vertex: Path, *args: str, state_home: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(state_home)
    environment["XDG_CONFIG_HOME"] = str(state_home.parent / "config")
    environment["LOOPS_HOME"] = str(state_home.parent / "loops")
    prefix: list[str] = []
    if args and args[0] == "--pretty":
        prefix.append(args[0])
        args = args[1:]
    command, *command_args = args
    return subprocess.run(
        [sys.executable, "-m", "loops_min", *prefix, command, str(vertex), *command_args],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def _json_result(process: subprocess.CompletedProcess[str]) -> dict:
    assert process.stdout.count("\n") == 1, process.stdout
    assert process.stderr == "", process.stderr
    return json.loads(process.stdout)


def test_exact_export_process_preserves_bytes_and_refuses_replacement(tmp_path: Path) -> None:
    vertex, _fact_id = _fixture(tmp_path)
    output = tmp_path / "captured.jsonl"
    process = _run(vertex, "export", str(output), state_home=tmp_path / "xdg")
    assert process.returncode == 0
    result = _json_result(process)["result"]
    assert result["schema"] == "loops.sdk/export/v2"
    assert output.read_bytes() == _ledger_path(vertex).read_bytes()
    assert result["byte_count"] == output.stat().st_size
    again = _run(vertex, "export", str(output), state_home=tmp_path / "xdg")
    assert again.returncode == 4
    assert json.loads(again.stdout)["error"]["published"] is False
    assert output.read_bytes() == _ledger_path(vertex).read_bytes()


def test_restore_forward_process_keeps_ordinary_rollback_refusal(tmp_path: Path) -> None:
    vertex, _fact_id = _fixture(tmp_path)
    source_log = _ledger_path(vertex)
    receiver_log = tmp_path / "receiver.arrival"
    receiver_log.write_bytes(b"".join(source_log.read_bytes().splitlines(keepends=True)[:2]))
    receiver = tmp_path / "receiver.vertex"
    receiver.write_text(
        vertex.read_text().replace(str(source_log), str(receiver_log))
        .replace('role="authority"', 'role="replica"')
    )
    state = tmp_path / "xdg"
    assert _run(vertex, "verify", state_home=state).returncode == 0
    refused = _run(receiver, "verify", state_home=state)
    assert refused.returncode == 4
    assert json.loads(refused.stdout)["error"]["source_type"] == "HeadRollback"
    process = _run(vertex, "restore-forward", str(receiver), state_home=state)
    assert process.returncode == 0, process.stdout
    result = _json_result(process)["result"]
    assert result["schema"] == "loops.sdk/restore-forward/v2"
    assert result["commit"]["after"] == result["after"]
    assert receiver_log.read_bytes() == source_log.read_bytes()
    assert _run(receiver, "verify", state_home=state).returncode == 0


def test_real_arrival_reads_are_json_process_results(tmp_path: Path) -> None:
    vertex, fact_id = _fixture(tmp_path)
    state_home = tmp_path / "xdg"

    summary_process = _run(vertex, "summary", state_home=state_home)
    target_process = _run(vertex, "target", state_home=state_home)
    facts_process = _run(
        vertex,
        "facts",
        "--limit",
        "1",
        "--order",
        "oldest",
        "--kind",
        "note",
        "--observer",
        "kyle",
        state_home=state_home,
    )
    fact_process = _run(vertex, "fact", fact_id, state_home=state_home)
    state_process = _run(vertex, "state", state_home=state_home)
    inspect_process = _run(vertex, "inspect", state_home=state_home)
    ticks_process = _run(vertex, "ticks", "--name", "checkpoint", state_home=state_home)
    timeline_process = _run(vertex, "timeline", state_home=state_home)
    verify_process = _run(vertex, "verify", state_home=state_home)
    sync_process = _run(vertex, "sync", state_home=state_home)
    search_sync_process = _run(vertex, "search-sync", state_home=state_home)
    search_process = _run(vertex, "search", "hello", state_home=state_home)

    summary = _json_result(summary_process)
    target = _json_result(target_process)
    facts = _json_result(facts_process)
    fact = _json_result(fact_process)
    state = _json_result(state_process)
    inspect = _json_result(inspect_process)
    ticks = _json_result(ticks_process)
    timeline = _json_result(timeline_process)
    verify = _json_result(verify_process)
    sync = _json_result(sync_process)
    search_sync = _json_result(search_sync_process)
    search = _json_result(search_process)

    assert all(
        result["ok"]
        for result in (
            summary, target, facts, fact, state, inspect, ticks, timeline, verify, sync,
            search_sync, search,
        )
    )
    assert target["result"]["schema"] == "loops.sdk/arrival-target/v1"
    assert target["result"]["store"]["backend"] == "file"
    assert summary["result"]["read_path"] == "arrival"
    assert facts["result"]["items"][0]["id"] == fact_id
    assert facts["result"]["has_continuation"] is True
    assert facts["result"]["next_cursor"] is None
    assert fact["result"]["found"] is True
    assert fact["result"]["fact"]["id"] == fact_id
    assert "note" in state["result"]["sections"]
    assert inspect["result"]["read_path"] == "arrival"
    assert inspect["result"]["basis"] == summary["result"]["basis"]
    assert ticks["result"]["items"][0]["name"] == "checkpoint"
    assert timeline["result"]["read_path"] == "arrival"
    assert timeline["result"]["basis"] == summary["result"]["basis"]
    assert verify["result"]["level"] == "full"
    assert verify["result"]["captured_head"] == verify["result"]["verified_through"]
    assert sync["result"]["read_path"] == "arrival"
    assert search_sync["result"]["read_path"] == "arrival"
    assert search_sync["result"]["target"] == search_sync["result"]["basis"]["captured_head"]
    assert search["result"]["read_path"] == "arrival"
    assert search["result"]["basis"] is not None
    assert [item["payload"]["message"] for item in search["result"]["matches"]] == ["hello"]
    bases = [result["result"]["basis"] for result in (summary, facts, fact, state, ticks)]
    assert all(basis == bases[0] for basis in bases)


def test_sdk_refusal_and_unavailable_operation_have_stable_json_status(tmp_path: Path) -> None:
    vertex, _fact_id = _fixture(tmp_path)
    state_home = tmp_path / "xdg"

    search = _run(vertex, "search", "hello", state_home=state_home)
    assert search.returncode == 4
    search_error = json.loads(search.stdout)
    assert search_error["ok"] is False
    assert search_error["error"]["type"] == "ArrivalRefusal"
    assert search_error["error"]["source_type"] == "SearchStale"
    assert "search" in search.stderr

    timeline = _run(vertex, "timeline", state_home=state_home)
    entity = _run(vertex, "resolve", "note", "message", "hello", state_home=state_home)
    assert timeline.returncode == 0
    timeline_value = json.loads(timeline.stdout)["result"]
    assert timeline_value["read_path"] == "arrival"
    assert timeline_value["basis"] is not None
    assert entity.returncode == 0
    entity_value = json.loads(entity.stdout)["result"]
    assert entity_value["found"] is True
    assert entity_value["basis"] is not None
    assert entity_value["read_path"] == "arrival"
    assert entity_value["store"]["backend"] == "file"
    assert entity_value["address"] == {"kind": "note", "key": "message", "value": "hello"}

    init_target = tmp_path / "would-be.vertex"
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(state_home)
    environment["XDG_CONFIG_HOME"] = str(state_home.parent / "config")
    environment["LOOPS_HOME"] = str(state_home.parent / "loops")
    init = subprocess.run(
        [sys.executable, "-m", "loops_min", "replicate", str(init_target)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert init.returncode == 3
    assert json.loads(init.stdout) == {
        "ok": False,
        "error": {
            "type": "Unavailable",
            "message": "replicate is unavailable until its Arrival SDK operation exists",
            "details": {"operation": "replicate"},
        },
    }
    assert not init_target.exists()

    inspect = _run(vertex, "inspect", state_home=state_home)
    assert inspect.returncode == 0
    inspect_value = json.loads(inspect.stdout)["result"]
    assert inspect_value["read_path"] == "arrival"
    assert inspect_value["basis"] is not None


def test_help_and_pretty_output_are_conventional(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["XDG_STATE_HOME"] = str(tmp_path / "xdg")
    help_process = subprocess.run(
        [sys.executable, "-m", "loops_min", "--help"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert help_process.returncode == 0
    assert "JSON process client" in help_process.stdout
    assert help_process.stderr == ""

    vertex, _fact_id = _fixture(tmp_path)
    pretty = _run(vertex, "--pretty", "summary", state_home=tmp_path / "xdg-pretty")
    assert pretty.returncode == 0
    assert json.loads(pretty.stdout)["ok"] is True
    assert pretty.stdout.count("\n") > 1
    trailing_pretty = _run(vertex, "summary", "--pretty", state_home=tmp_path / "xdg-pretty-trailing")
    assert trailing_pretty.returncode == 0
    assert json.loads(trailing_pretty.stdout)["ok"] is True

    malformed_pretty = subprocess.run(
        [sys.executable, "-m", "loops_min", "--pretty", "facts", str(vertex), "--limit", "invalid"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert malformed_pretty.returncode == 2
    assert malformed_pretty.stdout.count("\n") > 1

    malformed = subprocess.run(
        [sys.executable, "-m", "loops_min", "facts", str(vertex), "--limit", "invalid"],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert malformed.returncode == 2
    assert json.loads(malformed.stdout) == {
        "ok": False,
        "error": {
            "type": "UsageError",
            "message": "argument --limit: invalid int value: 'invalid'",
            "details": {},
        },
    }
    assert "loops-min parse:" in malformed.stderr

    unknown = subprocess.run(
        [sys.executable, "-m", "loops_min", "unknown", str(vertex)],
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )
    assert unknown.returncode == 2
    assert json.loads(unknown.stdout)["error"]["type"] == "UsageError"

    missing = _run(tmp_path / "missing.vertex", "summary", state_home=tmp_path / "xdg-missing")
    assert missing.returncode == 4
    assert json.loads(missing.stdout)["error"]["type"] == "TargetNotFound"


def test_arrival_corruption_rollback_and_projection_behind_are_typed_refusals(
    tmp_path: Path,
) -> None:
    corrupt_vertex, _fact_id = _fixture(tmp_path / "corrupt")
    corrupt_log = _ledger_path(corrupt_vertex)
    corrupt_rows = corrupt_log.read_text(encoding="utf-8").splitlines()
    corrupt_record = json.loads(corrupt_rows[-1])
    corrupt_record["rh"] = "0" * 64
    corrupt_rows[-1] = json.dumps(corrupt_record, separators=(",", ":"))
    corrupt_log.write_text("\n".join(corrupt_rows) + "\n", encoding="utf-8")
    corrupt = _run(corrupt_vertex, "summary", state_home=tmp_path / "corrupt-xdg")
    assert corrupt.returncode == 4
    corrupt_error = json.loads(corrupt.stdout)["error"]
    assert corrupt_error["schema"] == "loops.sdk/error/v1"
    assert corrupt_error["type"] == "ArrivalRefusal"
    assert corrupt_error["message"] == (
        "arrival log corrupt at ordinal -1: rh does not recompute — "
        "the record's bytes have changed"
    )
    assert corrupt_error["source_type"] == "ArrivalCorrupt"
    assert corrupt_error["outcome"] == "refused"
    assert corrupt_error["details"]["ordinal"] == -1
    assert corrupt_error["details"]["source_type"] == "ArrivalCorrupt"
    assert corrupt_error["details"]["evidence"]["schema"] == "loops.sdk/evidence/v1"

    rollback_vertex, _fact_id = _fixture(tmp_path / "rollback")
    rollback_log = _ledger_path(rollback_vertex)
    rollback_xdg = tmp_path / "rollback-xdg"
    assert _run(rollback_vertex, "summary", state_home=rollback_xdg).returncode == 0
    rollback_rows = rollback_log.read_text(encoding="utf-8").splitlines()
    rollback_log.write_text("\n".join(rollback_rows[:-1]) + "\n", encoding="utf-8")
    rollback = _run(rollback_vertex, "summary", state_home=rollback_xdg)
    assert rollback.returncode == 4
    assert json.loads(rollback.stdout)["error"]["details"]["source_type"] == "HeadRollback"

    behind_vertex, _fact_id = _fixture(tmp_path / "behind")
    behind_log = _ledger_path(behind_vertex)
    behind_xdg = tmp_path / "behind-xdg"
    assert _run(behind_vertex, "summary", state_home=behind_xdg).returncode == 0
    index_path_for(behind_log).unlink()
    behind = _run(behind_vertex, "summary", state_home=behind_xdg)
    assert behind.returncode == 4
    assert json.loads(behind.stdout)["error"] == {
        "schema": "loops.sdk/error/v1",
        "type": "ArrivalRefusal",
        "message": f"{index_path_for(behind_log)} does not exist",
        "source_type": "ProjectionAbsent",
        "outcome": "refused",
        "details": {"source_type": "ProjectionAbsent"},
    }


def test_built_wheel_contains_only_the_cli_boundary(tmp_path: Path) -> None:
    repo_root = Path(__file__).parents[3]
    built = subprocess.run(
        ["uv", "build", "--package", "loops-min", "--wheel", "--out-dir", str(tmp_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    wheels = list(tmp_path.glob("loops_min-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())
        assert {
            "loops_min/__init__.py",
            "loops_min/__main__.py",
            "loops_min/main.py",
        } <= names
        metadata = archive.read(next(name for name in names if name.endswith("/METADATA"))).decode()
        entry_points = archive.read(
            next(name for name in names if name.endswith("/entry_points.txt"))
        ).decode()
    assert "Requires-Dist: sdk" in metadata
    assert "loops-min = loops_min.main:main" in entry_points


def test_cli_source_has_no_forbidden_direct_dependencies() -> None:
    source_root = Path(__file__).parents[1] / "src" / "loops_min"
    for source_path in source_root.rglob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
                assert set(names) <= {"argparse", "json", "sys"}, (source_path, names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                assert node.module in {
                    "__future__",
                    "collections.abc",
                    "typing",
                    "sdk",
                    "sdk.errors",
                }, (source_path, node.module)
            else:
                continue
