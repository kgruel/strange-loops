"""App spec parser: loads .app.kdl and resolves projection specs.

An app spec declares:
  - inventory source (path to ansible YAML)
  - per-connection projections (which specs to instantiate per VM)
  - watch mode (hot-reload on spec file changes)
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kdl

from .spec import ProjectionSpec, parse_projection_spec
from .inventory import HostInfo, load_ansible_inventory


# Backward compatibility alias
VMInfo = HostInfo


@dataclass(frozen=True)
class DataSourceSpec:
    """A data source: collector -> projection mapping.

    Parsed from:
        collect "docker:containers" as="container.status" into="vm-health" interval=5
        stream "docker:events" as="docker.event" into="vm-events"
    """
    collector: str        # "docker:containers"
    event_type: str       # "container.status" - maps collector output to event type
    projection: str       # "vm-health"
    mode: str            # "collect" or "stream"
    interval: int | None  # poll interval in seconds (collect only)


@dataclass(frozen=True)
class AppSpec:
    """Parsed app specification."""
    name: str
    about: str
    watch: bool
    inventory_path: Path
    inventory_type: str  # "ansible" (default), future: other formats
    hosts: tuple[HostInfo, ...]
    projections: tuple[ProjectionSpec, ...]  # per-connection specs
    data_sources: tuple[DataSourceSpec, ...]  # collector -> projection mappings

    @property
    def vms(self) -> tuple[HostInfo, ...]:
        """Backward compat alias for hosts."""
        return self.hosts

    def diff_uses(self, other: AppSpec) -> tuple[list[str], list[str]]:
        """Compare projection uses with another spec. Returns (added, removed)."""
        old_names = {p.name for p in self.projections}
        new_names = {p.name for p in other.projections}
        return sorted(new_names - old_names), sorted(old_names - new_names)


def parse_app_spec(path: Path, specs_dir: Path | None = None) -> AppSpec:
    """Parse a .app.kdl file, resolve inventory and projection specs.

    Args:
        path: Path to the .app.kdl file
        specs_dir: Directory containing .projection.kdl files.
                   Defaults to the same directory as the app spec.
    """
    if specs_dir is None:
        specs_dir = path.parent

    doc = kdl.parse(path.read_text())

    name = ""
    about = ""
    watch = False
    inventory_path = ""
    inventory_type = "ansible"  # default
    uses: list[str] = []
    data_sources: list[DataSourceSpec] = []

    for node in doc.nodes:
        if node.name == "app":
            name = str(node.args[0]) if node.args else ""
            for child in node.nodes or []:
                if child.name == "about":
                    about = str(child.args[0]) if child.args else ""
                elif child.name == "watch":
                    watch = bool(child.args[0]) if child.args else True
                elif child.name == "inventory":
                    # Parse inventory node: supports two syntaxes
                    # 1. inventory "path" (backward compat, implies from="ansible")
                    # 2. inventory from="ansible" path="..."
                    inv_path, inv_type = _parse_inventory_node(child)
                    inventory_path = inv_path
                    inventory_type = inv_type
                elif child.name == "per-connection":
                    for use_node in child.nodes or []:
                        if use_node.name == "use":
                            spec_name = str(use_node.args[0]) if use_node.args else ""
                            if spec_name:
                                uses.append(spec_name)
                        elif use_node.name in ("collect", "stream"):
                            ds = _parse_data_source(use_node)
                            if ds:
                                data_sources.append(ds)

    if not name:
        raise ValueError(f"Missing app name in {path}")

    # Resolve inventory
    inv_path = _resolve_path(inventory_path, path.parent)
    hosts = _load_inventory(inv_path, inventory_type) if inv_path.exists() else ()

    # Resolve projection specs
    projections: list[ProjectionSpec] = []
    for use_name in uses:
        spec_path = specs_dir / f"{use_name}.projection.kdl"
        if not spec_path.exists():
            raise FileNotFoundError(
                f"Projection spec not found: {spec_path} (referenced by use \"{use_name}\")"
            )
        projections.append(parse_projection_spec(spec_path))

    return AppSpec(
        name=name,
        about=about,
        watch=watch,
        inventory_path=inv_path,
        inventory_type=inventory_type,
        hosts=tuple(hosts),
        projections=tuple(projections),
        data_sources=tuple(data_sources),
    )


def _parse_data_source(node: Any) -> DataSourceSpec | None:
    """Parse a collect or stream node into a DataSourceSpec.

    Syntax:
        collect "docker:containers" as="container.status" into="vm-health" interval=5
        stream "docker:events" as="docker.event" into="vm-events"

    Returns None if required fields (as, into) are missing.
    """
    if not node.args:
        return None

    collector = str(node.args[0])
    mode = node.name  # "collect" or "stream"

    # Get properties (node.props is an OrderedDict)
    props = node.props or {}
    event_type = str(props.get("as", ""))
    projection = str(props.get("into", ""))
    interval = int(props["interval"]) if "interval" in props else None

    # Both 'as' and 'into' are required
    if not event_type or not projection:
        return None

    return DataSourceSpec(
        collector=collector,
        event_type=event_type,
        projection=projection,
        mode=mode,
        interval=interval,
    )


def _resolve_path(path_str: str, base: Path) -> Path:
    """Resolve a path relative to a base directory."""
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _parse_inventory_node(node: Any) -> tuple[str, str]:
    """Parse inventory node into (path, type).

    Supports two syntaxes:
        inventory "path"                   → path, "ansible"
        inventory from="ansible" path="~"  → path, "ansible"

    Returns (inventory_path, inventory_type).
    """
    props = node.props or {}

    # Check for new syntax: from= and path= properties
    if "path" in props:
        inv_path = str(props["path"])
        inv_type = str(props.get("from", "ansible"))
        return inv_path, inv_type

    # Backward compat: positional arg is path, type is ansible
    if node.args:
        return str(node.args[0]), "ansible"

    return "", "ansible"


def _load_inventory(path: Path, inventory_type: str) -> list[HostInfo]:
    """Load hosts from inventory file based on type."""
    if inventory_type == "ansible":
        return load_ansible_inventory(path)
    raise ValueError(f"Unknown inventory type: {inventory_type}")
