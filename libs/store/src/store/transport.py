"""Transport protocol and push/pull orchestration.

Every data movement decomposes to: slice on source -> move bytes -> merge on target.
Transport doesn't understand facts, ticks, or vertices. It moves SQLite files.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .receive import ReceiveResult


class Transport(Protocol):
    """Pluggable byte pipe between stores.

    Transport doesn't understand facts or vertices.
    It moves SQLite files between locations.
    """

    def push(self, local_path: Path, *, remote_path: Path) -> ReceiveResult:
        """Send a local store file to the remote, which merges it."""
        ...

    def pull(self, remote_path: Path, *, local_path: Path) -> ReceiveResult:
        """Fetch a remote store file to local, which merges it."""
        ...


@dataclass(frozen=True)
class PushResult:
    """Outcome of a push operation."""

    sliced_facts: int
    sliced_ticks: int
    receive: ReceiveResult


@dataclass(frozen=True)
class PullResult:
    """Outcome of a pull operation."""

    sliced_facts: int
    sliced_ticks: int
    receive: ReceiveResult


def push_store(
    source: Path,
    transport: Transport,
    *,
    remote_path: Path,
    since: float | None = None,
    before: float | None = None,
    kinds: list[str] | None = None,
) -> PushResult:
    """Slice source -> transport.push -> remote receive.

    Args:
        source: Local store to push from.
        transport: Transport implementation to use.
        remote_path: Where the remote should place/merge the store.
        since: Include facts/ticks with ts >= since.
        before: Include facts/ticks with ts < before.
        kinds: Include facts matching these kinds (exact or prefix).

    Returns:
        PushResult with slice counts and receive outcome.

    Raises:
        FileNotFoundError: If source does not exist.
    """
    from .slice import slice_store

    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Source store not found: {source}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_slice = Path(tmpdir) / "slice.db"
        slice_result = slice_store(
            source, tmp_slice, since=since, before=before, kinds=kinds,
        )
        receive_result = transport.push(tmp_slice, remote_path=remote_path)

    return PushResult(
        sliced_facts=slice_result.facts,
        sliced_ticks=slice_result.ticks,
        receive=receive_result,
    )


def pull_store(
    target: Path,
    transport: Transport,
    *,
    remote_path: Path,
    since: float | None = None,
    before: float | None = None,
    kinds: list[str] | None = None,
) -> PullResult:
    """Remote slice -> transport.pull -> local receive.

    Args:
        target: Local store to receive into.
        transport: Transport implementation to use.
        remote_path: Remote store to pull from.
        since: Include facts/ticks with ts >= since.
        before: Include facts/ticks with ts < before.
        kinds: Include facts matching these kinds (exact or prefix).

    Returns:
        PullResult with slice counts and receive outcome.

    Raises nothing if target doesn't exist yet — receive_store will create it.
    """
    from .receive import receive_store
    from .slice import slice_store

    target = Path(target)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Transport fetches the remote file to a local temp
        tmp_remote = Path(tmpdir) / "remote.db"
        transport.pull(remote_path, local_path=tmp_remote)

        # Slice the fetched file if filters are specified
        if since is not None or before is not None or kinds is not None:
            tmp_sliced = Path(tmpdir) / "sliced.db"
            slice_result = slice_store(
                tmp_remote, tmp_sliced, since=since, before=before, kinds=kinds,
            )
            receive_result = receive_store(target, tmp_sliced)
        else:
            # No filters — receive the full remote file directly
            receive_result = receive_store(target, tmp_remote)
            return PullResult(
                sliced_facts=receive_result.facts,
                sliced_ticks=receive_result.ticks,
                receive=receive_result,
            )

    return PullResult(
        sliced_facts=slice_result.facts,
        sliced_ticks=slice_result.ticks,
        receive=receive_result,
    )
