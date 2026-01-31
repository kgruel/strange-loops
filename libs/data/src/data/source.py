"""Source: run shell commands and emit output as facts."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Literal

from data.fact import Fact

if TYPE_CHECKING:
    from data.parse import ParseOp


@dataclass
class Source:
    """Bridge from shell command output to Facts flowing into Vertex.

    The shell is the universal adapter — Source doesn't need to know about
    HTTP, files, or APIs. It runs commands and shapes output into Facts.

    Format controls how stdout is interpreted:
    - lines: each stdout line becomes a Fact (default)
    - json: parse stdout as JSON, emit single Fact with parsed payload
    - blob: entire stdout as single Fact with {"text": ...} payload

    When parse is provided:
    - format=lines: parse runs on each line
    - format=json: parse runs on the parsed JSON dict
    - format=blob: parse is ignored (blob is raw text)

    Errors are emitted as facts with kind="source.error" rather than raised.
    This allows the runner to continue processing other sources.

    Attributes:
        command: Shell command to execute
        kind: Fact kind for output
        observer: Identity for produced facts
        every: Seconds between runs (None = run once)
        format: How to interpret stdout (lines, json, blob)
        parse: Optional parse pipeline to transform output into structured data
    """

    command: str
    kind: str
    observer: str
    every: float | None = None
    format: Literal["lines", "json", "blob"] = "lines"
    parse: list[ParseOp] | None = field(default=None)

    def _parse_data(self, data: dict[str, Any] | str) -> dict[str, Any] | None:
        """Parse data through the pipeline, returning payload or None to skip.

        For lines format: data is a string (the line text)
        For json format: data is the parsed JSON dict
        """
        if self.parse is None:
            if isinstance(data, str):
                return {"line": data}
            return data

        # Import here to avoid circular dependency at module load
        from data.parse import run_parse

        return run_parse(data, self.parse)

    async def _emit_lines(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Emit one fact per stdout line."""
        if proc.stdout is not None:
            async for line in proc.stdout:
                text = line.decode().rstrip("\n")
                payload = self._parse_data(text)
                if payload is not None:
                    yield Fact.of(self.kind, self.observer, **payload)

    async def _emit_json(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Parse stdout as JSON, emit single fact."""
        if proc.stdout is not None:
            raw = await proc.stdout.read()
            text = raw.decode().strip()
            if text:
                try:
                    data = json.loads(text)
                    payload = self._parse_data(data)
                    if payload is not None:
                        yield Fact.of(self.kind, self.observer, **payload)
                except json.JSONDecodeError as e:
                    yield Fact.of(
                        "source.error",
                        self.observer,
                        command=self.command,
                        error=f"JSON decode error: {e}",
                        error_type="JSONDecodeError",
                    )

    async def _emit_blob(self, proc: asyncio.subprocess.Process) -> AsyncIterator[Fact]:
        """Emit entire stdout as single fact with text payload."""
        if proc.stdout is not None:
            raw = await proc.stdout.read()
            text = raw.decode()
            if text:
                yield Fact.of(self.kind, self.observer, text=text)

    async def stream(self) -> AsyncIterator[Fact]:
        """Yield facts from command output. Re-runs if every is set."""
        while True:
            try:
                proc = await asyncio.create_subprocess_shell(
                    self.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                if self.format == "lines":
                    async for fact in self._emit_lines(proc):
                        yield fact
                elif self.format == "json":
                    async for fact in self._emit_json(proc):
                        yield fact
                elif self.format == "blob":
                    async for fact in self._emit_blob(proc):
                        yield fact

                await proc.wait()

                if proc.returncode != 0 and proc.stderr is not None:
                    stderr = await proc.stderr.read()
                    yield Fact.of(
                        "source.error",
                        self.observer,
                        command=self.command,
                        returncode=proc.returncode,
                        stderr=stderr.decode(),
                    )

            except Exception as e:
                yield Fact.of(
                    "source.error",
                    self.observer,
                    command=self.command,
                    error=str(e),
                    error_type=type(e).__name__,
                )

            if self.every is None:
                break

            await asyncio.sleep(self.every)


# Deprecated alias for backwards compatibility
CommandSource = Source
