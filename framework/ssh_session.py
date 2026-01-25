"""SSHSession: async context manager for SSH connections.

Wraps asyncssh to provide:
  - run(cmd) → stdout as string (for poll collectors)
  - stream(cmd) → async iterator of lines (for stream collectors)

Usage:
    async with SSHSession(host, user, key_file) as ssh:
        output = await ssh.run("docker ps --format json")
        async for line in ssh.stream("docker events --format json"):
            process(line)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import asyncssh


@dataclass
class SSHSession:
    """Async SSH session with run() and stream() methods."""

    host: str
    user: str
    key_file: str
    _conn: asyncssh.SSHClientConnection | None = None

    async def __aenter__(self) -> "SSHSession":
        self._conn = await asyncssh.connect(
            self.host,
            username=self.user,
            client_keys=[self.key_file],
            known_hosts=None,  # TODO: proper host key verification
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._conn:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    async def run(self, cmd: str) -> str:
        """Run a command and return stdout."""
        if not self._conn:
            raise RuntimeError("SSHSession not connected")
        result = await self._conn.run(cmd, check=True)
        return result.stdout or ""

    async def stream(self, cmd: str) -> AsyncIterator[str]:
        """Run a command and yield stdout lines as they arrive."""
        if not self._conn:
            raise RuntimeError("SSHSession not connected")

        process = await self._conn.create_process(cmd)
        try:
            async for line in process.stdout:
                yield line.rstrip("\n")
        finally:
            process.terminate()
            await process.wait()
