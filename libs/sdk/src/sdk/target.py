"""Target resolution and probing."""

from __future__ import annotations

from pathlib import Path

from engine.probe import TargetInfo, probe_target

from .types import TargetNotFound, TargetUnsupported

__all__ = ["resolve_target", "discover_targets", "TargetInfo"]

_IGNORE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".hypothesis",
        ".gemini",
        ".claude",
        ".subtask",
        ".uv-cache",
        "node_modules",
    }
)


def resolve_target(target: Path | str) -> TargetInfo:
    """Resolve and probe a target path without modifying it or opening SQLite.

    Returns `TargetInfo` describing target type, canonical path, and mode.
    Raises `TargetNotFound` if the path doesn't exist, or `TargetUnsupported`
    if the target cannot be classified as a loops artifact.
    """
    path = Path(target).resolve()
    if not path.exists():
        raise TargetNotFound(f"target path does not exist: {path}")

    info = probe_target(path)
    if info.target_type == "unknown":
        raise TargetUnsupported(
            f"target {path} is not a recognized loops artifact "
            "(accepted: .vertex, .jsonl, .db, .sqlite)"
        )

    return info


def discover_targets(
    root_path: Path | str = ".",
    *,
    recursive: bool = True,
    include_bare: bool = True,
) -> list[TargetInfo]:
    """Discover all Loops targets (vertices and bare stores) within a directory.

    Parameters:
        root_path: Root directory path to start scanning from.
        recursive: Whether to search subdirectories recursively.
        include_bare: Whether to include bare .jsonl / .db stores.

    Returns:
        Sorted list of TargetInfo descriptors for all discovered artifacts.
    """
    root = Path(root_path).resolve()
    if not root.exists() or not root.is_dir():
        return []

    discovered: list[TargetInfo] = []
    seen_paths: set[Path] = set()

    def _scan_dir(dir_path: Path) -> None:
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: p.name)
        except OSError:
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name in _IGNORE_DIRS or entry.name.startswith("."):
                    continue
                if recursive:
                    _scan_dir(entry)
            elif entry.is_file():
                suffix = entry.suffix.lower()
                if suffix == ".vertex":
                    try:
                        info = resolve_target(entry)
                        if entry not in seen_paths:
                            seen_paths.add(entry)
                            discovered.append(info)
                    except Exception:
                        continue
                elif include_bare and suffix in (".jsonl", ".db", ".sqlite"):
                    # Avoid adding .loops/data derived indices
                    if ".loops" in entry.parts:
                        continue
                    try:
                        info = resolve_target(entry)
                        if entry not in seen_paths:
                            seen_paths.add(entry)
                            discovered.append(info)
                    except Exception:
                        continue

    _scan_dir(root)
    discovered.sort(key=lambda t: str(t.canonical_path) if t.canonical_path else "")
    return discovered
