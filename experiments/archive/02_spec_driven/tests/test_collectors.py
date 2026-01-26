"""Tests for collector discovery system."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.collectors.spec import (
    CollectorSpec,
    FieldMapping,
    parse_collector_spec,
    build_poll_collector,
    build_stream_collector,
)
from framework.collectors.discovery import (
    derive_name,
    discover_collectors,
    discover_and_register,
)
from framework.sources.poll import PollSource
from framework.sources.stream import StreamSource


class TestFieldMapping:
    def test_source_key_uses_name_when_no_from(self):
        fm = FieldMapping(name="id")
        assert fm.source_key == "id"

    def test_source_key_uses_from_when_specified(self):
        fm = FieldMapping(name="id", source="ID")
        assert fm.source_key == "ID"


class TestCollectorSpec:
    def test_transform_record_with_fields(self):
        spec = CollectorSpec(
            name="test",
            command="echo hi",
            fields=(
                FieldMapping(name="id", source="ID"),
                FieldMapping(name="name", source="Names"),
            ),
        )
        raw = {"ID": "abc123", "Names": "nginx", "Extra": "ignored"}
        result = spec.transform_record(raw)
        assert result == {"id": "abc123", "name": "nginx"}

    def test_transform_record_no_fields_passthrough(self):
        spec = CollectorSpec(name="test", command="echo hi")
        raw = {"foo": "bar", "baz": 123}
        result = spec.transform_record(raw)
        assert result == raw

    def test_transform_record_with_coercion(self):
        spec = CollectorSpec(
            name="test",
            command="echo",
            fields=(
                FieldMapping(name="cpu", source="CPUPerc", coerce="float"),
                FieldMapping(name="count", source="Count", coerce="int"),
                FieldMapping(name="active", source="Active", coerce="bool"),
            ),
        )
        raw = {"CPUPerc": "45.5%", "Count": "10", "Active": "true"}
        result = spec.transform_record(raw)
        assert result == {"cpu": 45.5, "count": 10, "active": True}

    def test_parse_output_json(self):
        spec = CollectorSpec(name="test", command="echo", parse="json")
        output = '[{"id": "1"}, {"id": "2"}]'
        result = spec.parse_output(output)
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_parse_output_json_single(self):
        spec = CollectorSpec(name="test", command="echo", parse="json")
        output = '{"id": "1"}'
        result = spec.parse_output(output)
        assert result == [{"id": "1"}]

    def test_parse_output_jsonl(self):
        spec = CollectorSpec(name="test", command="echo", parse="jsonl")
        output = '{"id": "1"}\n{"id": "2"}\n'
        result = spec.parse_output(output)
        assert result == [{"id": "1"}, {"id": "2"}]

    def test_parse_output_text(self):
        spec = CollectorSpec(name="test", command="echo", parse="text")
        output = "hello world\n"
        result = spec.parse_output(output)
        assert result == [{"output": "hello world"}]


class TestParseCollectorSpec:
    def test_parse_basic_collector(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.collector"
            path.write_text('''
                collector {
                    command "docker ps --format json"
                    parse "jsonl"
                    mode "collect"
                }
            ''')
            spec = parse_collector_spec(path)
            assert spec.command == "docker ps --format json"
            assert spec.parse == "jsonl"
            assert spec.mode == "collect"

    def test_parse_with_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.collector"
            path.write_text('''
                collector {
                    command "docker ps --format json"
                    parse "jsonl"
                    mode "collect"

                    fields {
                        id from="ID"
                        name from="Names"
                        cpu from="CPUPerc" as="float"
                    }
                }
            ''')
            spec = parse_collector_spec(path)
            assert len(spec.fields) == 3
            assert spec.fields[0].name == "id"
            assert spec.fields[0].source == "ID"
            assert spec.fields[1].name == "name"
            assert spec.fields[1].source == "Names"
            assert spec.fields[2].name == "cpu"
            assert spec.fields[2].source == "CPUPerc"
            assert spec.fields[2].coerce == "float"

    def test_parse_stream_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.collector"
            path.write_text('''
                collector {
                    command "docker events --format json"
                    parse "jsonl"
                    mode "stream"
                }
            ''')
            spec = parse_collector_spec(path)
            assert spec.mode == "stream"

    def test_missing_command_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "test.collector"
            path.write_text('''
                collector {
                    parse "jsonl"
                }
            ''')
            with pytest.raises(ValueError, match="Missing command"):
                parse_collector_spec(path)


class TestDeriveName:
    def test_single_level(self):
        base = Path("/collectors")
        path = Path("/collectors/uptime.collector")
        assert derive_name(path, base) == "uptime"

    def test_nested_path(self):
        base = Path("/collectors")
        path = Path("/collectors/docker/containers.collector")
        assert derive_name(path, base) == "docker.containers"

    def test_deep_nesting(self):
        base = Path("/collectors")
        path = Path("/collectors/cloud/aws/ec2.py")
        assert derive_name(path, base) == "cloud.aws.ec2"


class TestDiscovery:
    def test_discover_collector_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Create docker/containers.collector
            docker_dir = base / "docker"
            docker_dir.mkdir()
            (docker_dir / "containers.collector").write_text('''
                collector {
                    command "docker ps --format json"
                    parse "jsonl"
                    mode "collect"
                }
            ''')
            # Create system/uptime.collector
            system_dir = base / "system"
            system_dir.mkdir()
            (system_dir / "uptime.collector").write_text('''
                collector {
                    command "uptime"
                    parse "text"
                    mode "collect"
                }
            ''')

            registry = discover_collectors(base)
            assert "docker.containers" in registry
            assert "system.uptime" in registry
            assert registry["docker.containers"][0] == "collect"
            assert registry["system.uptime"][0] == "collect"

    def test_discover_python_collectors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            proxmox_dir = base / "proxmox"
            proxmox_dir.mkdir()
            (proxmox_dir / "vms.py").write_text('''
__collector__ = {"mode": "collect"}

async def collect(ssh):
    return [{"vmid": "100", "name": "test"}]
''')

            registry = discover_collectors(base)
            assert "proxmox.vms" in registry
            assert registry["proxmox.vms"][0] == "collect"

    def test_python_without_metadata_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "helper.py").write_text('''
def some_utility():
    pass
''')

            registry = discover_collectors(base)
            assert "helper" not in registry

    def test_discover_mixed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / "uptime.collector").write_text('''
                collector {
                    command "uptime"
                    parse "text"
                    mode "collect"
                }
            ''')
            (base / "custom.py").write_text('''
__collector__ = {"mode": "stream"}

async def stream(ssh):
    yield {"event": "test"}
''')

            registry = discover_collectors(base)
            assert "uptime" in registry
            assert "custom" in registry
            assert registry["uptime"][0] == "collect"
            assert registry["custom"][0] == "stream"

    def test_discover_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = discover_collectors(Path(tmpdir))
            assert registry == {}

    def test_discover_nonexistent_dir(self):
        registry = discover_collectors(Path("/nonexistent/path"))
        assert registry == {}


class TestBuildCollector:
    def test_build_poll_collector(self):
        spec = CollectorSpec(
            name="test",
            command="echo test",
            parse="text",
            mode="collect",
        )
        collector = build_poll_collector(spec)
        # Verify it's a callable
        assert callable(collector)

    def test_build_stream_collector(self):
        spec = CollectorSpec(
            name="test",
            command="tail -f /var/log/syslog",
            parse="text",
            mode="stream",
        )
        collector = build_stream_collector(spec)
        assert callable(collector)


class TestSourceErrorEvents:
    def test_poll_source_emits_error_on_failure(self):
        ssh = MagicMock()
        failing_collector = AsyncMock(side_effect=Exception("Connection refused"))

        source = PollSource(
            ssh,
            failing_collector,
            interval=1.0,
            host="test-host",
            collector_name="test.collector",
        )

        async def get_event():
            return await source.__anext__()

        event = asyncio.run(get_event())
        assert event["type"] == "source.error"
        assert event["host"] == "test-host"
        assert event["collector"] == "test.collector"
        assert "Connection refused" in event["error"]

    def test_poll_source_continues_after_error(self):
        ssh = MagicMock()
        # First call fails, second succeeds
        call_count = [0]

        async def alternating_collector(ssh):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("Temporary failure")
            return [{"data": "success"}]

        source = PollSource(
            ssh,
            alternating_collector,
            interval=0.01,
            host="test-host",
            collector_name="test.collector",
        )

        async def get_events():
            events = []
            events.append(await source.__anext__())  # Error event
            events.append(await source.__anext__())  # Success event
            return events

        events = asyncio.run(get_events())
        assert events[0]["type"] == "source.error"
        assert events[1]["data"] == "success"

    def test_stream_source_emits_error_on_failure(self):
        ssh = MagicMock()

        def failing_collector(ssh):
            raise Exception("Stream failed")

        source = StreamSource(
            ssh,
            failing_collector,
            host="test-host",
            collector_name="test.collector",
        )

        async def get_event():
            return await source.__anext__()

        event = asyncio.run(get_event())
        assert event["type"] == "source.error"
        assert event["host"] == "test-host"
        assert event["collector"] == "test.collector"
        assert "Stream failed" in event["error"]
