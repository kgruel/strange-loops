# Logging Bridge Pattern

*Bridging Python's stdlib logging to ev events.*

## The Problem

Third-party libraries (requests, boto3, sqlalchemy) emit logs via Python's standard `logging` module. These logs bypass ev entirely, potentially breaking the "unified output" experience.

## When You Need This

- You want library warnings/errors to appear in your ev output stream
- You're building a comprehensive audit log
- You want JSON output mode to capture everything

## When You Don't

- You're fine with library logs going to stderr separately
- You only care about your application's user-facing facts
- You want to keep diagnostics separate from user output

ev is designed for **user-facing facts**, not diagnostics. Library logs are diagnostics. Keeping them separate is often the right choice.

## The Bridge

A custom `logging.Handler` that emits ev events:

```python
import logging
from ev import Event, Emitter

class EvLoggingHandler(logging.Handler):
    """Bridge stdlib logging to an ev Emitter."""

    def __init__(self, emitter: Emitter, level: int = logging.WARNING):
        super().__init__(level)
        self._emitter = emitter

    def emit(self, record: logging.LogRecord) -> None:
        # Map logging levels to ev levels
        if record.levelno >= logging.ERROR:
            level = "error"
        elif record.levelno >= logging.WARNING:
            level = "warn"
        elif record.levelno >= logging.INFO:
            level = "info"
        else:
            level = "debug"

        # Emit as a log event with source metadata
        self._emitter.emit(
            Event.log(
                record.getMessage(),
                level=level,
                source="logging",
                logger=record.name,
                module=record.module,
            )
        )
```

## Usage

```python
import logging
from ev import ListEmitter

# Create your emitter
emitter = ListEmitter()

# Install the bridge
handler = EvLoggingHandler(emitter, level=logging.WARNING)
logging.getLogger().addHandler(handler)

# Now library logs appear in your event stream
import requests
requests.get("https://invalid.example.com")  # Connection error → ev event
```

## Filtering by Logger

You might only want specific loggers bridged:

```python
# Only bridge boto3 and requests
for name in ["boto3", "requests", "urllib3"]:
    logging.getLogger(name).addHandler(handler)
```

## Distinguishing Bridged Logs

Bridged logs include `source="logging"` in their data, so renderers can treat them differently:

```python
def emit(self, event: Event) -> None:
    if event.kind == "log" and event.data.get("source") == "logging":
        # Library log - render dimmed or skip in quiet mode
        ...
    else:
        # Application log - render normally
        ...
```

## Avoiding Recursion

If your emitter itself uses logging, you might create a loop. Prevent this:

```python
class EvLoggingHandler(logging.Handler):
    def __init__(self, emitter: Emitter, level: int = logging.WARNING):
        super().__init__(level)
        self._emitter = emitter
        self._emitting = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._emitting:
            return  # Prevent recursion
        self._emitting = True
        try:
            # ... emit logic ...
        finally:
            self._emitting = False
```

## Alternative: Separate Streams

Instead of bridging, you might keep them separate:

```python
# ev events → stdout (via your renderer)
# Library logs → stderr (via logging)

import logging
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
```

This is often cleaner and matches the "ev is for user facts, logging is for diagnostics" philosophy.

## Summary

| Approach | When to Use |
|----------|-------------|
| Bridge to ev | Unified output, audit logging, JSON mode |
| Separate streams | Clean separation of concerns, simple setup |
| Filtered bridge | Only specific libraries need visibility |

Most CLI tools work fine without bridging. Add it only if you have a specific need.
