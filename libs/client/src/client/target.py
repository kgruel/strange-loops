"""Target resolution and probing."""

from __future__ import annotations

from pathlib import Path

from engine.probe import TargetInfo, probe_target

from .types import TargetNotFound, TargetUnsupported

__all__ = ["resolve_target", "TargetInfo"]


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
            f"target {path} is not a recognized loops artifact (accepted: .vertex, .jsonl, .db, .sqlite)"
        )

    return info
