#!/usr/bin/env python3
"""Explicit Arrival-backed Claude Code session hooks.

The selected configuration is the only source of target, binary, and identity.
There is deliberately no discovery, SDK import, fallback binary, or retry path.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_CONFIG_ENV = "LOOPS_CLAUDE_HOOK_CONFIG"
_ALLOWED = {
    "enabled",
    "binary",
    "target",
    "credential_root",
    "credential_namespace",
    "observer",
    "receipt_observer",
    "stop_nudge",
}
_MAX_CONTEXT = 9_500  # Claude's additionalContext cap is 10,000 UTF-16 units.
_MAX_MESSAGE = 500


class HookError(Exception):
    pass


@dataclass(frozen=True)
class RunResult:
    """One child outcome; a missing result does not prove the child never started."""

    process: subprocess.CompletedProcess[bytes] | None
    response: dict[str, Any] | None
    parse_error: str | None
    run_error: str | None = None

    @property
    def returncode(self) -> int | None:
        return None if self.process is None else self.process.returncode

    @property
    def ok(self) -> bool:
        """A successful process envelope; callers must still validate its evidence."""
        return (
            self.returncode == 0
            and self.run_error is None
            and self.parse_error is None
            and self.response is not None
            and self.response.get("ok") is True
        )


@dataclass(frozen=True)
class Config:
    binary: str
    target: str
    credential_root: str
    credential_namespace: str
    observer: str
    receipt_observer: str
    stop_nudge: bool


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HookError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _nonfinite(value: str) -> None:
    raise HookError(f"non-finite JSON number {value!r}")


def _load_json(text: str, what: str) -> dict[str, Any]:
    try:
        value = json.loads(
            text, object_pairs_hook=_no_duplicates, parse_constant=_nonfinite
        )
        json.dumps(value, allow_nan=False)
    except HookError:
        raise
    except (TypeError, ValueError) as exc:
        raise HookError(f"{what} is not valid finite JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise HookError(f"{what} must be a JSON object")
    return value


def _message(value: object) -> str:
    """Keep human text useful without copying child data into diagnostics."""
    text = str(value).replace("\x00", "\\0").replace("\n", " ")
    return text[: _MAX_MESSAGE - 1] + "…" if len(text) > _MAX_MESSAGE else text


def _config() -> Config | None:
    selected = os.environ.get(_CONFIG_ENV)
    # This is intentionally before stdin, target, custody, or child-process IO.
    if not selected:
        return None
    if "\x00" in selected or not os.path.isabs(selected):
        raise HookError(f"{_CONFIG_ENV} must be an absolute JSON path")
    try:
        text = Path(selected).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise HookError(f"cannot read {_CONFIG_ENV}: {_message(exc)}") from exc
    if "\x00" in text:
        raise HookError("hook configuration contains a NUL byte")
    raw = _load_json(text, "hook configuration")
    unknown = set(raw) - _ALLOWED
    if unknown:
        raise HookError(
            f"hook configuration has unknown keys: {', '.join(sorted(unknown))}"
        )
    if "enabled" not in raw or type(raw["enabled"]) is not bool:
        raise HookError("hook configuration enabled must be a boolean")
    # A disabled selected config is intentionally not interpreted beyond its own JSON.
    if raw["enabled"] is False:
        return None
    required = (
        "binary",
        "target",
        "credential_root",
        "credential_namespace",
        "observer",
        "receipt_observer",
    )
    missing = [
        name
        for name in required
        if not isinstance(raw.get(name), str) or not raw[name] or "\x00" in raw[name]
    ]
    if missing:
        raise HookError(
            f"enabled hook configuration requires nonempty strings: {', '.join(missing)}"
        )
    for name in ("binary", "target", "credential_root"):
        if not os.path.isabs(raw[name]):
            raise HookError(f"hook configuration {name} must be an absolute path")
    if "stop_nudge" in raw and type(raw["stop_nudge"]) is not bool:
        raise HookError("hook configuration stop_nudge must be a boolean")
    return Config(
        binary=raw["binary"],
        target=raw["target"],
        credential_root=raw["credential_root"],
        credential_namespace=raw["credential_namespace"],
        observer=raw["observer"],
        receipt_observer=raw["receipt_observer"],
        stop_nudge=raw.get("stop_nudge", False),
    )


def _event(expected: str) -> dict[str, Any]:
    try:
        binary_stdin = getattr(sys.stdin, "buffer", None)
        event_text = (
            binary_stdin.read().decode("utf-8")
            if binary_stdin is not None
            else sys.stdin.read()
        )
    except UnicodeError as exc:
        raise HookError(f"hook event is not valid UTF-8: {_message(exc)}") from exc
    raw = _load_json(event_text, "hook event")
    if raw.get("hook_event_name") != expected:
        raise HookError(f"hook event_name must be {expected!r}")
    return raw


def _request_id(phase: str) -> str:
    return f"claude-session-{phase}-{uuid.uuid4()}"


def _run(config: Config, command: str, *arguments: str) -> RunResult:
    """Capture bytes so decode errors retain the completed child's return code."""
    try:
        process = subprocess.run(
            [config.binary, command, config.target, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        return RunResult(
            None, None, None, f"loops-min {command} process failed: {_message(exc)}"
        )
    try:
        stdout = process.stdout.decode("utf-8")
    except UnicodeError:
        return RunResult(
            process, None, f"loops-min {command} stdout is not valid UTF-8"
        )
    try:
        response = _load_json(stdout, f"loops-min {command} stdout")
    except HookError as exc:
        return RunResult(process, None, _message(exc))
    return RunResult(process, response, None)


def _head(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HookError("missing or malformed Arrival head")
    lineage, ordinal, record_hash = (
        value.get("lineage"),
        value.get("ordinal"),
        value.get("record_hash"),
    )
    if (
        not isinstance(lineage, str)
        or not lineage
        or type(ordinal) is not int
        or ordinal < 0
        or not isinstance(record_hash, str)
        or not record_hash
    ):
        raise HookError("missing or malformed Arrival head")
    return {"lineage": lineage, "ordinal": ordinal, "record_hash": record_hash}


def _commit(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise HookError("missing or malformed Arrival commit evidence")
    return {"before": _head(value.get("before")), "after": _head(value.get("after"))}


def _commit_evidence(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    evidence: dict[str, Any] = {}
    for side in ("before", "after"):
        try:
            evidence[side] = _head(value.get(side))
        except HookError:
            pass
    return evidence or None


def _scalar(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int or type(value) is float:
        return value
    return None


def _store_evidence(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    store = {
        key: _scalar(value.get(key))
        for key in ("backend", "location", "lineage", "role")
    }
    return {key: item for key, item in store.items() if item is not None}


def _receipt_evidence(value: Any) -> dict[str, Any] | None:
    """Extract reconciliation coordinates before deciding whether they prove success."""
    if not isinstance(value, Mapping):
        return None
    evidence: dict[str, Any] = {}
    for key in ("id", "fact_id", "tick_id", "tick_mark"):
        item = _scalar(value.get(key))
        if item is not None:
            evidence[key] = item
    for key in ("stored", "witnessed", "signed"):
        if type(value.get(key)) is bool:
            evidence[key] = value[key]
    store = _store_evidence(value.get("store"))
    if store is not None:
        evidence["store"] = store
    try:
        evidence["captured_head"] = _head(value.get("captured_head"))
    except HookError:
        pass
    commit = _commit_evidence(value.get("commit"))
    if commit is not None:
        evidence["commit"] = commit
    return evidence or None


def _receipt(response: dict[str, Any], request_id: str) -> dict[str, Any]:
    if response.get("ok") is not True or not isinstance(
        response.get("result"), Mapping
    ):
        raise HookError("loops-min did not report ok:true receipt")
    result = response["result"]
    if result.get("write_path") != "arrival" or not isinstance(
        result.get("store"), Mapping
    ):
        raise HookError("receipt does not confirm the Arrival write path and store")
    if result.get("id") != request_id or not isinstance(result.get("id"), str):
        raise HookError("receipt id is absent or does not match this invocation")
    if result.get("stored") is not True or result.get("witnessed") is not True:
        raise HookError("receipt is not witnessed and stored")
    evidence = _receipt_evidence(result)
    if evidence is None:
        raise HookError("receipt has no usable identity evidence")
    # These strict checks also ensure a successful receipt carries both heads.
    evidence["captured_head"] = _head(result.get("captured_head"))
    evidence["commit"] = _commit(result.get("commit"))
    return evidence


def _basis_and_store(
    result: Any, operation: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(result, Mapping) or result.get("read_path") != "arrival":
        raise HookError(f"{operation} did not confirm the Arrival read path")
    basis = result.get("basis")
    store = result.get("store")
    if not isinstance(basis, Mapping) or not isinstance(store, Mapping):
        raise HookError(f"{operation} did not include Arrival basis and store")
    # Retain only stable custody/store identity, never an arbitrary read payload.
    compact_basis = {
        "lineage": basis.get("lineage"),
        "captured_head": _head(basis.get("captured_head")),
        "projected_through": _head(basis.get("projected_through")),
        "view_generation": _scalar(basis.get("view_generation")),
    }
    if not isinstance(compact_basis["lineage"], str) or not compact_basis["lineage"]:
        raise HookError(f"{operation} has malformed Arrival basis")
    compact_store = {
        key: _scalar(store.get(key))
        for key in ("backend", "location", "lineage", "role")
    }
    if (
        not isinstance(compact_store["backend"], str)
        or not compact_store["backend"]
        or not isinstance(compact_store["location"], str)
        or not compact_store["location"]
    ):
        raise HookError(f"{operation} has malformed Arrival store")
    return compact_basis, compact_store


def _copy_error_coordinates(detail: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key in (
        "fact_id",
        "tick_id",
        "tick_mark",
        "ordinal",
        "lineage",
        "observer",
        "vertex",
    ):
        value = _scalar(source.get(key))
        if value is not None:
            detail[key] = value
    reported_id = _scalar(source.get("id"))
    if reported_id is not None:
        detail["reported_id"] = reported_id
    for key in (
        "captured_head",
        "head",
        "projected_head",
        "projected_before",
        "observed_after",
    ):
        try:
            detail[key] = _head(source.get(key))
        except HookError:
            pass
    commit = _commit_evidence(source.get("commit"))
    if commit is not None:
        detail["commit"] = commit


def _operation_error(phase: str, request_id: str, run: RunResult) -> dict[str, Any]:
    """Return structured, payload-free evidence for any child outcome."""
    detail: dict[str, Any] = {"phase": phase, "returncode": run.returncode}
    if request_id:
        detail["id"] = request_id
    if run.run_error:
        # subprocess.run can raise during communication after launching the child.
        # Without a returned process result, do not claim absence of durable effects.
        detail.update({"outcome": "unknown", "error": run.run_error})
        return detail
    if run.parse_error:
        detail.update({"outcome": "invalid-result", "error": run.parse_error})
        return detail
    if run.response is None:
        detail["outcome"] = "unknown"
        return detail
    error = run.response.get("error")
    if isinstance(error, Mapping):
        outcome = _scalar(error.get("outcome"))
        detail["outcome"] = outcome if isinstance(outcome, str) else "unknown"
        for source_key, target_key in (
            ("type", "error_type"),
            ("source_type", "source_type"),
        ):
            value = _scalar(error.get(source_key))
            if value is not None:
                detail[target_key] = value
        details = error.get("details")
        if isinstance(details, Mapping):
            _copy_error_coordinates(detail, details)
            sdk_phase = _scalar(details.get("phase"))
            if sdk_phase is not None:
                detail["sdk_phase"] = sdk_phase
            source_type = _scalar(details.get("source_type"))
            if source_type is not None:
                detail["source_type"] = source_type
    else:
        detail["outcome"] = "unknown"
    result = run.response.get("result")
    if isinstance(result, Mapping):
        receipt = _receipt_evidence(result)
        if receipt is not None:
            detail["result"] = receipt
    return detail


def _seal_result_evidence(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep selected seal identities even when the receipt does not prove success."""
    if not isinstance(response, Mapping) or not isinstance(
        response.get("result"), Mapping
    ):
        return None
    result = response["result"]
    evidence: dict[str, Any] = {}
    if type(result.get("sealed")) is bool:
        evidence["sealed"] = result["sealed"]
    vertex_name = _scalar(result.get("vertex_name"))
    if vertex_name is not None:
        evidence["vertex_name"] = vertex_name
    receipt = _receipt_evidence(result.get("receipt"))
    if receipt is not None:
        evidence["receipt"] = receipt
        for key in ("tick_id", "tick_mark"):
            if key in receipt:
                evidence[key] = receipt[key]
    return evidence or None


def _emit(config: Config, status: str, request_id: str) -> RunResult:
    return _run(
        config,
        "emit",
        "session",
        "--payload-json",
        json.dumps({"name": config.observer, "status": status}, separators=(",", ":")),
        "--observer",
        config.observer,
        "--credential-root",
        config.credential_root,
        "--credential-namespace",
        config.credential_namespace,
        "--receipt-observer",
        config.receipt_observer,
        "--id",
        request_id,
    )


def _context(data: dict[str, Any]) -> str:
    # ASCII JSON makes Python's length exactly the host's UTF-16 string length.
    rendered = json.dumps(
        data, ensure_ascii=True, separators=(",", ":"), allow_nan=False
    )
    if len(rendered) > _MAX_CONTEXT:
        raise HookError(
            "required session evidence exceeds the hook presentation bound; no evidence was clipped"
        )
    return rendered


def _start_output(data: dict[str, Any], *, warning: bool = False) -> None:
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _context(data),
        }
    }
    if warning:
        output["systemMessage"] = (
            "Arrival session opened; orientation is incomplete. Check hook diagnostics."
        )
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":"), allow_nan=False))


def _stderr(data: dict[str, Any]) -> None:
    print(
        json.dumps(data, ensure_ascii=True, separators=(",", ":"), allow_nan=False),
        file=sys.stderr,
        flush=True,
    )


def _summary_presentation(result: Mapping[str, Any]) -> dict[str, Any]:
    name, facts, ticks, epoch = (
        result.get("vertex_name"),
        result.get("fact_total"),
        result.get("tick_total"),
        result.get("runtime_epoch"),
    )
    if (
        not isinstance(name, str)
        or not name
        or type(facts) is not int
        or facts < 0
        or type(ticks) is not int
        or ticks < 0
        or not isinstance(epoch, Mapping)
    ):
        raise HookError("summary lacks valid name, counts, or runtime epoch")
    return {
        "name": name,
        "fact_total": facts,
        "tick_total": ticks,
        "runtime_epoch": {
            "mode": _scalar(epoch.get("mode")),
            "anchor_ordinal": _scalar(epoch.get("anchor_ordinal")),
        },
    }


def _activity(result: Mapping[str, Any]) -> dict[str, Any]:
    items = result.get("items")
    if result.get("metadata_only") is not True or result.get("order") != "newest":
        raise HookError("facts result did not honor metadata-only newest-page request")
    if (
        type(result.get("truncated")) is not bool
        or not isinstance(items, list)
        or len(items) > 5
    ):
        raise HookError("facts metadata result is not a bounded page")
    required = (
        "id",
        "kind",
        "ts",
        "observer",
        "origin",
        "arrival_ordinal",
        "arrival_seq",
    )
    required_set = set(required)
    metadata: list[dict[str, Any]] = []
    previous: tuple[int, int] | None = None
    for item in items:
        if (
            not isinstance(item, Mapping)
            or not required_set.issubset(item)
            or "payload" in item
        ):
            raise HookError("facts metadata item has an invalid envelope")
        # Future scalar envelope fields are compatible but are not presented.
        if any(
            key not in required_set and value is not None and _scalar(value) is None
            for key, value in item.items()
        ):
            raise HookError("facts metadata item has an invalid envelope")
        if not all(
            isinstance(item[key], str) and item[key]
            for key in ("id", "kind", "observer")
        ):
            raise HookError("facts metadata item has invalid identity")
        if not isinstance(item["origin"], str):
            raise HookError("facts metadata item has invalid identity")
        timestamp = item["ts"]
        try:
            finite_timestamp = type(timestamp) in (int, float) and math.isfinite(
                timestamp
            )
        except OverflowError:
            finite_timestamp = False
        if not finite_timestamp:
            raise HookError("facts metadata item has invalid timestamp")
        position = (item["arrival_ordinal"], item["arrival_seq"])
        if any(type(value) is not int or value < 0 for value in position):
            raise HookError("facts metadata item has invalid Arrival position")
        if previous is not None and position >= previous:
            raise HookError("facts metadata page is not newest first")
        previous = position
        metadata.append({key: item[key] for key in required})
    return {
        "items": metadata,
        "truncated": result["truncated"],
        "presentation_omitted": False,
    }


def _partial_start(base: dict[str, Any]) -> int:
    """Present partial context when possible, while stderr remains reconciliable."""
    try:
        _start_output(base, warning=True)
    except HookError as exc:
        _stderr(
            {
                "status": "start_open_confirmed_presentation_refused",
                "open": base["open"],
                "error": _message(exc),
            }
        )
        return 1
    _stderr(
        {
            "status": "start_open_confirmed_orientation_incomplete",
            "open": base["open"],
            "read_error": base["read_error"],
        }
    )
    return 1


def _start(config: Config) -> int:
    _event("SessionStart")
    open_id = _request_id("open")
    open_run = _emit(config, "open", open_id)
    if not open_run.ok:
        _stderr(
            {
                "status": "open_not_confirmed",
                "open": _operation_error("open", open_id, open_run),
            }
        )
        return 1
    try:
        opened = _receipt(open_run.response, open_id)  # type: ignore[arg-type]
    except HookError as exc:
        rejected = _operation_error("open", open_id, open_run)
        rejected.update({"outcome": "invalid-receipt", "error": _message(exc)})
        _stderr({"status": "open_not_confirmed", "open": rejected})
        return 1

    base: dict[str, Any] = {
        "status": "partial",
        "open": opened,
        "target": config.target,
    }
    summary_run = _run(config, "summary", "--arrival-only")
    if not summary_run.ok:
        base["read_error"] = _operation_error("summary", "", summary_run)
        return _partial_start(base)
    try:
        summary, summary_store = _basis_and_store(
            summary_run.response["result"], "summary"
        )
        base["summary"] = {"basis": summary, "store": summary_store}
        base["summary"].update(_summary_presentation(summary_run.response["result"]))
    except (HookError, KeyError) as exc:
        base["read_error"] = {
            "phase": "summary",
            "outcome": "invalid-result",
            "error": _message(exc),
        }
        return _partial_start(base)
    facts_run = _run(
        config,
        "facts",
        "--arrival-only",
        "--metadata-only",
        "--limit",
        "5",
        "--order",
        "newest",
    )
    if not facts_run.ok:
        base["read_error"] = _operation_error("facts", "", facts_run)
        return _partial_start(base)
    try:
        facts, facts_store = _basis_and_store(facts_run.response["result"], "facts")
        activity = _activity(facts_run.response["result"])
    except (HookError, KeyError) as exc:
        base["read_error"] = {
            "phase": "facts",
            "outcome": "invalid-result",
            "error": _message(exc),
        }
        return _partial_start(base)
    base.update(
        {
            "status": "open",
            "activity": {"basis": facts, "store": facts_store, **activity},
            "snapshot_note": "summary and activity carry their own read bases; no common snapshot is claimed",
        }
    )
    try:
        _start_output(base)
    except HookError:
        # Optional metadata is the first presentation data omitted, never clipped.
        base["activity"] = {
            "basis": facts,
            "store": facts_store,
            "presentation_omitted": True,
            "omission": "activity metadata omitted to fit hook context bound",
        }
        try:
            _start_output(base)
        except HookError as exc:
            _stderr(
                {
                    "status": "start_open_confirmed_presentation_refused",
                    "open": opened,
                    "error": _message(exc),
                }
            )
            return 1
    return 0


def _end(config: Config) -> int:
    _event("SessionEnd")
    close_id = _request_id("close")
    close_run = _emit(config, "closed", close_id)
    if not close_run.ok:
        _stderr(
            {
                "status": "close_not_confirmed",
                "close": _operation_error("close", close_id, close_run),
            }
        )
        return 1
    try:
        closed = _receipt(close_run.response, close_id)  # type: ignore[arg-type]
    except HookError as exc:
        rejected = _operation_error("close", close_id, close_run)
        rejected.update({"outcome": "invalid-receipt", "error": _message(exc)})
        _stderr({"status": "close_not_confirmed", "close": rejected})
        return 1
    close_evidence = {
        "phase": "close",
        "id": close_id,
        "returncode": close_run.returncode,
        "outcome": "confirmed",
        "receipt": closed,
    }
    seal_id = _request_id("seal")
    _stderr(
        {
            "status": "close_confirmed_seal_pending",
            "close": close_evidence,
            "seal": {"phase": "seal", "id": seal_id, "outcome": "pending"},
        }
    )
    seal_run = _run(
        config,
        "seal",
        "--payload-json",
        "{}",
        "--observer",
        config.observer,
        "--credential-root",
        config.credential_root,
        "--credential-namespace",
        config.credential_namespace,
        "--receipt-observer",
        config.receipt_observer,
        "--id",
        seal_id,
    )
    diagnostic: dict[str, Any] = {
        "close": close_evidence,
        "seal": _operation_error("seal", seal_id, seal_run),
    }
    seal_evidence = _seal_result_evidence(seal_run.response)
    if seal_evidence is not None:
        diagnostic["seal"]["result"] = seal_evidence
    if not seal_run.ok:
        diagnostic["status"] = "close_confirmed_seal_unknown_or_failed"
        _stderr(diagnostic)
        return 1
    try:
        if seal_run.response.get("ok") is not True or not isinstance(
            seal_run.response.get("result"), Mapping
        ):
            raise HookError("loops-min did not report ok:true seal")
        seal_result = seal_run.response["result"]
        nested = _receipt({"ok": True, "result": seal_result.get("receipt")}, seal_id)
        vertex_name = seal_result.get("vertex_name")
        receipt = seal_result.get("receipt")
        if (
            not isinstance(vertex_name, str)
            or not vertex_name
            or not isinstance(receipt, Mapping)
            or type(seal_result.get("sealed")) is not bool
        ):
            raise HookError("malformed seal result")
        own_tick = (
            isinstance(receipt.get("tick_id"), str)
            and bool(receipt["tick_id"])
            and receipt.get("tick_mark") == vertex_name
        )
        if seal_result["sealed"] != own_tick:
            raise HookError("seal result contradicts its own-vertex tick evidence")
    except HookError as exc:
        diagnostic["status"] = "close_confirmed_seal_unknown_or_failed"
        diagnostic["seal"].update(
            {"outcome": "invalid-receipt", "error": _message(exc)}
        )
        _stderr(diagnostic)
        return 1
    if seal_result["sealed"] is False:
        diagnostic["status"] = "close_confirmed_seal_not_completed"
        diagnostic["seal"]["outcome"] = "seal_not_completed"
        _stderr(diagnostic)
        return 1
    _stderr(
        {
            "status": "sealed",
            "close": close_evidence,
            "seal": {
                "phase": "seal",
                "id": seal_id,
                "outcome": "sealed",
                "receipt": nested,
                "vertex_name": vertex_name,
                "tick_id": receipt["tick_id"],
                "tick_mark": receipt["tick_mark"],
                "returncode": seal_run.returncode,
            },
        }
    )
    return 0


def _stop(config: Config) -> int:
    if not config.stop_nudge:
        return 0
    event = _event("Stop")
    if type(event.get("stop_hook_active")) is not bool:
        raise HookError("Stop event stop_hook_active must be a boolean")
    message = event.get("last_assistant_message")
    if event["stop_hook_active"] or not isinstance(message, str) or not message.strip():
        return 0
    reminder = "Before continuing, capture any relevant durable finding if one emerged; this reminder continues the conversation."
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "additionalContext": reminder,
                }
            },
            separators=(",", ":"),
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in {"start", "end", "stop"}:
        print("usage: arrival_session.py start|end|stop", file=sys.stderr)
        return 2
    try:
        config = _config()
        if config is None:
            return 0
        return {"start": _start, "end": _end, "stop": _stop}[argv[0]](config)
    except (HookError, OSError, UnicodeError, ValueError) as exc:
        _stderr(
            {
                "status": "hook_error",
                "error": {"outcome": "invalid-input", "message": _message(exc)},
            }
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
