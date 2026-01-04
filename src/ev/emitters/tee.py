"""TeeEmitter and FileEmitter for dual-stream output.

TeeEmitter: Forward events to multiple emitters simultaneously.
FileEmitter: Write events as JSONL for debugging/LLM consumption.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO

from ev import Event, Result

if TYPE_CHECKING:
    from ev import Emitter


class TeeEmitter:
    """Forward events to multiple emitters simultaneously.

    Usage:
        with TeeEmitter(emitter1, emitter2) as tee:
            tee.emit(Event.log("hello"))
            tee.finish(result)

    Context manager calls __enter__/__exit__ on all children.
    """

    def __init__(self, *emitters: Emitter) -> None:
        self._emitters = emitters

    def emit(self, event: Event) -> None:
        """Forward event to all emitters."""
        for emitter in self._emitters:
            emitter.emit(event)

    def finish(self, result: Result) -> None:
        """Forward finish to all emitters."""
        for emitter in self._emitters:
            emitter.finish(result)

    def __enter__(self) -> TeeEmitter:
        """Enter context on all child emitters."""
        for emitter in self._emitters:
            emitter.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context on all child emitters. All children are called even if one raises."""
        errors = []
        for emitter in self._emitters:
            try:
                emitter.__exit__(exc_type, exc_val, exc_tb)
            except Exception as e:
                errors.append(e)
        if errors:
            raise errors[0]


class FileEmitter:
    """Write events as JSONL for debugging/LLM consumption.

    Each event is written as a JSON object on its own line, flushed immediately
    for real-time tailing with `tail -f`.

    Usage:
        with FileEmitter("deploy.log") as emitter:
            await deploy_with_emitter(stack, emitter)
            emitter.finish(result)

    Or as part of a TeeEmitter:
        with FileEmitter("deploy.log") as file_emitter, live_emitter:
            tee = TeeEmitter(live_emitter, file_emitter)
            await deploy_with_emitter(stack, tee)
            tee.finish(result)
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._file: TextIO | None = None

    def __enter__(self) -> FileEmitter:
        self._file = self._path.open("w")
        return self

    def __exit__(self, *args: object) -> None:
        if self._file:
            self._file.close()
            self._file = None

    def emit(self, event: Event) -> None:
        """Write event as JSON line, flush immediately."""
        if self._file is None:
            return

        record = self._event_to_dict(event)
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def finish(self, result: Result) -> None:
        """Write result as final JSON line."""
        if self._file is None:
            return

        record = {
            "type": "result",
            "is_ok": result.is_ok,
            "is_error": result.is_error,
            "summary": result.summary,
            "code": result.code,
            "data": dict(result.data) if result.data else None,
        }
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def _event_to_dict(self, event: Event) -> dict[str, Any]:
        """Convert event to serializable dict."""
        record: dict[str, Any] = {
            "kind": event.kind,
            "data": dict(event.data),
        }
        # Include log-specific fields only for log events
        if event.kind == "log":
            if event.message:
                record["message"] = event.message
            record["level"] = event.level
            if event.is_signal:
                record["signal_name"] = event.signal_name
        return record
