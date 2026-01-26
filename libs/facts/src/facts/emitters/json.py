"""JSON emitter for machine-readable output."""

import json
import sys
from typing import TextIO

from facts.types import Event, Result


class JsonEmitter:
    """Emitter that outputs JSON to stdout.

    By default, buffers events and outputs {"events": [...], "result": {...}}
    when finish() is called.

    Options:
        include_events: Include events in final output (default: True)
        stream_events: Also stream events as JSONL to stderr (default: False)

    Output streams follow the facts convention:
        - Result (and buffered events) → stdout
        - Streamed events → stderr
    """

    def __init__(
        self,
        stdout: TextIO = sys.stdout,
        stderr: TextIO = sys.stderr,
        include_events: bool = True,
        stream_events: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self._include_events = include_events
        self._stream_events = stream_events
        self._events: list[dict] = []

    def emit(self, event: Event) -> None:
        """Buffer event, optionally stream to stderr."""
        event_dict = event.to_dict()

        if self._include_events:
            self._events.append(event_dict)

        if self._stream_events:
            self._stderr.write(json.dumps(event_dict) + "\n")
            self._stderr.flush()

    def finish(self, result: Result) -> None:
        """Output final JSON to stdout."""
        if self._include_events:
            output = {
                "events": self._events,
                "result": result.to_dict(),
            }
        else:
            output = result.to_dict()

        self._stdout.write(json.dumps(output) + "\n")
        self._stdout.flush()

    def __enter__(self) -> "JsonEmitter":
        """Enter context manager. Returns self."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager. Does not suppress exceptions."""
        pass
