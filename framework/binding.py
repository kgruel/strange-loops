"""SourceBinding: wires Sources to Streams and Projections.

Bindings compose the data flow:
  Source → Stream → Projection (→ optional FileWriter)

The binding pattern replaces SSHConnectionManager's manual task spawning
with declarative wiring.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from rill import Stream, Tap, FileWriter

from .sources import TailerSource, PollSource, StreamSource
from .collectors import get_collector

if TYPE_CHECKING:
    from .app_spec import DataSourceSpec
    from .spec import SpecProjection
    from .ssh_session import SSHSession


@dataclass
class SourceBinding:
    """Wiring between a Source, Stream, and Projection.

    Holds all the pieces needed for one data flow:
      - source: produces events (async iterator)
      - stream: distributes events
      - projection: folds events into state
      - writer: optional persistence tap
      - tap: handle for the writer tap (for enable/disable recording)
    """

    name: str  # e.g., "vm-health"
    source: AsyncIterator[dict]
    stream: Stream[dict]
    projection: "SpecProjection"
    writer: FileWriter[dict] | None = None
    tap: Tap[dict] | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)

    def enable_recording(self, output_dir: Path, vm_name: str) -> None:
        """Tap a FileWriter onto the stream for persistence.

        Creates {output_dir}/{vm_name}/{name}.jsonl
        """
        if self.writer is not None:
            return  # already recording

        dir_path = output_dir / vm_name
        dir_path.mkdir(parents=True, exist_ok=True)
        log_path = dir_path / f"{self.name}.jsonl"

        self.writer = FileWriter(log_path, serialize=lambda e: e)
        self.tap = self.stream.tap(self.writer)

    def disable_recording(self) -> None:
        """Remove FileWriter tap, stop recording."""
        if self.tap is not None:
            self.stream.detach(self.tap)
            self.tap = None
        if self.writer is not None:
            self.writer.close()
            self.writer = None


async def run_source(binding: SourceBinding) -> None:
    """Run a source, feeding events to its stream.

    This is the main loop for a binding: reads from source,
    emits to stream. Runs until source exhausted or cancelled.
    """
    try:
        async for event in binding.source:
            await binding.stream.emit(event)
    except asyncio.CancelledError:
        pass
    except Exception:
        # Source failed, stop cleanly
        pass


def create_binding_for_poll(
    name: str,
    ssh: "SSHSession",
    collector_name: str,
    projection: "SpecProjection",
    interval: float = 10.0,
) -> SourceBinding:
    """Create a binding for a poll collector."""
    _, collector_fn = get_collector(collector_name)
    source = PollSource(ssh, collector_fn, interval=interval)
    stream: Stream[dict] = Stream()
    stream.tap(projection)

    return SourceBinding(
        name=name,
        source=source,
        stream=stream,
        projection=projection,
    )


def create_binding_for_stream(
    name: str,
    ssh: "SSHSession",
    collector_name: str,
    projection: "SpecProjection",
) -> SourceBinding:
    """Create a binding for a streaming collector."""
    _, collector_fn = get_collector(collector_name)
    source = StreamSource(ssh, collector_fn)
    stream: Stream[dict] = Stream()
    stream.tap(projection)

    return SourceBinding(
        name=name,
        source=source,
        stream=stream,
        projection=projection,
    )


def create_binding_for_tailer(
    name: str,
    path: Path,
    projection: "SpecProjection",
    poll_interval: float = 0.5,
) -> SourceBinding:
    """Create a binding for tailing a JSONL file (replay mode)."""
    source = TailerSource(path, deserialize=lambda d: d, poll_interval=poll_interval)
    stream: Stream[dict] = Stream()
    stream.tap(projection)

    return SourceBinding(
        name=name,
        source=source,
        stream=stream,
        projection=projection,
    )


def bind_data_source(
    ds: "DataSourceSpec",
    projection: "SpecProjection",
    ssh: "SSHSession | None" = None,
    source_path: Path | None = None,
) -> SourceBinding:
    """Create a binding from a DataSourceSpec.

    If source_path is provided, creates a TailerSource (replay mode).
    Otherwise, creates PollSource or StreamSource based on ds.mode.
    """
    if source_path is not None:
        # Replay mode: tail from JSONL file
        return create_binding_for_tailer(
            name=ds.projection,
            path=source_path,
            projection=projection,
            poll_interval=0.5,
        )

    if ssh is None:
        raise ValueError("SSH session required for live mode")

    if ds.mode == "collect":
        return create_binding_for_poll(
            name=ds.projection,
            ssh=ssh,
            collector_name=ds.collector,
            projection=projection,
            interval=float(ds.interval or 10),
        )
    else:  # stream
        return create_binding_for_stream(
            name=ds.projection,
            ssh=ssh,
            collector_name=ds.collector,
            projection=projection,
        )


async def start_binding(binding: SourceBinding) -> asyncio.Task:
    """Start running a binding, return the task."""
    task = asyncio.create_task(run_source(binding))
    binding._task = task
    return task


async def stop_binding(binding: SourceBinding) -> None:
    """Stop a running binding."""
    if binding._task is not None and not binding._task.done():
        binding._task.cancel()
        try:
            await binding._task
        except asyncio.CancelledError:
            pass
    binding.disable_recording()

    # Close the source if it has a close method
    source = binding.source
    if hasattr(source, "close"):
        await source.close()
