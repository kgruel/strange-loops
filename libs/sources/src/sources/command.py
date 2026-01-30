"""CommandSource: run shell commands and emit stdout lines as facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from facts import Fact

if TYPE_CHECKING:
    from specs.parse import ParseOp


@dataclass
class CommandSource:
    """Source that runs a shell command and emits stdout lines as facts.

    Each line of stdout becomes a Fact with the configured kind and observer.
    If interval is set, the command re-runs after the delay. If None, runs once.

    When parse is provided, each line is run through the parse pipeline:
    - If parse returns None, the line is skipped (no Fact emitted)
    - If parse succeeds, the Fact payload is the parsed dict

    Errors are emitted as facts with kind="source.error" rather than raised.
    This allows the runner to continue processing other sources.

    Attributes:
        command: Shell command to execute
        kind: Fact kind for stdout lines
        observer: Identity for produced facts
        interval: Seconds between runs (None = run once)
        parse: Optional parse pipeline to transform lines into structured data
    """

    command: str
    kind: str
    observer: str
    interval: float | None = None
    parse: list[ParseOp] | None = field(default=None)

    def _parse_line(self, text: str) -> dict[str, Any] | None:
        """Parse a line through the pipeline, returning payload or None to skip."""
        if self.parse is None:
            return {"line": text}

        # Import here to avoid circular dependency at module load
        from specs.parse import run_parse

        return run_parse(text, self.parse)

    async def stream(self) -> AsyncIterator[Fact]:
        """Yield facts from command output. Re-runs if interval is set."""
        while True:
            try:
                proc = await asyncio.create_subprocess_shell(
                    self.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                if proc.stdout is not None:
                    async for line in proc.stdout:
                        text = line.decode().rstrip("\n")
                        payload = self._parse_line(text)
                        if payload is not None:
                            yield Fact.of(self.kind, self.observer, **payload)

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

            if self.interval is None:
                break

            await asyncio.sleep(self.interval)
