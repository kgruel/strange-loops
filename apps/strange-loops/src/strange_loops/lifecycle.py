"""Compiled vertex loader + Spec-based fold for task state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine import CompiledVertex, compile_vertex_recursive
from lang import parse_vertex_file

# Module-level cache — CLI is short-lived, compile once per invocation.
_compiled: CompiledVertex | None = None

# Package root: apps/strange-loops/
_PKG_ROOT = Path(__file__).resolve().parent.parent.parent


def _vertex_path() -> Path:
    """Resolve loops/tasks.vertex relative to the app root."""
    return _PKG_ROOT / "loops" / "tasks.vertex"


def load_compiled() -> CompiledVertex:
    """Parse + compile tasks.vertex, cached."""
    global _compiled  # noqa: PLW0603
    if _compiled is None:
        vertex = parse_vertex_file(_vertex_path())
        _compiled = compile_vertex_recursive(vertex)
    return _compiled


def _fold_all_specs(reader: Any) -> dict[str, dict]:
    """Fold all facts through compiled specs. Returns {kind: folded_state}."""
    compiled = load_compiled()
    all_facts = reader.facts_between(0, float("inf"))

    by_kind: dict[str, list[dict]] = {}
    for f in all_facts:
        by_kind.setdefault(f["kind"], []).append(f)

    states: dict[str, dict] = {}
    for kind, spec in compiled.specs.items():
        state = spec.initial_state()
        for fact in by_kind.get(kind, []):
            state = spec.apply(state, fact["payload"])
        states[kind] = state

    return states


def _extract_task(states: dict[str, dict], name: str) -> dict | None:
    """Extract a single task's state from folded specs."""
    created = states.get("task.created", {}).get("items", {}).get(name)
    if created is None:
        return None

    result: dict[str, Any] = {"name": name}
    result["title"] = created.get("title", "")
    result["base_branch"] = created.get("base_branch", "")
    result["description"] = created.get("description", "")

    assigned = states.get("task.assigned", {}).get("items", {}).get(name)
    if assigned:
        result["harness"] = assigned.get("harness", "")
        result["worktree"] = assigned.get("worktree", "")

    # Status: task.stage overrides completion/merge/assign/create
    stage = states.get("task.stage", {}).get("items", {}).get(name)
    completed = states.get("task.completed", {}).get("items", {}).get(name)
    merged = states.get("task.merged", {}).get("items", {}).get(name)

    if stage:
        result["status"] = stage.get("status", "")
    elif completed:
        result["status"] = "completed"
    elif merged:
        result["status"] = "merged"
    elif assigned:
        result["status"] = "assigned"
    else:
        result["status"] = "created"

    # Worker PID from worker.started
    ws = states.get("worker.started", {}).get("items", {}).get(name)
    if ws:
        result["pid"] = ws.get("pid")

    # Worker status from worker.output.complete (replaces PID liveness)
    woc = states.get("worker.output.complete", {}).get("items", {}).get(name)
    if woc:
        status = woc.get("status", "ok")
        result["worker"] = "error" if status == "error" else "stopped"
        result["exit_code"] = woc.get("returncode")

    return result


def fold_task_state(reader: Any, name: str) -> dict | None:
    """Fold task facts into current state for one task using compiled Specs."""
    states = _fold_all_specs(reader)
    return _extract_task(states, name)


def fold_all_tasks(reader: Any) -> list[dict]:
    """Fold all tasks from the store using compiled Specs."""
    states = _fold_all_specs(reader)
    names = sorted(states.get("task.created", {}).get("items", {}).keys())
    return [s for name in names if (s := _extract_task(states, name)) is not None]
