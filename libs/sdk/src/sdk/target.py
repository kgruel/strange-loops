"""Target resolution and probing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from engine.arrival_contract import StoreDescriptor
from engine.arrival_registry import descriptor_for
from engine.probe import TargetInfo, probe_target
from lang import parse_vertex_file, resolve_vertex

from .types import (
    ArrivalTarget,
    SdkValueError,
    StoreDescriptorInfo,
    TargetNotFound,
    TargetUnsupported,
)

__all__ = ["resolve_target", "resolve_arrival_target", "discover_targets", "TargetInfo"]

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


def _arrival_descriptor(target: Path | str) -> tuple[Path, Any, StoreDescriptor] | None:
    """Resolve an explicitly declared descriptor without probing its location.

    ``TargetInfo`` is a legacy filesystem classification and necessarily turns
    a store spelling into a ``Path``. Descriptor resolution instead parses the
    vertex locator directly, so another backend's DSN or service URL remains
    byte-for-byte opaque until that named adapter receives it.
    """
    path = Path(target).resolve()
    if path.suffix.lower() != ".vertex":
        return None
    if not path.exists():
        raise TargetNotFound(f"target path does not exist: {path}")
    try:
        ast = parse_vertex_file(path)
    except Exception:
        return None  # the legacy resolver owns malformed-target classification
    descriptor = descriptor_for(ast, path)
    if descriptor is None:
        return None
    if ast.combine is not None or ast.discover is not None:
        raise TargetUnsupported(
            f"Arrival target {path} is an aggregate; member-basis reads are not "
            "implemented in this single-store stage"
        )
    if descriptor.role is None:
        raise SdkValueError(
            f"Arrival target {path} must declare store role explicitly"
        )
    return path, ast, descriptor


def _refuse_arrival_aggregate_members(target: Path | str) -> None:
    """Keep legacy aggregate composition from opening descriptor members."""
    root = Path(target).resolve()
    if root.suffix.lower() != ".vertex" or not root.exists():
        return

    config_home = Path(
        os.environ.get(
            "LOOPS_HOME",
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "loops",
        )
    )
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        path = path.resolve()
        if path in visited or not path.exists():
            return
        visited.add(path)
        try:
            ast = parse_vertex_file(path)
        except Exception:
            return  # legacy resolver reports malformed targets in its own taxonomy

        if path != root and ast.store_backend is not None:
            raise TargetUnsupported(
                f"aggregate target {root} includes descriptor-backed member {path}; "
                "member-basis Arrival reads are not implemented"
            )

        members: list[Path] = []
        if ast.discover is not None:
            members.extend(
                match.resolve()
                for match in sorted(path.parent.glob(ast.discover))
                if match.suffix.lower() == ".vertex" and match.resolve() != path
            )
        elif ast.combine is not None:
            for entry in ast.combine:
                member = resolve_vertex(entry.name, config_home)
                if not member.is_absolute():
                    member = (path.parent / member).resolve()
                members.append(member)
        for member in members:
            visit(member)

    visit(root)


def resolve_arrival_target(target: Path | str) -> ArrivalTarget:
    """Resolve the supported descriptor-first Arrival target.

    Bare stores and vertices without ``backend=`` remain legacy inputs. They
    are deliberately refused here instead of being inferred from a suffix.
    """
    resolved = _arrival_descriptor(target)
    if resolved is None:
        path = Path(target).resolve()
        raise TargetUnsupported(
            f"target {path} does not declare an Arrival backend and role"
        )
    path, ast, descriptor = resolved
    return ArrivalTarget(
        target_path=str(path),
        vertex_name=ast.name,
        store=StoreDescriptorInfo.from_descriptor(descriptor),
    )


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
