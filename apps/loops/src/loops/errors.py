"""Loops CLI error hierarchy.

Domain errors for the CLI layer. Wraps raw exceptions (FileNotFoundError,
lang.ParseError, etc.) into typed errors with structured context. Libs
keep their own errors — the CLI translates at the boundary.

Catch ``LoopsError`` at the CLI boundary for uniform error presentation.
Catch specific subclasses when recovery behavior differs.
"""
from __future__ import annotations

from pathlib import Path


class LoopsError(Exception):
    """Base for all loops CLI domain errors."""


# --- Vertex resolution errors ---

class VertexNotFound(LoopsError):
    """A vertex file does not exist at the expected path."""

    def __init__(self, path: Path, context: str = ""):
        self.path = path
        self.context = context
        msg = f"Vertex not found: {path}"
        if context:
            msg += f" ({context})"
        super().__init__(msg)


class VertexParseError(LoopsError):
    """A vertex file exists but cannot be parsed."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Invalid vertex {path}: {cause}")


class ResolutionFailed(LoopsError):
    """A vertex name could not be resolved to any path."""

    def __init__(self, name: str, searched: list[str] | None = None):
        self.name = name
        self.searched = searched or []
        msg = f"Cannot resolve vertex: {name}"
        if searched:
            msg += f" (searched: {', '.join(searched)})"
        super().__init__(msg)


# --- Store errors ---

class StoreNotFound(LoopsError):
    """A vertex has no store configured or the store path doesn't exist."""

    def __init__(self, vertex: str | Path, detail: str = ""):
        self.vertex = vertex
        msg = f"No store configured for vertex '{vertex}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class StoreAccessError(LoopsError):
    """A store exists but cannot be read or written."""

    def __init__(self, path: Path, cause: Exception):
        self.path = path
        self.cause = cause
        super().__init__(f"Store access failed ({path}): {cause}")


# --- Emit / action errors ---

class EmitError(LoopsError):
    """An emit operation failed after validation passed."""

    def __init__(self, detail: str, vertex: Path | None = None):
        self.vertex = vertex
        self.detail = detail
        msg = f"Emit failed: {detail}"
        if vertex:
            msg = f"Emit to {vertex} failed: {detail}"
        super().__init__(msg)
