"""Harness runner — spawned as a detached process by task send.

Bridge for .loop declarations. Each .loop file declares a harness's source
template (CLI invocation), kind, observer, and format. This module resolves
the .loop by name, substitutes {{prompt}}/{{command}} with the user input,
executes synchronously, and emits facts matching the declared kind structure.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from lang import parse_loop_file

from strange_loops.store import emit_fact, emit_tick

# Package root: apps/strange-loops/
_PKG_ROOT = Path(__file__).resolve().parent.parent.parent
_HARNESS_DIR = _PKG_ROOT / "loops" / "harnesses"


def _find_loop(name: str) -> Path:
    """Resolve loops/harnesses/{name}.loop, raise if missing."""
    path = _HARNESS_DIR / f"{name}.loop"
    if not path.exists():
        available = sorted(p.stem for p in _HARNESS_DIR.glob("*.loop"))
        raise FileNotFoundError(
            f"Harness '{name}' not found at {path}. Available: {', '.join(available)}"
        )
    return path


def _build_command(source_template: str, prompt: str) -> str:
    """Substitute {{prompt}} (shell-escaped) and {{command}} (raw) in source template.

    {{prompt}} is for AI tools — user input that must be shell-escaped.
    {{command}} is for shell harness — already a valid shell command.
    """
    escaped = shlex.quote(prompt)
    result = source_template.replace("{{prompt}}", escaped)
    result = result.replace("{{command}}", prompt)
    return result


def run_harness(
    path: Path,
    task_name: str,
    worktree: Path,
    prompt: str,
    harness_name: str,
    obs: str,
) -> int:
    """Run a harness in a worktree, emitting worker facts.

    Loads the .loop file by harness_name, builds the command from its source
    template, runs it with cwd=worktree. Emits worker.output per line,
    worker.output.complete on exit. Returns the exit code.
    """
    loop_path = _find_loop(harness_name)
    loop = parse_loop_file(loop_path)

    assert loop.source is not None, f"Harness '{harness_name}' has no source template"
    command = _build_command(loop.source, prompt)

    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=worktree,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        emit_fact(path, "worker.output", obs, {"task": task_name, "line": line})

    exit_code = proc.wait()

    status = "ok" if exit_code == 0 else "error"
    complete_payload: dict = {"task": task_name, "status": status, "returncode": exit_code}
    if exit_code != 0:
        complete_payload["error"] = f"Process exited with code {exit_code}"
    emit_fact(path, "worker.output.complete", obs, complete_payload)

    # Advance task stage and emit tick (boundary crossing)
    stage = "completed" if exit_code == 0 else "errored"
    emit_fact(path, "task.stage", obs, {"name": task_name, "status": stage})
    emit_tick(
        path,
        name="task.tick",
        payload={"task": task_name, "status": stage, "exit_code": exit_code},
        origin="tasks",
    )

    return exit_code


def spawn(
    path: Path,
    task_name: str,
    worktree: Path,
    prompt: str,
    harness_name: str,
    obs: str,
) -> int:
    """Spawn a harness as a detached process. Returns the PID."""
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "strange_loops.harness",
            str(path),
            task_name,
            str(worktree),
            prompt,
            harness_name,
            obs,
        ],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc.pid


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) != 6:
        print(
            "Usage: python -m strange_loops.harness <store_path> <task_name> <worktree> <prompt> <harness_name> <observer>",
            file=sys.stderr,
        )
        sys.exit(1)

    sp, task, wt, prompt_arg, harness, observer_name = args
    code = run_harness(Path(sp), task, Path(wt), prompt_arg, harness, observer_name)
    sys.exit(code)
