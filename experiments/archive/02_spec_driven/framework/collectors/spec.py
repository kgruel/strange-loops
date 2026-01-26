"""CollectorSpec: parse .collector KDL files.

Collectors are declared in KDL with command, parse mode, and field mappings:

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

The parser returns a CollectorSpec dataclass which can be used to build
a collector function that transforms command output into events.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, TYPE_CHECKING

import kdl

if TYPE_CHECKING:
    from ..ssh_session import SSHSession


@dataclass(frozen=True)
class FieldMapping:
    """Maps a field from command output to event output.

    Attributes:
        name: Output field name in the event
        source: Source field name in command output (from=)
        coerce: Type to coerce to (as=): str, int, float, bool
    """
    name: str
    source: str | None = None  # None means use name as source
    coerce: str | None = None  # None means no coercion

    @property
    def source_key(self) -> str:
        """The key to read from source data."""
        return self.source if self.source is not None else self.name


@dataclass(frozen=True)
class CollectorSpec:
    """Parsed collector specification.

    Attributes:
        name: Collector name (derived from path)
        command: Shell command to run
        parse: Output format: text, json, jsonl
        mode: Collection mode: collect (poll), stream
        fields: Field mappings from command output to events
    """
    name: str
    command: str
    parse: str = "text"  # text, json, jsonl
    mode: str = "collect"  # collect, stream
    fields: tuple[FieldMapping, ...] = ()

    def transform_record(self, raw: dict) -> dict:
        """Transform a raw record using field mappings.

        If no fields are specified, passes through raw data.
        """
        if not self.fields:
            return raw

        result = {}
        for fm in self.fields:
            if fm.source_key in raw:
                value = raw[fm.source_key]
                if fm.coerce:
                    value = _coerce(value, fm.coerce)
                result[fm.name] = value
        return result

    def parse_output(self, output: str) -> list[dict]:
        """Parse command output according to parse mode."""
        match self.parse:
            case "json":
                data = json.loads(output)
                if isinstance(data, list):
                    return [self.transform_record(r) for r in data]
                return [self.transform_record(data)]
            case "jsonl":
                records = []
                for line in output.strip().split("\n"):
                    if line:
                        records.append(self.transform_record(json.loads(line)))
                return records
            case "text":
                # Text mode: return single record with 'output' field
                return [{"output": output.strip()}]
            case _:
                raise ValueError(f"Unknown parse mode: {self.parse}")


def _coerce(value: Any, type_str: str) -> Any:
    """Coerce a value to the specified type."""
    if value is None:
        return None

    match type_str:
        case "str":
            return str(value)
        case "int":
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, str):
                # Handle percentage strings like "45.5%"
                clean = value.rstrip("%").strip()
                try:
                    return int(float(clean))
                except ValueError:
                    return value
            return int(value)
        case "float":
            if isinstance(value, bool):
                return float(value)
            if isinstance(value, str):
                clean = value.rstrip("%").strip()
                try:
                    return float(clean)
                except ValueError:
                    return value
            return float(value)
        case "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes")
            return bool(value)
        case _:
            return value


def parse_collector_spec(path: Path, name: str | None = None) -> CollectorSpec:
    """Parse a .collector KDL file into a CollectorSpec.

    Args:
        path: Path to the .collector file
        name: Override for collector name (default: derived from filename)
    """
    doc = kdl.parse(path.read_text())

    command = ""
    parse_mode = "text"
    mode = "collect"
    fields: list[FieldMapping] = []

    # Top-level should be a single `collector` node
    for node in doc.nodes:
        if node.name == "collector":
            for child in node.nodes or []:
                if child.name == "command":
                    command = str(child.args[0]) if child.args else ""
                elif child.name == "parse":
                    parse_mode = str(child.args[0]) if child.args else "text"
                elif child.name == "mode":
                    mode = str(child.args[0]) if child.args else "collect"
                elif child.name == "fields":
                    fields = _parse_fields(child)

    if not command:
        raise ValueError(f"Missing command in collector spec: {path}")

    collector_name = name or path.stem

    return CollectorSpec(
        name=collector_name,
        command=command,
        parse=parse_mode,
        mode=mode,
        fields=tuple(fields),
    )


def _parse_fields(node: kdl.Node) -> list[FieldMapping]:
    """Parse fields block into FieldMapping list."""
    fields: list[FieldMapping] = []
    for child in node.nodes or []:
        field_name = child.name
        source = child.props.get("from")
        coerce = child.props.get("as")
        fields.append(FieldMapping(
            name=field_name,
            source=str(source) if source is not None else None,
            coerce=str(coerce) if coerce is not None else None,
        ))
    return fields


def build_poll_collector(spec: CollectorSpec) -> Callable[["SSHSession"], list[dict]]:
    """Build a poll collector function from a spec.

    Returns an async function that runs the command and parses output.
    """
    async def collector(ssh: "SSHSession") -> list[dict]:
        output = await ssh.run(spec.command)
        return spec.parse_output(output)

    return collector


async def build_stream_collector_iter(
    spec: CollectorSpec, ssh: "SSHSession"
) -> AsyncIterator[dict]:
    """Build a streaming collector iterator from a spec.

    Yields events as lines arrive from the streaming command.
    """
    async for line in ssh.stream(spec.command):
        if line:
            match spec.parse:
                case "json" | "jsonl":
                    yield spec.transform_record(json.loads(line))
                case "text":
                    yield {"output": line.strip()}
                case _:
                    yield {"output": line}


def build_stream_collector(
    spec: CollectorSpec,
) -> Callable[["SSHSession"], AsyncIterator[dict]]:
    """Build a stream collector function from a spec."""
    def collector(ssh: "SSHSession") -> AsyncIterator[dict]:
        return build_stream_collector_iter(spec, ssh)

    return collector
