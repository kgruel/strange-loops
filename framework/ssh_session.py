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
import shlex
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import asyncssh


def _parse_common_args(args: str) -> dict[str, Any]:
    """Parse SSH common args into asyncssh connect kwargs.

    Supports:
      -J jump_host        → tunnel="jump_host"
      -o ProxyJump=host   → tunnel="host"
      -p port             → port=int(port)
      -o Port=port        → port=int(port)

    Returns dict of asyncssh.connect() kwargs.
    """
    if not args:
        return {}

    result: dict[str, Any] = {}
    tokens = shlex.split(args)
    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token == "-J" and i + 1 < len(tokens):
            # -J jump_host
            result["tunnel"] = tokens[i + 1]
            i += 2
        elif token == "-p" and i + 1 < len(tokens):
            # -p port
            result["port"] = int(tokens[i + 1])
            i += 2
        elif token == "-o" and i + 1 < len(tokens):
            # -o Option=value
            opt = tokens[i + 1]
            if "=" in opt:
                key, val = opt.split("=", 1)
                if key == "ProxyJump":
                    result["tunnel"] = val
                elif key == "Port":
                    result["port"] = int(val)
                # Other -o options can be added here
            i += 2
        else:
            i += 1

    return result


@dataclass
class SSHSession:
    """Async SSH session with run() and stream() methods."""

    host: str
    user: str
    key_file: str
    common_args: str = ""
    _conn: asyncssh.SSHClientConnection | None = field(default=None, repr=False)

    async def __aenter__(self) -> "SSHSession":
        connect_kwargs = _parse_common_args(self.common_args)
        self._conn = await asyncssh.connect(
            self.host,
            username=self.user,
            client_keys=[self.key_file],
            known_hosts=None,  # TODO: proper host key verification
            **connect_kwargs,
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
