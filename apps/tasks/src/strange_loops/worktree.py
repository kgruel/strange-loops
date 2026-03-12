"""Git worktree operations — thin wrappers around git CLI."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _worktree_dir(repo_root: Path) -> Path:
    return repo_root / ".worktrees"


def create(repo_root: Path, name: str, base_branch: str) -> Path:
    """Create a git worktree at .worktrees/<name> branched from base_branch."""
    wt_path = _worktree_dir(repo_root) / name
    subprocess.run(
        ["git", "worktree", "add", str(wt_path), "-b", name, base_branch],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return wt_path


def remove(repo_root: Path, name: str) -> None:
    """Remove a git worktree and prune."""
    wt_path = _worktree_dir(repo_root) / name
    subprocess.run(
        ["git", "worktree", "remove", str(wt_path)],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "worktree", "prune"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )


def list_worktrees(repo_root: Path) -> list[dict[str, str]]:
    """List worktrees via git worktree list --porcelain."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["worktree"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["HEAD"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line == "bare":
            current["bare"] = "true"
    if current:
        worktrees.append(current)
    return worktrees


def exists(repo_root: Path, name: str) -> bool:
    """Check if a worktree with the given name exists."""
    wt_path = str(_worktree_dir(repo_root) / name)
    for wt in list_worktrees(repo_root):
        if wt.get("worktree") == wt_path:
            return True
    return False


def diff_stat(worktree_path: Path) -> str:
    """Run git diff --stat in a worktree, return output."""
    result = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def diff_full(worktree_path: Path) -> str:
    """Run git diff in a worktree, return full diff output.

    Combines unstaged changes, staged changes, and untracked files.
    Untracked files are rendered as pseudo-diffs (new file mode).
    """
    parts = []

    # Unstaged changes to tracked files
    result = subprocess.run(
        ["git", "diff"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        parts.append(result.stdout)

    # Staged changes
    result = subprocess.run(
        ["git", "diff", "--cached"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        parts.append(result.stdout)

    # Untracked files as pseudo-diff entries
    status_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        check=True,
        capture_output=True,
        text=True,
    )
    for line in status_result.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        entry = line[3:]
        entry_path = worktree_path / entry

        if entry_path.is_file():
            files: list[Path] = [entry_path]
        elif entry_path.is_dir():
            files = sorted(f for f in entry_path.rglob("*") if f.is_file())
        else:
            continue

        for f in files:
            rel = f.relative_to(worktree_path)
            try:
                content = f.read_text()
            except (UnicodeDecodeError, PermissionError):
                continue
            lines = content.splitlines()
            count = len(lines)
            pseudo_diff = (
                f"diff --git a/{rel} b/{rel}\n"
                f"new file mode 100644\n"
                f"--- /dev/null\n"
                f"+++ b/{rel}\n"
                f"@@ -0,0 +1,{count} @@\n"
            )
            pseudo_diff += "\n".join(f"+{line}" for line in lines) + "\n"
            parts.append(pseudo_diff)

    return "".join(parts)


def current_branch(repo_root: Path) -> str:
    """Get the current branch name."""
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
