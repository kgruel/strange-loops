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


@dataclass(frozen=True)
class VMInfo:
    """A VM from the inventory."""
    name: str
    host: str
    user: str
    key_file: str
    service_type: str


@dataclass(frozen=True)
class AppSpec:
    """Parsed app specification."""
    name: str
    about: str
    watch: bool
    inventory_path: Path
    vms: tuple[VMInfo, ...]
    projections: tuple[ProjectionSpec, ...]  # per-connection specs


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
    uses: list[str] = []

    for node in doc.nodes:
        if node.name == "app":
            name = str(node.args[0]) if node.args else ""
            for child in node.nodes or []:
                if child.name == "about":
                    about = str(child.args[0]) if child.args else ""
                elif child.name == "watch":
                    watch = bool(child.args[0]) if child.args else True
                elif child.name == "inventory":
                    inventory_path = str(child.args[0]) if child.args else ""
                elif child.name == "per-connection":
                    for use_node in child.nodes or []:
                        if use_node.name == "use":
                            spec_name = str(use_node.args[0]) if use_node.args else ""
                            if spec_name:
                                uses.append(spec_name)

    if not name:
        raise ValueError(f"Missing app name in {path}")

    # Resolve inventory
    inv_path = _resolve_path(inventory_path, path.parent)
    vms = _load_inventory(inv_path) if inv_path.exists() else ()

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
        vms=tuple(vms),
        projections=tuple(projections),
    )


def _resolve_path(path_str: str, base: Path) -> Path:
    """Resolve a path relative to a base directory."""
    p = Path(path_str).expanduser()
    if p.is_absolute():
        return p
    return (base / p).resolve()


def _load_inventory(path: Path) -> list[VMInfo]:
    """Load VMs from an Ansible inventory YAML."""
    data = yaml.safe_load(path.read_text())

    vms: list[VMInfo] = []

    # Walk the inventory structure: all.children.{group}.hosts.{name}
    children = data.get("all", {}).get("children", {})
    for group_name, group in children.items():
        hosts = group.get("hosts", {})
        if not hosts:
            continue
        for host_name, host_data in hosts.items():
            if not isinstance(host_data, dict):
                continue
            vms.append(VMInfo(
                name=host_name,
                host=host_data.get("ansible_host", ""),
                user=host_data.get("ansible_user", ""),
                key_file=host_data.get("ansible_ssh_private_key_file", ""),
                service_type=host_data.get("service_type", ""),
            ))

    return vms
