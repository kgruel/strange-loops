"""Process tests for the standalone Claude Arrival adapter."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parents[1] / "hooks" / "arrival_session.py"
HEAD = {"lineage": "lineage", "ordinal": 2, "record_hash": "hash-2"}
COMMIT = {
    "before": {"lineage": "lineage", "ordinal": 1, "record_hash": "hash-1"},
    "after": HEAD,
}
PLUGIN_ROOT = HOOK.parents[1]


def test_plugin_registers_one_adapter_per_event_without_legacy_loading() -> None:
    manifest = json.loads(
        (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    hooks = json.loads(
        (PLUGIN_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )["hooks"]
    assert manifest["version"] == "0.2.0"
    assert set(hooks) == {"SessionStart", "SessionEnd", "Stop"}
    matcher = hooks["SessionStart"][0]["matcher"]
    assert all(
        re.fullmatch(matcher, source)
        for source in ("startup", "resume", "clear", "fork")
    )
    assert not re.fullmatch(matcher, "compact")
    assert hooks["SessionEnd"][0]["hooks"][0]["timeout"] == 60
    for event in hooks.values():
        assert len(event) == 1 and len(event[0]["hooks"]) == 1
        assert "arrival_session.py" in event[0]["hooks"][0]["command"]
    legacy_files = {
        "commands/reconcile.md",
        "commands/sweep.md",
        "hooks/lib.sh",
        "hooks/session-close.sh",
        "hooks/session-open.sh",
        "hooks/session-orient.sh",
        "hooks/turn-capture.py",
        "skills/loops/SKILL.md",
        "skills/release/SKILL.md",
    }
    discovered = {
        path.relative_to(PLUGIN_ROOT).as_posix()
        for path in PLUGIN_ROOT.rglob("*")
        if path.is_file()
    }
    assert not legacy_files & discovered


def _binary(tmp_path: Path) -> Path:
    binary = tmp_path / "fake loops min.py"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['HOOK_LOG'], 'a', encoding='utf-8') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "command=sys.argv[1]\n"
        "responses=json.loads(os.environ.get('HOOK_RESPONSES','{}'))\n"
        "item=responses.get(command)\n"
        "if isinstance(item,list): item=item.pop(0)\n"
        "request=sys.argv[sys.argv.index('--id')+1] if '--id' in sys.argv else None\n"
        "def replace_ids(value):\n"
        "  if isinstance(value,dict):\n"
        "    if value.get('id') == 'ignored': value['id']=request\n"
        "    for child in value.values(): replace_ids(child)\n"
        "  elif isinstance(value,list):\n"
        "    for child in value: replace_ids(child)\n"
        "if request: replace_ids(item)\n"
        "if item == 'INVALID': print('{')\n"
        "elif item == 'BAD_UTF8': sys.stdout.buffer.write(b'\\xff')\n"
        "else: print(json.dumps(item if item is not None else {'ok':False,'error':{'type':'Missing','outcome':'failed','details':{}}}))\n"
        "if os.environ.get('HOOK_DELETE_AFTER_EMIT') == '1' and command == 'emit': os.unlink(sys.argv[0])\n"
        "sys.exit(int(os.environ.get('HOOK_EXIT_'+command.upper(), '0')))\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    return binary


def _receipt(request_id: str = "ignored") -> dict:
    return {
        "write_path": "arrival",
        "store": {"backend": "file", "location": "/tmp/ledger"},
        "id": request_id,
        "stored": True,
        "witnessed": True,
        "captured_head": HEAD,
        "commit": COMMIT,
    }


def _read(items: list[dict] | None = None, *, head: dict | None = None) -> dict:
    read_head = HEAD if head is None else head
    return {
        "ok": True,
        "result": {
            "read_path": "arrival",
            "basis": {
                "lineage": "lineage",
                "captured_head": read_head,
                "projected_through": read_head,
                "view_generation": "view",
            },
            "store": {
                "backend": "file",
                "location": "/tmp/ledger",
                "lineage": "lineage",
                "role": "primary",
            },
            "vertex_name": "target",
            "fact_total": 2,
            "tick_total": 1,
            "runtime_epoch": {"mode": "strict"},
            "items": items or [],
            "truncated": False,
            "metadata_only": True,
            "order": "newest",
        },
    }


def _metadata_item(
    identifier: str = "metadata-id", ordinal: int = 2, sequence: int = 0
) -> dict:
    return {
        "id": identifier,
        "kind": "note",
        "ts": 1_767_225_600.0,
        "observer": "alice",
        "origin": "session",
        "arrival_ordinal": ordinal,
        "arrival_seq": sequence,
    }


def _environment(tmp_path: Path) -> dict[str, str]:
    excluded = {
        "LOOPS_CLAUDE_HOOK_CONFIG",
        "LOOPS_HOME",
        "XDG_STATE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in excluded and not key.startswith("HOOK_")
    }
    env.update(
        {
            "LOOPS_HOME": str(tmp_path / "loops"),
            "XDG_STATE_HOME": str(tmp_path / "state"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "HOOK_LOG": str(tmp_path / "calls.jsonl"),
        }
    )
    return env


def _run(
    tmp_path: Path,
    action: str,
    config: dict | None,
    event: object = None,
    responses: dict | None = None,
    *,
    config_bytes: bytes | None = None,
    **extra: str,
) -> subprocess.CompletedProcess[str]:
    env = _environment(tmp_path)
    if config is not None:
        path = tmp_path / "hook config.json"
        if config_bytes is None:
            path.write_text(json.dumps(config), encoding="utf-8")
        else:
            path.write_bytes(config_bytes)
        env["LOOPS_CLAUDE_HOOK_CONFIG"] = str(path)
    if responses is not None:
        env["HOOK_RESPONSES"] = json.dumps(responses)
    env.update(extra)
    if isinstance(event, bytes):
        process = subprocess.run(
            [sys.executable, str(HOOK), action],
            input=event,
            capture_output=True,
            env=env,
            check=False,
        )
        return subprocess.CompletedProcess(
            process.args,
            process.returncode,
            process.stdout.decode("utf-8"),
            process.stderr.decode("utf-8"),
        )
    return subprocess.run(
        [sys.executable, str(HOOK), action],
        input="" if event is None else json.dumps(event),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _adapter_module():
    spec = importlib.util.spec_from_file_location("arrival_session_test", HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _config(tmp_path: Path, binary: Path, **changes: object) -> dict:
    result: dict[str, object] = {
        "enabled": True,
        "binary": str(binary),
        "target": str(tmp_path / "target with spaces.vertex"),
        "credential_root": str(tmp_path / "credential root"),
        "credential_namespace": "tenant space",
        "observer": "alice/example",
        "receipt_observer": "receipt/example",
    }
    result.update(changes)
    return result


def _calls(tmp_path: Path) -> list[list[str]]:
    path = tmp_path / "calls.jsonl"
    return (
        []
        if not path.exists()
        else [json.loads(line) for line in path.read_text().splitlines()]
    )


def _diagnostics(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines()]


def _last_diagnostic(output: str) -> dict:
    return _diagnostics(output)[-1]


def test_unset_and_disabled_skip_stdin_target_and_subprocess(
    tmp_path: Path, monkeypatch
) -> None:
    module = _adapter_module()

    class UnreadableStdin:
        def read(self):
            raise AssertionError("disabled adapter read stdin")

    def forbidden_run(*_args, **_kwargs):
        raise AssertionError("disabled adapter touched target or subprocess")

    monkeypatch.setattr(module.sys, "stdin", UnreadableStdin())
    monkeypatch.setattr(module, "_run", forbidden_run)
    monkeypatch.delenv("LOOPS_CLAUDE_HOOK_CONFIG", raising=False)
    assert module.main(["start"]) == 0

    config = tmp_path / "disabled.json"
    config.write_text('{"enabled":false}', encoding="utf-8")
    monkeypatch.setenv("LOOPS_CLAUDE_HOOK_CONFIG", str(config))
    assert module.main(["start"]) == 0


def test_invalid_config_bytes_and_event_bytes_fail_before_child(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    bad_utf8 = _run(
        tmp_path,
        "start",
        {},
        {"hook_event_name": "SessionStart"},
        config_bytes=b'{"enabled":true}\xff',
    )
    assert bad_utf8.returncode == 1
    assert "cannot read" in bad_utf8.stderr and _calls(tmp_path) == []

    bad_nul = _run(
        tmp_path,
        "start",
        {},
        {"hook_event_name": "SessionStart"},
        config_bytes=b'{"enabled":true}\x00',
    )
    assert bad_nul.returncode == 1
    assert "NUL byte" in bad_nul.stderr and _calls(tmp_path) == []

    invalid_event = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        b'{"hook_event_name":"SessionStart"}\xff',
    )
    assert invalid_event.returncode == 1
    assert "not valid UTF-8" in invalid_event.stderr and _calls(tmp_path) == []


def test_enabled_configuration_and_event_errors_are_loud_before_child(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    relative = _config(tmp_path, binary, target="relative.vertex")
    process = _run(tmp_path, "start", relative, {"hook_event_name": "SessionStart"})
    assert (
        process.returncode == 1
        and "absolute" in process.stderr
        and _calls(tmp_path) == []
    )
    unknown = _config(tmp_path, binary, unexpected=True)
    process = _run(tmp_path, "start", unknown, {"hook_event_name": "Stop"})
    assert (
        process.returncode == 1
        and "unknown keys" in process.stderr
        and _calls(tmp_path) == []
    )
    process = _run(
        tmp_path, "start", _config(tmp_path, binary), {"hook_event_name": "Stop"}
    )
    assert (
        process.returncode == 1
        and "SessionStart" in process.stderr
        and _calls(tmp_path) == []
    )


def test_start_orders_open_then_arrival_reads_and_uses_argument_vectors(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    activity_head = {"lineage": "lineage", "ordinal": 3, "record_hash": "hash-3"}
    responses = {
        "emit": {"ok": True, "result": _receipt()},
        "summary": _read(head=HEAD),
        "facts": _read([_metadata_item()], head=activity_head),
    }
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        responses,
    )
    assert process.returncode == 0, process.stderr
    calls = _calls(tmp_path)
    assert [call[0] for call in calls] == ["emit", "summary", "facts"]
    assert calls[0][1:4] == [
        str(tmp_path / "target with spaces.vertex"),
        "session",
        "--payload-json",
    ]
    assert "--arrival-only" in calls[1]
    assert calls[2][-6:] == [
        "--arrival-only",
        "--metadata-only",
        "--limit",
        "5",
        "--order",
        "newest",
    ]
    context = json.loads(
        json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    assert (
        context["status"] == "open"
        and context["activity"]["items"][0]["id"] == "metadata-id"
    )
    assert "payload" not in context["activity"]["items"][0]
    assert context["activity"]["items"][0]["arrival_ordinal"] == 2
    assert context["activity"]["items"][0]["arrival_seq"] == 0
    assert context["summary"]["basis"] == {
        "lineage": "lineage",
        "captured_head": HEAD,
        "projected_through": HEAD,
        "view_generation": "view",
    }
    assert context["activity"]["basis"] == {
        "lineage": "lineage",
        "captured_head": activity_head,
        "projected_through": activity_head,
        "view_generation": "view",
    }


def test_start_bounds_huge_metadata_with_explicit_omission(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    responses = {
        "emit": {"ok": True, "result": _receipt()},
        "summary": _read(),
        "facts": _read([_metadata_item("x" * 20_000)]),
    }
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        responses,
    )
    assert process.returncode == 0
    context = json.loads(
        json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    assert len(json.dumps(context, ensure_ascii=True, separators=(",", ":"))) < 10_000
    assert context["activity"]["presentation_omitted"] is True


def test_end_never_seals_when_close_is_not_confirmed(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    variants = [
        "INVALID",
        {
            "ok": False,
            "error": {"type": "Refused", "outcome": "refused", "details": {}},
        },
        {"ok": True, "result": {**_receipt(), "stored": False}},
        {"ok": True, "result": {**_receipt(), "witnessed": False}},
        {
            "ok": True,
            "result": {
                key: value for key, value in _receipt().items() if key != "commit"
            },
        },
    ]
    for response in variants:
        process = _run(
            tmp_path,
            "end",
            _config(tmp_path, binary),
            {"hook_event_name": "SessionEnd"},
            {"emit": response},
        )
        assert process.returncode == 1
        diagnostic = _last_diagnostic(process.stderr)
        assert diagnostic["status"] == "close_not_confirmed"
        assert [call[0] for call in _calls(tmp_path)] == ["emit"]
        (tmp_path / "calls.jsonl").unlink()
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": {"ok": True, "result": _receipt()}},
        HOOK_EXIT_EMIT="6",
    )
    assert process.returncode == 1 and [call[0] for call in _calls(tmp_path)] == [
        "emit"
    ]


def test_close_requires_literal_booleans_and_complete_coordinates(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    incomplete_head = {"lineage": "lineage", "ordinal": 2}
    cases = [
        {**_receipt(), "stored": 1},
        {**_receipt(), "witnessed": "true"},
        {**_receipt(), "captured_head": incomplete_head},
        {**_receipt(), "commit": {"before": COMMIT["before"]}},
        {
            **_receipt(),
            "commit": {"before": incomplete_head, "after": COMMIT["after"]},
        },
    ]
    for result in cases:
        process = _run(
            tmp_path,
            "end",
            _config(tmp_path, binary),
            {"hook_event_name": "SessionEnd"},
            {"emit": {"ok": True, "result": result}},
        )
        diagnostic = _last_diagnostic(process.stderr)
        assert process.returncode == 1
        assert diagnostic["status"] == "close_not_confirmed"
        assert [call[0] for call in _calls(tmp_path)] == ["emit"]
        (tmp_path / "calls.jsonl").unlink()


def test_close_rejection_keeps_generated_id_and_partial_commit_evidence(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    result = _receipt("reported-other")
    result["commit"] = {"after": COMMIT["after"]}
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": {"ok": True, "result": result}},
    )
    diagnostic = _last_diagnostic(process.stderr)["close"]
    assert process.returncode == 1 and diagnostic["id"].startswith(
        "claude-session-close-"
    )
    assert diagnostic["id"] != "reported-other"
    assert diagnostic["result"]["id"] == "reported-other"
    assert diagnostic["result"]["commit"] == {"after": COMMIT["after"]}


def test_close_exit_six_retains_sdk_unknown_or_committed_coordinates(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    for outcome in ("unknown", "committed"):
        rejected = {
            "ok": False,
            "error": {
                "type": "Write",
                "outcome": outcome,
                "details": {
                    "id": "reported-error-id",
                    "tick_id": "tick-1",
                    "commit": COMMIT,
                },
            },
        }
        process = _run(
            tmp_path,
            "end",
            _config(tmp_path, binary),
            {"hook_event_name": "SessionEnd"},
            {"emit": rejected},
            HOOK_EXIT_EMIT="6",
        )
        close = _last_diagnostic(process.stderr)["close"]
        assert process.returncode == 1
        assert close["returncode"] == 6 and close["outcome"] == outcome
        assert close["id"].startswith("claude-session-close-")
        assert close["reported_id"] == "reported-error-id"
        assert close["tick_id"] == "tick-1" and close["commit"] == COMMIT
        assert [call[0] for call in _calls(tmp_path)] == ["emit"]
        (tmp_path / "calls.jsonl").unlink()


def test_end_accepts_a_nested_successful_seal_receipt(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    nested_receipt = _receipt()
    nested_receipt.update({"tick_id": "tick-target", "tick_mark": "target"})
    seal = {
        "ok": True,
        "result": {
            "sealed": True,
            "vertex_name": "target",
            "receipt": nested_receipt,
        },
    }
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": {"ok": True, "result": _receipt()}, "seal": seal},
    )
    diagnostics = _diagnostics(process.stderr)
    diagnostic = diagnostics[-1]
    assert process.returncode == 0 and diagnostic["status"] == "sealed"
    assert diagnostics[0]["status"] == "close_confirmed_seal_pending"
    assert diagnostics[0]["close"]["receipt"]["commit"] == COMMIT
    assert diagnostics[0]["seal"]["id"] == diagnostic["seal"]["id"]
    assert diagnostic["seal"]["receipt"]["id"].startswith("claude-session-seal-")
    assert diagnostic["seal"]["receipt"]["commit"] == COMMIT


def test_end_preserves_confirmed_close_when_seal_fails_or_is_false(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    close = {"ok": True, "result": _receipt()}
    false = {
        "ok": True,
        "result": {"sealed": False, "vertex_name": "target", "receipt": _receipt()},
    }
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": close, "seal": false},
    )
    assert process.returncode == 1
    diagnostic = _last_diagnostic(process.stderr)
    assert (
        diagnostic["close"]["receipt"]["commit"] == COMMIT
        and diagnostic["close"]["phase"] == "close"
    )
    assert (
        diagnostic["seal"]["outcome"] == "seal_not_completed"
        and diagnostic["seal"]["phase"] == "seal"
    )
    assert diagnostic["seal"]["result"]["sealed"] is False
    assert diagnostic["seal"]["result"]["receipt"]["commit"] == COMMIT
    assert [call[0] for call in _calls(tmp_path)] == ["emit", "seal"]


def test_invalid_seal_receipts_remain_uncertain(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    receipt = {**_receipt(), "tick_id": "tick-target", "tick_mark": "target"}
    variants = [
        {"sealed": True, "receipt": {**receipt, "commit": None}},
        {"sealed": True, "receipt": {**receipt, "id": "wrong-id"}},
        {"sealed": True, "receipt": {**receipt, "tick_mark": "loop"}},
        {"sealed": "true", "receipt": receipt},
        {"sealed": False, "receipt": {**receipt, "witnessed": False}},
        {"sealed": False, "receipt": receipt},  # Contradicts its own-vertex tick.
    ]
    for variant in variants:
        process = _run(
            tmp_path,
            "end",
            _config(tmp_path, binary),
            {"hook_event_name": "SessionEnd"},
            {
                "emit": {"ok": True, "result": _receipt()},
                "seal": {"ok": True, "result": {"vertex_name": "target", **variant}},
            },
        )
        diagnostic = _last_diagnostic(process.stderr)
        assert process.returncode == 1
        assert diagnostic["status"] == "close_confirmed_seal_unknown_or_failed"
        assert diagnostic["seal"]["outcome"] == "invalid-receipt"
        assert diagnostic["close"]["receipt"]["commit"] == COMMIT
        assert diagnostic["seal"]["result"]["receipt"]["tick_id"] == "tick-target"
        assert [call[0] for call in _calls(tmp_path)] == ["emit", "seal"]
        (tmp_path / "calls.jsonl").unlink()


def test_untyped_seal_failure_has_unknown_outcome(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {
            "emit": {"ok": True, "result": _receipt()},
            "seal": {"ok": False, "error": {"type": "InternalError"}},
        },
        HOOK_EXIT_SEAL="70",
    )
    diagnostic = _last_diagnostic(process.stderr)
    assert process.returncode == 1
    assert diagnostic["status"] == "close_confirmed_seal_unknown_or_failed"
    assert diagnostic["seal"]["outcome"] == "unknown"
    assert diagnostic["seal"]["returncode"] == 70
    assert diagnostic["close"]["receipt"]["commit"] == COMMIT


def test_close_rejection_retains_receipt_coordinates_and_sdk_error_phase(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    rejected = {
        "ok": False,
        "error": {
            "type": "Projection",
            "source_type": "ProjectionFailed",
            "outcome": "unknown",
            "details": {
                "phase": "sdk-seal",
                "fact_id": "fact-1",
                "tick_id": "tick-1",
                "captured_head": HEAD,
                "commit": COMMIT,
            },
        },
    }
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": rejected},
    )
    diagnostic = _last_diagnostic(process.stderr)
    close = diagnostic["close"]
    assert close["phase"] == "close" and close["sdk_phase"] == "sdk-seal"
    assert close["source_type"] == "ProjectionFailed"
    assert close["fact_id"] == "fact-1" and close["tick_id"] == "tick-1"
    assert close["captured_head"] == HEAD and close["commit"] == COMMIT
    assert [call[0] for call in _calls(tmp_path)] == ["emit"]


def test_seal_nonzero_retains_reported_receipt_without_confirming_success(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    seal = {
        "ok": True,
        "result": {"sealed": True, "vertex_name": "target", "receipt": _receipt()},
    }
    process = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": {"ok": True, "result": _receipt()}, "seal": seal},
        HOOK_EXIT_SEAL="9",
    )
    diagnostic = _last_diagnostic(process.stderr)
    assert (
        process.returncode == 1
        and diagnostic["status"] == "close_confirmed_seal_unknown_or_failed"
    )
    assert diagnostic["seal"]["returncode"] == 9
    assert diagnostic["seal"]["outcome"] == "unknown"
    assert diagnostic["seal"]["result"]["receipt"]["commit"] == COMMIT


def test_close_preserved_when_seal_cannot_start_or_decode(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    close = {"ok": True, "result": _receipt()}
    spawned = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": close},
        HOOK_DELETE_AFTER_EMIT="1",
    )
    spawn_diagnostics = _diagnostics(spawned.stderr)
    spawn_diagnostic = spawn_diagnostics[-1]
    assert spawned.returncode == 1 and len(spawn_diagnostics) == 2
    assert spawn_diagnostics[0]["status"] == "close_confirmed_seal_pending"
    assert spawn_diagnostics[0]["close"]["receipt"]["commit"] == COMMIT
    assert spawn_diagnostics[0]["seal"]["id"] == spawn_diagnostic["seal"]["id"]
    assert spawn_diagnostic["close"]["receipt"]["commit"] == COMMIT
    assert (
        spawn_diagnostic["seal"]["outcome"] == "unknown"
        and spawn_diagnostic["seal"]["returncode"] is None
    )
    binary = _binary(tmp_path)
    decoded = _run(
        tmp_path,
        "end",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionEnd"},
        {"emit": close, "seal": "BAD_UTF8"},
        HOOK_EXIT_SEAL="7",
    )
    decode_diagnostic = _last_diagnostic(decoded.stderr)
    assert (
        decoded.returncode == 1
        and decode_diagnostic["close"]["receipt"]["commit"] == COMMIT
    )
    assert decode_diagnostic["seal"]["outcome"] == "invalid-result"
    assert decode_diagnostic["seal"]["returncode"] == 7


def test_post_launch_oserror_never_claims_no_child_effects(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _adapter_module()
    config_values = _config(tmp_path, _binary(tmp_path), stop_nudge=False)
    config_values.pop("enabled")
    config = module.Config(**config_values)
    monkeypatch.setattr(module, "_event", lambda _event_name: {})
    calls = []

    def communicate_failure(arguments, **_kwargs):
        calls.append(arguments[1])
        if arguments[1] == "emit":
            request_id = arguments[arguments.index("--id") + 1]
            raw = json.dumps({"ok": True, "result": _receipt(request_id)}).encode()
            return subprocess.CompletedProcess(arguments, 0, raw, b"")
        # A fault while communicating can occur after the seal child has written.
        raise OSError("communication failed after child launch")

    monkeypatch.setattr(module.subprocess, "run", communicate_failure)
    assert module._end(config) == 1
    diagnostic = _last_diagnostic(capsys.readouterr().err)
    assert calls == ["emit", "seal"]
    assert diagnostic["close"]["receipt"]["commit"] == COMMIT
    assert diagnostic["seal"]["outcome"] == "unknown"
    assert diagnostic["seal"]["returncode"] is None


def test_start_partial_has_context_and_diagnostic_after_opened_read_failure(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {"emit": {"ok": True, "result": _receipt()}, "summary": "BAD_UTF8"},
    )
    envelope = json.loads(process.stdout)
    output = envelope["hookSpecificOutput"]
    diagnostics = process.stderr.splitlines()
    diagnostic = json.loads(diagnostics[0])
    context = json.loads(output["additionalContext"])
    assert process.returncode == 1
    assert envelope["systemMessage"].startswith("Arrival session opened")
    assert "systemMessage" not in output and len(diagnostics) == 1
    assert context["open"]["commit"] == COMMIT
    assert (
        diagnostic["open"]["commit"] == COMMIT
        and diagnostic["read_error"]["returncode"] == 0
    )


def test_start_after_open_read_spawn_failure_is_partial_without_retry(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {"emit": {"ok": True, "result": _receipt()}},
        HOOK_DELETE_AFTER_EMIT="1",
    )
    envelope = json.loads(process.stdout)
    diagnostic = _last_diagnostic(process.stderr)
    context = json.loads(envelope["hookSpecificOutput"]["additionalContext"])
    assert process.returncode == 1 and envelope["systemMessage"]
    assert context["open"]["commit"] == COMMIT
    assert diagnostic["read_error"]["outcome"] == "unknown"
    assert [call[0] for call in _calls(tmp_path)] == ["emit"]


def test_invalid_summary_preserves_basis_and_prevents_activity_read(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    summary = _read()
    summary["result"]["fact_total"] = "invalid"
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {"emit": {"ok": True, "result": _receipt()}, "summary": summary},
    )
    context = json.loads(
        json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    assert process.returncode == 1
    assert context["summary"]["basis"]["captured_head"] == HEAD
    assert context["summary"]["store"]["backend"] == "file"
    assert [call[0] for call in _calls(tmp_path)] == ["emit", "summary"]


def test_context_does_not_forward_nested_identity_extensions(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    summary = _read()
    summary["result"]["runtime_epoch"]["mode"] = {"payload": "hidden"}
    summary["result"]["store"]["lineage"] = {"payload": "hidden"}
    summary["result"]["basis"]["view_generation"] = {"payload": "hidden"}
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {
            "emit": {"ok": True, "result": _receipt()},
            "summary": summary,
            "facts": _read(),
        },
    )
    assert process.returncode == 0
    assert "hidden" not in process.stdout and "payload" not in process.stdout


def test_activity_rejects_invalid_metadata_page_guards(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    invalid_results = []
    metadata_flag = _read([_metadata_item()])
    metadata_flag["result"]["metadata_only"] = False
    invalid_results.append(metadata_flag)
    wrong_order = _read([_metadata_item()])
    wrong_order["result"]["order"] = "oldest"
    invalid_results.append(wrong_order)
    bad_truncation = _read([_metadata_item()])
    bad_truncation["result"]["truncated"] = "false"
    invalid_results.append(bad_truncation)
    too_many = _read([_metadata_item(str(number), 10 - number) for number in range(6)])
    invalid_results.append(too_many)
    string_timestamp = _read([_metadata_item()])
    string_timestamp["result"]["items"][0]["ts"] = "2026-01-01T00:00:00Z"
    invalid_results.append(string_timestamp)
    overflowing_timestamp = _read([_metadata_item()])
    overflowing_timestamp["result"]["items"][0]["ts"] = 10**400
    invalid_results.append(overflowing_timestamp)
    payload_present = _read([_metadata_item()])
    payload_present["result"]["items"][0]["payload"] = {"secret": "not forwarded"}
    invalid_results.append(payload_present)
    wrong_position = _read([_metadata_item("new", 2), _metadata_item("old", 3)])
    invalid_results.append(wrong_position)
    for bad in invalid_results:
        process = _run(
            tmp_path,
            "start",
            _config(tmp_path, binary),
            {"hook_event_name": "SessionStart"},
            {
                "emit": {"ok": True, "result": _receipt()},
                "summary": _read(),
                "facts": bad,
            },
        )
        context = json.loads(
            json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
        )
        assert process.returncode == 1
        assert context["status"] == "partial"
        assert context["read_error"]["phase"] == "facts"
        (tmp_path / "calls.jsonl").unlink()


def test_activity_accepts_sdk_empty_origin_and_discards_scalar_extensions(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    item = _metadata_item()
    item.update({"origin": "", "future_scalar": "kept-compatible", "future_null": None})
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {
            "emit": {"ok": True, "result": _receipt()},
            "summary": _read(),
            "facts": _read([item]),
        },
    )
    context = json.loads(
        json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    activity = context["activity"]["items"][0]
    assert process.returncode == 0
    assert activity["origin"] == "" and "future_scalar" not in activity
    assert "future_null" not in activity


def test_oversized_required_evidence_refuses_stdout_but_retains_open(
    tmp_path: Path,
) -> None:
    binary = _binary(tmp_path)
    huge_head = {"lineage": "lineage", "ordinal": 2, "record_hash": "x" * 10_000}
    receipt = _receipt()
    receipt["captured_head"] = huge_head
    receipt["commit"] = {"before": COMMIT["before"], "after": huge_head}
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary),
        {"hook_event_name": "SessionStart"},
        {
            "emit": {"ok": True, "result": receipt},
            "summary": _read(),
            "facts": _read(),
        },
    )
    diagnostic = _last_diagnostic(process.stderr)
    assert process.returncode == 1 and not process.stdout
    assert diagnostic["status"] == "start_open_confirmed_presentation_refused"
    assert diagnostic["open"]["commit"]["after"] == huge_head


def test_context_uses_utf16_safe_ascii_json(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    astral = "😀" * 500
    process = _run(
        tmp_path,
        "start",
        _config(tmp_path, binary, target=str(tmp_path / astral)),
        {"hook_event_name": "SessionStart"},
        {
            "emit": {"ok": True, "result": _receipt()},
            "summary": _read(),
            "facts": _read([_metadata_item()]),
        },
    )
    assert process.returncode == 0
    rendered = json.loads(process.stdout)["hookSpecificOutput"]["additionalContext"]
    assert len(rendered.encode("utf-16-le")) // 2 < 10_000


def test_stop_default_active_invalid_and_no_transcript_io(tmp_path: Path) -> None:
    binary = _binary(tmp_path)
    default = _run(tmp_path, "stop", _config(tmp_path, binary), b"\xff")
    assert default.returncode == 0 and not default.stdout and _calls(tmp_path) == []

    config = _config(tmp_path, binary, stop_nudge=True)
    event = {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": "done",
        "transcript_path": str(tmp_path / "does-not-exist"),
    }
    process = _run(tmp_path, "stop", config, event)
    assert process.returncode == 0
    assert "continues the conversation" in process.stdout and _calls(tmp_path) == []
    active = _run(tmp_path, "stop", config, {**event, "stop_hook_active": True})
    assert active.returncode == 0 and not active.stdout
    invalid = _run(tmp_path, "stop", config, {**event, "stop_hook_active": "false"})
    assert invalid.returncode == 1 and "must be a boolean" in invalid.stderr


def test_real_loops_min_lifecycle_seals_an_own_vertex_tick(tmp_path: Path) -> None:
    """The adapter's process boundary works against a disposable Arrival target."""
    console = Path(sys.executable).with_name("loops-min")
    assert console.is_file(), "CI must provide loops-min for this lifecycle coverage"
    environment = _environment(tmp_path)
    environment.pop("HOOK_LOG")
    custody, target, ledger = (
        tmp_path / "custody",
        tmp_path / "target.vertex",
        tmp_path / "target.arrival",
    )

    def console_run(*args: str) -> dict:
        process = subprocess.run(
            [str(console), *args],
            text=True,
            capture_output=True,
            env=environment,
            check=False,
        )
        assert process.returncode == 0, process.stdout + process.stderr
        return json.loads(process.stdout)

    credentials = [
        "--credential-root",
        str(custody),
        "--credential-namespace",
        "tenant",
        "--receipt-observer",
        "alice",
    ]
    console_run(
        "credential-create",
        str(custody),
        "--namespace",
        "tenant",
        "--observer",
        "alice",
        "--token",
        "adapter-test",
    )
    console_run(
        "init",
        str(target),
        "--name",
        "adapter-target",
        "--location",
        str(ledger),
        "--observer",
        "alice",
        *credentials,
    )
    current = target.read_text(encoding="utf-8")
    proposal = tmp_path / "with-boundary.vertex"
    proposal.write_text(
        current[:-2]
        + '  session { fold { items "by" "name" } }\n  boundary when="seal"\n}\n',
        encoding="utf-8",
    )
    console_run(
        "declaration",
        str(target),
        "--proposed-file",
        str(proposal),
        "--observer",
        "alice",
        *credentials,
    )
    config = _config(
        tmp_path,
        console,
        target=str(target),
        credential_root=str(custody),
        credential_namespace="tenant",
        observer="alice",
        receipt_observer="alice",
    )
    start = _run(tmp_path, "start", config, {"hook_event_name": "SessionStart"})
    assert start.returncode == 0, start.stderr
    start_context = json.loads(
        json.loads(start.stdout)["hookSpecificOutput"]["additionalContext"]
    )
    assert start_context["activity"]["items"][0]["origin"] == ""
    assert start_context["open"]["signed"] is True
    end = _run(tmp_path, "end", config, {"hook_event_name": "SessionEnd"})
    assert end.returncode == 0, end.stderr
    receipt = _last_diagnostic(end.stderr)
    assert receipt["seal"]["vertex_name"] == "adapter-target"
    assert receipt["close"]["receipt"]["signed"] is True
    assert receipt["seal"]["receipt"]["signed"] is True
    assert (
        receipt["seal"]["tick_mark"] == "adapter-target" and receipt["seal"]["tick_id"]
    )
    assert console_run("verify", str(target))["result"]["level"] == "full"
