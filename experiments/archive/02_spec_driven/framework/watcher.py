"""File watcher using mtime polling.

Polls stat() on tracked files every `poll_interval` seconds.
Debounces changes: waits `debounce` seconds after the last detected
change before firing the callback. No external dependencies.

Usage:
    watcher = SpecWatcher(
        directory=Path("specs"),
        patterns=["*.app.kdl", "*.projection.kdl"],
        on_change=my_callback,
    )
    task = asyncio.create_task(watcher.run())
    # later:
    watcher.stop()
    await task
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable, Awaitable


class SpecWatcher:
    """Polls a directory for file changes and fires a callback.

    Args:
        directory: Path to watch.
        patterns: Glob patterns to match (e.g. ["*.app.kdl"]).
        on_change: Async callback receiving the set of changed file paths.
        poll_interval: Seconds between stat polls (default 1.0).
        debounce: Seconds to wait after last change before firing (default 0.3).
    """

    def __init__(
        self,
        directory: Path,
        patterns: list[str],
        on_change: Callable[[set[Path]], Awaitable[None]],
        poll_interval: float = 1.0,
        debounce: float = 0.3,
    ):
        self._directory = directory
        self._patterns = patterns
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._debounce = debounce
        self._running = False
        self._mtimes: dict[Path, float] = {}

    def _scan_files(self) -> set[Path]:
        """Find all files matching patterns in the watched directory."""
        files: set[Path] = set()
        if not self._directory.exists():
            return files
        for pattern in self._patterns:
            files.update(self._directory.glob(pattern))
        return files

    def _snapshot_mtimes(self, files: set[Path]) -> dict[Path, float]:
        """Get mtime for each file, skipping vanished files."""
        mtimes: dict[Path, float] = {}
        for f in files:
            try:
                mtimes[f] = f.stat().st_mtime
            except OSError:
                pass
        return mtimes

    def _detect_changes(self, current: dict[Path, float]) -> set[Path]:
        """Compare current mtimes against stored, return changed/new/deleted paths."""
        changed: set[Path] = set()

        for path, mtime in current.items():
            if path not in self._mtimes or self._mtimes[path] != mtime:
                changed.add(path)

        for path in self._mtimes:
            if path not in current:
                changed.add(path)

        return changed

    async def run(self) -> None:
        """Poll loop. Runs until stop() is called."""
        self._running = True

        # Initial snapshot — don't fire on startup
        files = self._scan_files()
        self._mtimes = self._snapshot_mtimes(files)

        pending_changes: set[Path] = set()
        last_change_time: float | None = None

        while self._running:
            await asyncio.sleep(self._poll_interval)
            if not self._running:
                break

            files = self._scan_files()
            current = self._snapshot_mtimes(files)
            changed = self._detect_changes(current)

            if changed:
                pending_changes.update(changed)
                last_change_time = asyncio.get_running_loop().time()
                self._mtimes = current

            # Debounce: fire callback after debounce period of quiet
            if pending_changes and last_change_time is not None:
                elapsed = asyncio.get_running_loop().time() - last_change_time
                if elapsed >= self._debounce:
                    try:
                        await self._on_change(set(pending_changes))
                    except Exception:
                        pass  # caller handles errors
                    pending_changes.clear()
                    last_change_time = None

    def stop(self) -> None:
        """Signal the poll loop to exit."""
        self._running = False
