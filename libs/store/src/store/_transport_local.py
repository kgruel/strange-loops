"""LocalTransport — move stores between local paths.

Used for cross-store combine on the same machine.
Validates the Transport protocol contract.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .receive import ReceiveResult, receive_store


@dataclass(frozen=True)
class LocalTransport:
    """Move stores between local paths via file copy.

    Push: copy local_path to remote, receive at remote_path.
    Pull: copy remote_path to local_path location.
    """

    def push(self, local_path: Path, *, remote_path: Path) -> ReceiveResult:
        """Copy local store to remote path, merging if it exists.

        Args:
            local_path: Path to the local store file to send.
            remote_path: Remote (local filesystem) path to receive into.

        Returns:
            ReceiveResult from the receive operation.
        """
        return receive_store(remote_path, local_path)

    def pull(self, remote_path: Path, *, local_path: Path) -> ReceiveResult:
        """Copy remote store to local path.

        For pull, the caller (pull_store) handles receive. We just
        copy the remote file to the local temp location.

        Args:
            remote_path: Path to the remote store file.
            local_path: Local path to copy the file to.

        Returns:
            ReceiveResult (created, since it's always a fresh temp file).
        """
        remote_path = Path(remote_path)
        local_path = Path(local_path)

        if not remote_path.exists():
            raise FileNotFoundError(f"Remote store not found: {remote_path}")

        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(remote_path), str(local_path))

        # Return a minimal result — the caller will re-receive into the real target
        from ._conn import _open

        conn = _open(local_path, read_only=True)
        try:
            facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            ticks = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        finally:
            conn.close()

        return ReceiveResult(status="created", facts=facts, ticks=ticks)
