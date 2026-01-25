"""Orchestrator: composes Streams and FileWriters for multi-host collection.

Wires up the streaming topology for an app spec:
  - One Stream[dict] per (host, projection) pair
  - FileWriter tapped onto each stream for JSONL persistence
  - Collectors emit events into streams, persistence happens automatically

Usage:
    uv run python -m framework.orchestrator --spec specs/homelab.app.kdl --output /tmp

Flow:
    SSHSession.run(cmd) → collector parses → stream.emit(event) → FileWriter persists
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass, field
from pathlib import Path

from .app_spec import AppSpec, DataSourceSpec, VMInfo, parse_app_spec
from .collectors import get_collector
from .file_writer import FileWriter
from .ssh_session import SSHSession
from .stream import Stream, Tap


@dataclass
class HostStream:
    """A Stream with its tapped FileWriter for a single host+projection pair."""

    host: str
    projection: str
    stream: Stream[dict]
    writer: FileWriter[dict]
    tap: Tap[dict]

    def close(self) -> None:
        """Detach the writer and close the file."""
        self.stream.detach(self.tap)
        self.writer.close()


@dataclass
class Orchestrator:
    """Manages Streams and FileWriters for multi-host event collection.

    Create streams per host+projection, tap FileWriters for persistence,
    provide emit() entry points for collectors.
    """

    output_dir: Path
    host_streams: dict[tuple[str, str], HostStream] = field(default_factory=dict)
    _shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    def create_stream(self, host: str, projection: str) -> Stream[dict]:
        """Create a Stream for a host+projection pair, tap a FileWriter.

        Log path: {output_dir}/{host}/{projection}.jsonl
        """
        key = (host, projection)
        if key in self.host_streams:
            return self.host_streams[key].stream

        # Ensure directory exists
        host_dir = self.output_dir / host
        host_dir.mkdir(parents=True, exist_ok=True)

        log_path = host_dir / f"{projection}.jsonl"
        stream: Stream[dict] = Stream()
        writer: FileWriter[dict] = FileWriter(log_path, serialize=lambda e: e)
        tap = stream.tap(writer)

        self.host_streams[key] = HostStream(
            host=host,
            projection=projection,
            stream=stream,
            writer=writer,
            tap=tap,
        )
        return stream

    def get_stream(self, host: str, projection: str) -> Stream[dict] | None:
        """Get an existing stream, or None if not created."""
        hs = self.host_streams.get((host, projection))
        return hs.stream if hs else None

    def close_all(self) -> None:
        """Close all FileWriters and detach all taps."""
        for hs in self.host_streams.values():
            hs.close()
        self.host_streams.clear()

    def request_shutdown(self) -> None:
        """Signal all collectors to stop gracefully."""
        self._shutdown_event.set()

    @property
    def shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown is requested."""
        await self._shutdown_event.wait()

    def __enter__(self) -> "Orchestrator":
        return self

    def __exit__(self, *args) -> None:
        self.close_all()


async def run_poll_collector(
    ssh: SSHSession,
    ds: DataSourceSpec,
    stream: Stream[dict],
    shutdown: asyncio.Event,
) -> None:
    """Run a poll collector on an interval until shutdown."""
    _, collector_fn = get_collector(ds.collector)
    interval = ds.interval or 10

    while not shutdown.is_set():
        try:
            events = await collector_fn(ssh)
            for event in events:
                await stream.emit(event)
        except Exception as e:
            print(f"Collector {ds.collector} error: {e}")

        # Wait for interval or shutdown
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass  # interval elapsed, loop again


async def run_stream_collector(
    ssh: SSHSession,
    ds: DataSourceSpec,
    stream: Stream[dict],
    shutdown: asyncio.Event,
) -> None:
    """Run a stream collector until shutdown."""
    _, collector_fn = get_collector(ds.collector)

    try:
        async for event in collector_fn(ssh):
            if shutdown.is_set():
                break
            await stream.emit(event)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Collector {ds.collector} error: {e}")


async def run_vm_collectors(
    vm: VMInfo,
    data_sources: list[DataSourceSpec],
    orch: "Orchestrator",
) -> None:
    """Run all collectors for a single VM within one SSH session."""
    async with SSHSession(vm.host, vm.user, vm.key_file) as ssh:
        tasks: list[asyncio.Task] = []

        for ds in data_sources:
            stream = orch.create_stream(vm.name, ds.projection)

            if ds.mode == "collect":
                task = asyncio.create_task(
                    run_poll_collector(ssh, ds, stream, orch._shutdown_event),
                    name=f"{vm.name}-{ds.collector}",
                )
            else:  # stream
                task = asyncio.create_task(
                    run_stream_collector(ssh, ds, stream, orch._shutdown_event),
                    name=f"{vm.name}-{ds.collector}",
                )
            tasks.append(task)

        # Wait for shutdown
        await orch.wait_for_shutdown()

        # Cancel all collector tasks for this VM
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_orchestrator(app_spec: AppSpec, output_dir: Path) -> None:
    """Run the orchestrator with the given app spec.

    Creates SSH sessions per VM, runs collectors per data source,
    emits events to streams, persists via FileWriter.
    """
    with Orchestrator(output_dir=output_dir) as orch:
        # Set up signal handlers for graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, orch.request_shutdown)

        if not app_spec.data_sources:
            print("No data sources configured")
            return

        # Group data sources by nothing — each VM gets all data sources
        # (The spec is per-connection, so all VMs run the same collectors)
        vm_tasks: list[asyncio.Task] = []

        for vm in app_spec.vms:
            task = asyncio.create_task(
                run_vm_collectors(vm, list(app_spec.data_sources), orch),
                name=f"vm-{vm.name}",
            )
            vm_tasks.append(task)

        print(f"Started collectors for {len(app_spec.vms)} VMs")
        print(f"Data sources: {[ds.collector for ds in app_spec.data_sources]}")
        print(f"Output: {output_dir}")
        print("Press Ctrl+C to stop")

        # Wait for all VM tasks (they'll all wait for shutdown)
        await asyncio.gather(*vm_tasks, return_exceptions=True)

        print("Done")


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Event collection orchestrator")
    parser.add_argument("--spec", required=True, help="Path to .app.kdl spec file")
    parser.add_argument("--output", default="/tmp", help="Output directory for JSONL files")
    args = parser.parse_args()

    spec_path = Path(args.spec).expanduser()
    output_dir = Path(args.output).expanduser()

    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}")
        return

    app_spec = parse_app_spec(spec_path)
    print(f"App: {app_spec.name}")
    print(f"VMs: {len(app_spec.vms)}")
    print(f"Projections: {[p.name for p in app_spec.projections]}")
    print(f"Data sources: {len(app_spec.data_sources)}")

    await run_orchestrator(app_spec, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
