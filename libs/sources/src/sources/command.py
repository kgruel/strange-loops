"""CommandSource: run shell commands and emit stdout lines as facts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator

from facts import Fact

if TYPE_CHECKING:
    pass


@dataclass
class CommandSource:
    """Source that runs a shell command and emits stdout lines as facts.

    Each line of stdout becomes a Fact with the configured kind and observer.
    If interval is set, the command re-runs after the delay. If None, runs once.

    Errors are emitted as facts with kind="source.error" rather than raised.
    This allows the runner to continue processing other sources.

    Attributes:
        command: Shell command to execute
        kind: Fact kind for stdout lines
        observer: Identity for produced facts
        interval: Seconds between runs (None = run once)
    """

    command: str
    kind: str
    observer: str
    interval: float | None = None

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
                        yield Fact.of(self.kind, self.observer, line=text)

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
