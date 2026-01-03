"""Core types: Event and Result.

These are the fundamental building blocks of the ev contract.
Both are frozen dataclasses, immutable and serializable.
"""

import time
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
        ts: Timestamp (epoch seconds, auto-populated at creation)

    Examples:
        # Preferred: use factory methods
        Event.log("Connecting to server...")
        Event.progress("Syncing", percent=50)
        Event.metric("duration", 2.3, unit="s")
        Event.artifact("file", "Config saved", path="/tmp/out.txt")
        Event.input("Continue?", response="yes")

        # Raw constructor (escape hatch)
        Event(kind="log", message="Hello")
    """

    kind: EventKind
    level: EventLevel = "info"
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Wrap data in MappingProxyType for effective immutability."""
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))

    def is_kind(self, *kinds: EventKind) -> bool:
        """Check if event matches any of the given kinds.

        Args:
            *kinds: One or more event kinds to match against

        Returns:
            True if this event's kind matches any of the provided kinds
        """
        return self.kind in kinds

    @classmethod
    def log(
        cls,
        message: str,
        *,
        level: EventLevel = "info",
        ts: float | None = None,
        **data: Any,
    ) -> Self:
        """Create a log event.

        Args:
            message: Human-readable log message
            level: Severity level (debug, info, warn, error)
            ts: Timestamp override (auto-populated if not provided)
            **data: Additional structured data
        """
        if ts is not None:
            return cls(kind="log", level=level, message=message, data=data, ts=ts)
        return cls(kind="log", level=level, message=message, data=data)

    @classmethod
    def progress(
        cls,
        message: str = "",
        *,
        level: EventLevel = "info",
        ts: float | None = None,
        **data: Any,
    ) -> Self:
        """Create a progress event.

        Args:
            message: Optional progress message
            level: Severity level
            ts: Timestamp override (auto-populated if not provided)
            **data: Progress data (step, of, percent, phase, etc.)
        """
        if ts is not None:
            return cls(kind="progress", level=level, message=message, data=data, ts=ts)
        return cls(kind="progress", level=level, message=message, data=data)

    @classmethod
    def artifact(
        cls,
        type: str,
        message: str = "",
        *,
        level: EventLevel = "info",
        ts: float | None = None,
        **data: Any,
    ) -> Self:
        """Create an artifact event.

        Artifacts represent things produced or discovered during execution.
        The type parameter identifies what kind of artifact this is.

        Args:
            type: Artifact type identifier (e.g., "file", "stack_status", "deployment").
                Used by consumers to understand what data shape to expect.
            message: Human-readable description of the artifact
            level: Severity level
            ts: Optional timestamp
            **data: Additional artifact data (path, href, id, etc.)

        Examples:
            Event.artifact("file", path="/tmp/report.pdf")
            Event.artifact("stack_status", "Stack healthy", stack="media", healthy_count=21)
        """
        if ts is not None:
            return cls(
                kind="artifact",
                level=level,
                message=message,
                data={**data, "type": type},
                ts=ts,
            )
        return cls(
            kind="artifact",
            level=level,
            message=message,
            data={**data, "type": type},
        )

    @classmethod
    def metric(
        cls,
        name: str,
        value: Any,
        *,
        unit: str | None = None,
        level: EventLevel = "info",
        ts: float | None = None,
        **data: Any,
    ) -> Self:
        """Create a metric event.

        Args:
            name: Metric name
            value: Metric value
            unit: Optional unit (s, ms, bytes, etc.)
            level: Severity level
            ts: Timestamp override (auto-populated if not provided)
            **data: Additional metric data
        """
        metric_data: dict[str, Any] = {"name": name, "value": value, **data}
        if unit is not None:
            metric_data["unit"] = unit
        if ts is not None:
            return cls(kind="metric", level=level, data=metric_data, ts=ts)
        return cls(kind="metric", level=level, data=metric_data)

    @classmethod
    def input(
        cls,
        message: str,
        *,
        response: Any = None,
        level: EventLevel = "info",
        ts: float | None = None,
        **data: Any,
    ) -> Self:
        """Create an input event.

        Args:
            message: The prompt or question
            response: The user's response (if captured)
            level: Severity level
            ts: Timestamp override (auto-populated if not provided)
            **data: Additional input data (options, default, etc.)
        """
        input_data: dict[str, Any] = {**data}
        if response is not None:
            input_data["response"] = response
        if ts is not None:
            return cls(kind="input", level=level, message=message, data=input_data, ts=ts)
        return cls(kind="input", level=level, message=message, data=input_data)

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
        """Reconstruct an Event from a dict.

        Note: If ts is missing or null, uses 0.0 as a sentinel indicating
        unknown original timestamp (distinguishable from "created now").
        """
        ts = d.get("ts")
        return cls(
            kind=d["kind"],
            level=d.get("level", "info"),
            message=d.get("message", ""),
            data=d.get("data", {}),
            ts=ts if ts is not None else 0.0,
        )


@dataclass(frozen=True)
class Result:
    """Final outcome of a command execution.

    Emitted once at the end of a run. Contains summary and structured data.

    Attributes:
        status: Overall outcome (ok, error)
        code: Exit code (0 for success, non-zero for error)
        summary: Short human sentence describing outcome
        data: Structured payload with command-specific results
        meta: Metadata (durations, counts, timing)

    Invariants:
        - status="ok" requires code=0
        - status="error" requires code != 0

    Examples:
        # Preferred: use factory methods
        Result.ok("Deployed 3 stacks", data={"stacks": [...]})
        Result.error("Failed to connect", data={"host": "media"})

        # Raw constructor (escape hatch)
        Result(status="ok", summary="Done")
        Result(status="error", code=1, summary="Failed")
    """

    status: ResultStatus
    code: int = 0
    summary: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    meta: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Wrap data/meta and enforce status/code invariants."""
        object.__setattr__(self, "data", MappingProxyType(dict(self.data)))
        object.__setattr__(self, "meta", MappingProxyType(dict(self.meta)))

        # Enforce invariants
        if self.status == "ok" and self.code != 0:
            raise ValueError("Result with status='ok' must have code=0")
        if self.status == "error" and self.code == 0:
            raise ValueError("Result with status='error' must have non-zero code")

    @property
    def is_ok(self) -> bool:
        """True if status is 'ok'."""
        return self.status == "ok"

    @property
    def is_error(self) -> bool:
        """True if status is 'error'."""
        return self.status == "error"

    @classmethod
    def ok(
        cls,
        summary: str = "",
        *,
        data: Mapping[str, Any] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create a successful result.

        Args:
            summary: Human-readable summary of success
            data: Structured result data
            meta: Metadata (timing, counts, etc.)

        Returns:
            Result with status="ok" and code=0
        """
        return cls(
            status="ok",
            code=0,
            summary=summary,
            data=data or {},
            meta=meta or {},
        )

    @classmethod
    def error(
        cls,
        summary: str = "",
        *,
        code: int = 1,
        data: Mapping[str, Any] | None = None,
        meta: Mapping[str, Any] | None = None,
    ) -> Self:
        """Create an error result.

        Args:
            summary: Human-readable summary of error
            code: Exit code (must be non-zero, default 1)
            data: Structured error data
            meta: Metadata (timing, counts, etc.)

        Returns:
            Result with status="error" and specified code
        """
        return cls(
            status="error",
            code=code,
            summary=summary,
            data=data or {},
            meta=meta or {},
        )

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
