"""Tests for Source implementations and bindings."""

import asyncio
import tempfile
from pathlib import Path

import pytest

from ticks import Stream, Source, ClosableSource, FileWriter
from framework.sources import TailerSource, PollSource, StreamSource
from framework.binding import (
    SourceBinding,
    run_source,
    start_binding,
    stop_binding,
    create_binding_for_tailer,
)
from framework.spec import SpecProjection, parse_projection_spec


SPECS_DIR = Path(__file__).parent.parent / "specs"


class TestSourceProtocol:
    """Tests for the Source protocol."""

    def test_tailer_source_is_source(self):
        """TailerSource implements Source protocol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = TailerSource(Path(tmpdir) / "test.jsonl", lambda d: d)
            # Source is a runtime checkable protocol
            assert isinstance(source, Source)

    def test_tailer_source_is_closable_source(self):
        """TailerSource implements ClosableSource protocol."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = TailerSource(Path(tmpdir) / "test.jsonl", lambda d: d)
            assert isinstance(source, ClosableSource)


class TestTailerSource:
    """Tests for TailerSource."""

    @pytest.mark.asyncio
    async def test_tailer_source_yields_events(self):
        """TailerSource yields events from a JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            # Write some events
            path.write_text('{"a": 1}\n{"b": 2}\n')

            source = TailerSource(path, lambda d: d, poll_interval=0.1)
            events = []

            # Read two events
            async for event in source:
                events.append(event)
                if len(events) >= 2:
                    await source.close()
                    break

            assert events == [{"a": 1}, {"b": 2}]

    @pytest.mark.asyncio
    async def test_tailer_source_handles_missing_file(self):
        """TailerSource waits for file to appear."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            source = TailerSource(path, lambda d: d, poll_interval=0.1)

            # Close immediately (file doesn't exist, nothing to yield)
            await source.close()

            events = []
            async for event in source:
                events.append(event)

            assert events == []

    @pytest.mark.asyncio
    async def test_tailer_source_reset(self):
        """TailerSource can reset to replay from beginning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            path.write_text('{"x": 1}\n')

            source = TailerSource(path, lambda d: d, poll_interval=0.1)

            # Read first event
            events = []
            async for event in source:
                events.append(event)
                break

            assert events == [{"x": 1}]

            # Reset and read again
            source.reset()
            source._closed = False  # reopen

            events2 = []
            async for event in source:
                events2.append(event)
                if len(events2) >= 1:
                    await source.close()
                    break

            assert events2 == [{"x": 1}]


class TestSourceBinding:
    """Tests for SourceBinding wiring."""

    @pytest.mark.asyncio
    async def test_binding_connects_source_to_projection(self):
        """SourceBinding wires source → stream → projection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.jsonl"
            # Write events
            path.write_text('{"container": "nginx", "service": "nginx", "state": "running", "healthy": true}\n')

            spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
            proj = SpecProjection(spec)

            binding = create_binding_for_tailer(
                name="vm-health",
                path=path,
                projection=proj,
                poll_interval=0.1,
            )

            # Start binding
            task = await start_binding(binding)

            # Wait for event to flow through
            for _ in range(10):
                await asyncio.sleep(0.1)
                if proj.version > 0:
                    break

            # Stop binding
            await stop_binding(binding)

            # Verify projection received the event
            assert proj.version > 0
            assert "nginx" in proj.state["containers"]

    @pytest.mark.asyncio
    async def test_binding_enable_recording(self):
        """SourceBinding can enable recording to FileWriter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"container": "redis", "service": "redis", "state": "running", "healthy": true}\n')

            spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
            proj = SpecProjection(spec)

            binding = create_binding_for_tailer(
                name="vm-health",
                path=source_path,
                projection=proj,
                poll_interval=0.1,
            )

            # Enable recording
            output_dir = Path(tmpdir) / "output"
            binding.enable_recording(output_dir, "test-vm")

            # Start binding
            task = await start_binding(binding)

            # Wait for event to flow through
            for _ in range(10):
                await asyncio.sleep(0.1)
                if proj.version > 0:
                    break

            # Stop binding
            await stop_binding(binding)

            # Check recording file exists
            recorded = output_dir / "test-vm" / "vm-health.jsonl"
            assert recorded.exists()
            content = recorded.read_text()
            assert "redis" in content

    @pytest.mark.asyncio
    async def test_binding_disable_recording(self):
        """SourceBinding can disable recording."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.jsonl"
            source_path.write_text('{"container": "x", "service": "x", "state": "r", "healthy": true}\n')

            spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
            proj = SpecProjection(spec)

            binding = create_binding_for_tailer(
                name="vm-health",
                path=source_path,
                projection=proj,
            )

            # Enable then disable recording
            output_dir = Path(tmpdir) / "output"
            binding.enable_recording(output_dir, "test-vm")
            binding.disable_recording()

            # Writer should be gone
            assert binding.writer is None
            assert binding.tap is None


class TestStreamIntegration:
    """Integration tests for the stream data flow."""

    @pytest.mark.asyncio
    async def test_stream_tap_delivers_to_projection(self):
        """Events emitted to stream are delivered to tapped projection."""
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj = SpecProjection(spec)

        stream: Stream[dict] = Stream()
        stream.tap(proj)

        await stream.emit({
            "container": "memcached",
            "service": "memcached",
            "state": "running",
            "healthy": True,
        })

        assert proj.version == 1
        assert "memcached" in proj.state["containers"]

    @pytest.mark.asyncio
    async def test_multiple_taps_receive_events(self):
        """Multiple taps all receive the same events."""
        spec = parse_projection_spec(SPECS_DIR / "vm-health.projection.kdl")
        proj1 = SpecProjection(spec)
        proj2 = SpecProjection(spec)

        stream: Stream[dict] = Stream()
        stream.tap(proj1)
        stream.tap(proj2)

        await stream.emit({
            "container": "pg",
            "service": "postgres",
            "state": "running",
            "healthy": True,
        })

        assert proj1.version == 1
        assert proj2.version == 1
        assert "pg" in proj1.state["containers"]
        assert "pg" in proj2.state["containers"]
