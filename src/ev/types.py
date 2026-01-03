"""Core types: Event and Result.

These are the fundamental building blocks of the ev contract.
Both are frozen dataclasses, immutable and serializable.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Self

EventKind = Literal["log", "progress", "artifact", "metric", "input"]
EventLevel = Literal["debug", "info", "warn", "error"]
ResultStatus = Literal["ok", "error"]


@dataclass(frozen=True)
class Event:
    """A streaming fact emitted during command execution.

    Events describe what happened, not how to display it.
    Renderers interpret events according to their own logic.

    Attributes:
        kind: Category of event (log, progress, artifact, metric, input)
        level: Severity (debug, info, warn, error)
        message: Short human-readable text or key
        data: Structured payload (must be JSON-serializable)
        ts: Optional timestamp (epoch seconds)

    Examples:
        # Simple log
        Event(kind="log", message="Connecting to server...")

        # Progress with data
        Event(kind="progress", data={"phase": "sync", "percent": 50})

        # Metric
        Event(kind="metric", data={"name": "duration", "value": 2.3, "unit": "s"})

        # Artifact produced
        Event(kind="artifact", data={"type": "file", "path": "/tmp/out.txt"})

        # Input interaction
        Event(kind="input", message="Continue?", data={"response": "yes"})
    """

    kind: EventKind
    level: EventLevel = "info"
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    ts: float | None = None

    def __post_init__(self) -> None:
        """Wrap data in MappingProxyType for effective immutability."""
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        return {
            "kind": self.kind,
            "level": self.level,
            "message": self.message,
            "data": dict(self.data),
            "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Reconstruct an Event from a dict."""
        return cls(
            kind=d["kind"],
            level=d.get("level", "info"),
            message=d.get("message", ""),
            data=d.get("data", {}),
            ts=d.get("ts"),
        )


@dataclass(frozen=True)
class Result:
    """Final outcome of a command execution.

    Emitted once at the end of a run. Contains summary and structured data.

    Attributes:
        status: Overall outcome (ok, error)
        code: Exit code (0 for success)
        summary: Short human sentence describing outcome
        data: Structured payload with command-specific results
        meta: Metadata (durations, counts, timing)

    Examples:
        # Success
        Result(status="ok", summary="Deployed 3 stacks", data={"stacks": [...]})

        # Error
        Result(status="error", code=1, summary="Failed to connect",
               data={"host": "media", "error": "timeout"})
    """

    status: ResultStatus
    code: int = 0
    summary: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Wrap data and meta in MappingProxyType for effective immutability."""
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))

    def to_dict(self) -> dict[str, Any]:
        """Convert to a plain dict for serialization."""
        return {
            "status": self.status,
            "code": self.code,
            "summary": self.summary,
            "data": dict(self.data),
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Reconstruct a Result from a dict."""
        return cls(
            status=d["status"],
            code=d.get("code", 0),
            summary=d.get("summary", ""),
            data=d.get("data", {}),
            meta=d.get("meta", {}),
        )
