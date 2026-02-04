"""Infrastructure helpers — SSH execution and host configuration.

Provides low-level SSH execution primitives used by commands that need
to communicate with homelab hosts.
"""

from __future__ import annotations

import asyncio
import contextlib
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HostConfig:
    """SSH connection configuration for a host."""

    ip: str | None
    user: str
    key_file: Path | None = None
    common_args: str = ""


def ssh_base_args(host: HostConfig, *, connect_timeout_s: float = 5.0) -> list[str]:
    """Build base SSH command arguments.

    Args:
        host: Host configuration
        connect_timeout_s: SSH connection timeout in seconds

    Returns:
        List of SSH command arguments (excluding the remote command)
    """
    args = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={connect_timeout_s:g}"]
    if host.common_args:
        args.extend(shlex.split(host.common_args))
    if host.key_file is not None:
        args.extend(["-i", str(host.key_file)])
    return args


async def run_ssh(
    args: list[str],
    *,
    timeout_s: float = 30.0,
) -> tuple[int, str, str]:
    """Execute an SSH command asynchronously.

    Args:
        args: Full SSH command including ssh binary and all arguments
        timeout_s: Command timeout in seconds

    Returns:
        Tuple of (return_code, stdout, stderr)
        Return code 124 indicates timeout.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()
        return 124, "", f"timeout after {timeout_s:g}s"
    return proc.returncode or 0, stdout_b.decode(), stderr_b.decode()


async def run_ssh_streaming(
    args: list[str],
    *,
    timeout_s: float | None = None,
):
    """Execute an SSH command and yield stdout lines as they arrive.

    Args:
        args: Full SSH command including ssh binary and all arguments
        timeout_s: Optional overall timeout in seconds

    Yields:
        Lines from stdout as they arrive (without trailing newline)

    Raises:
        TimeoutError: If timeout_s is specified and exceeded
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def read_lines():
        assert proc.stdout is not None
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            yield raw.decode(errors="replace").rstrip("\n")

    try:
        if timeout_s is not None:
            async with asyncio.timeout(timeout_s):
                async for line in read_lines():
                    yield line
        else:
            async for line in read_lines():
                yield line
    finally:
        if proc.returncode is None:
            proc.terminate()
            with contextlib.suppress(Exception):
                await proc.wait()
