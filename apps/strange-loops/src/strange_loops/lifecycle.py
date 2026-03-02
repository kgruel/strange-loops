"""Compiled vertex loader + vertex_read-based fold for task state."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine import vertex_read

# Package root: apps/strange-loops/
_PKG_ROOT = Path(__file__).resolve().parent.parent.parent

# Vertex paths
_TASKS_VERTEX = _PKG_ROOT / "loops" / "tasks.vertex"
_PROJECT_VERTEX = _PKG_ROOT / "loops" / "project.vertex"


def tasks_vertex_path() -> Path:
    """Resolve loops/tasks.vertex relative to the app root."""
    return _TASKS_VERTEX


def project_vertex_path() -> Path:
    """Resolve loops/project.vertex relative to the app root."""
    return _PROJECT_VERTEX


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


def fold_task_state(vp: Path, name: str) -> dict | None:
    """Fold task facts into current state for one task via vertex_read."""
    states = vertex_read(vp)
    return _extract_task(states, name)


def fold_all_tasks(vp: Path) -> list[dict]:
    """Fold all tasks from the vertex store via vertex_read."""
    states = vertex_read(vp)
    names = sorted(states.get("task.created", {}).get("items", {}).keys())
    return [s for name in names if (s := _extract_task(states, name)) is not None]
