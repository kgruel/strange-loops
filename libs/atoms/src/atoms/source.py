"""Source: run shell commands and emit output as facts."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from atoms.fact import Fact

if TYPE_CHECKING:
    from atoms.parse import ParseOp


class SourceError(Exception):
    """Raised when a source command fails (non-zero exit or exception).

    Carries diagnostics for the executor to record as a _sync fact.
    """

    def __init__(self, command: str, returncode: int = 1, stderr: str = ""):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"command failed (rc={returncode}): {stderr or command}")


@dataclass
class Source:
    """Bridge from shell command output to Facts flowing into Vertex.

    Source is a pure adapter: command + parse → facts. Scheduling concerns
    (when to run) live in Cadence (engine layer), not here.

    Format controls how stdout is interpreted:
    - lines: each stdout line becomes a Fact (default)
    - json: parse stdout as JSON, emit single Fact with parsed payload
    - ndjson: each stdout line parsed as JSON, emit Fact per line
    - blob: entire stdout as single Fact with {"text": ...} payload

    When parse is provided:
    - format=lines: parse runs on each line
    - format=json: parse runs on the parsed JSON dict
    - format=blob: parse is ignored (blob is raw text)

    Errors raise SourceError for the executor to handle.
    Source yields only domain facts — no lifecycle artifacts.

    Attributes:
        command: Shell command to execute
        kind: Fact kind for output
        observer: Identity for produced facts
        format: How to interpret stdout (lines, json, blob)
        parse: Optional parse pipeline to transform output into structured data
    """

    command: str
    kind: str
    observer: str
    format: Literal["lines", "json", "ndjson", "blob"] = "lines"
    parse: list[ParseOp] | None = field(default=None)
    origin: str = ""
    env: dict[str, str] | None = None

    def _has_explode(self) -> bool:
        """Check if the parse pipeline contains explode ops."""
        if self.parse is None:
            return False
        from atoms.parse import has_explode

        return has_explode(self.parse)

    def _parse_data(self, data: Any) -> dict[str, Any] | None:
        """Parse data through the pipeline, returning payload or None to skip.

        For lines format: data is a string (the line text)
        For json/ndjson format: data is the parsed JSON value (non-objects are wrapped)
        """
        # JSON can be a top-level array/scalar; normalize to dict payloads.
        if not isinstance(data, (str, dict)):
            data = {"_json": data}

        if self.parse is None:
            if isinstance(data, str):
                return {"line": data}
            if isinstance(data, dict):
                return data
            # Defensive: normalize anything else
            return {"_json": data}

        # Import here to avoid circular dependency at module load
        from atoms.parse import run_parse

        return run_parse(data, self.parse)

    def _parse_data_many(self, data: Any) -> list[dict[str, Any]]:
        """Parse data through stream pipeline, returning multiple payloads.

        Used when the pipeline contains Explode ops that fan out records.
        """
        if not isinstance(data, (str, dict)):
            data = {"_json": data}

        if self.parse is None:
            if isinstance(data, dict):
                return [data]
            return []

        from atoms.parse import run_parse_many

        return run_parse_many(data, self.parse)

    async def _emit_lines(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Emit one fact per stdout line."""
        if proc.stdout is not None:
            async for line in proc.stdout:
                text = line.decode().rstrip("\n")
                payload = self._parse_data(text)
                if payload is not None:
                    yield Fact.of(self.kind, self.observer, origin=self.origin, **payload)

    async def _emit_json(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Parse stdout as JSON, emit fact(s)."""
        if proc.stdout is not None:
            raw = await proc.stdout.read()
            text = raw.decode().strip()
            if text:
                try:
                    data = json.loads(text)
                    if self._has_explode():
                        for payload in self._parse_data_many(data):
                            yield Fact.of(self.kind, self.observer, origin=self.origin, **payload)
                    else:
                        payload = self._parse_data(data)
                        if payload is not None:
                            yield Fact.of(self.kind, self.observer, origin=self.origin, **payload)
                except json.JSONDecodeError as e:
                    print(f"source: JSON decode error: {e} (command: {self.command})", file=sys.stderr)

    def _extract_metadata(self, payload: dict) -> tuple[str, str, float | None]:
        """Extract per-record metadata overrides from payload.

        ndjson sources can include ``_observer``, ``_origin``, and
        ``_ts`` keys to override Source-level defaults. These are removed
        from the payload before the Fact is created.

        Returns (observer, origin, ts) with Source defaults as fallback.
        """
        observer = payload.pop("_observer", self.observer)
        origin = payload.pop("_origin", self.origin)
        ts = payload.pop("_ts", None)
        return observer, origin, ts

    async def _emit_ndjson(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Parse each stdout line as JSON, emit one fact per line."""
        if proc.stdout is not None:
            async for line in proc.stdout:
                text = line.decode().rstrip("\n")
                if not text:
                    continue
                try:
                    data = json.loads(text)
                    payload = self._parse_data(data)
                    if payload is not None:
                        observer, origin, ts = self._extract_metadata(payload)
                        yield Fact.of(self.kind, observer, origin=origin, ts=ts, **payload)
                except json.JSONDecodeError as e:
                    print(f"source: JSON decode error on line: {e} (command: {self.command})", file=sys.stderr)

    async def _emit_blob(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Emit entire stdout as single fact with text payload."""
        if proc.stdout is not None:
            raw = await proc.stdout.read()
            text = raw.decode()
            if text:
                yield Fact.of(self.kind, self.observer, origin=self.origin, text=text)

    async def collect(self) -> AsyncIterator[Fact]:
        """Collect facts from a single command execution."""
        try:
            import os

            proc_env = None
            if self.env:
                proc_env = os.environ.copy()
                proc_env.update(self.env)

            proc = await asyncio.create_subprocess_shell(
                self.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=10 * 1024 * 1024,  # 10MB line buffer (session JSONL lines can be large)
                env=proc_env,
            )

            if self.format == "lines":
                async for fact in self._emit_lines(proc):
                    yield fact
            elif self.format == "json":
                async for fact in self._emit_json(proc):
                    yield fact
            elif self.format == "ndjson":
                async for fact in self._emit_ndjson(proc):
                    yield fact
            elif self.format == "blob":
                async for fact in self._emit_blob(proc):
                    yield fact

            await proc.wait()

            if proc.returncode != 0:
                stderr_text = ""
                if proc.stderr is not None:
                    stderr_text = (await proc.stderr.read()).decode()
                if stderr_text:
                    print(f"source: command failed (rc={proc.returncode}): {stderr_text.rstrip()}", file=sys.stderr)
                else:
                    print(f"source: command failed (rc={proc.returncode}): {self.command}", file=sys.stderr)
                raise SourceError(self.command, proc.returncode, stderr_text.rstrip())

        except SourceError:
            raise
        except Exception as e:
            print(f"source: {type(e).__name__}: {e} (command: {self.command})", file=sys.stderr)
            raise SourceError(self.command, stderr=str(e)) from e


# Deprecated alias for backwards compatibility
CommandSource = Source
