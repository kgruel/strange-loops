"""Ansible inventory loader.

Parses Ansible inventory YAML into HostInfo dataclass with full SSH config.
Follows the pattern from gruel.network's host_config_from_inventory().
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class HostInfo:
    """SSH connection info for a host from Ansible inventory.

    Attributes:
        name: Host identifier (inventory key)
        host: ansible_host (IP or FQDN)
        user: ansible_user (default: "deploy")
        key_file: ansible_ssh_private_key_file (expanded path)
        common_args: ansible_ssh_common_args from all.vars
        service_type: Optional service type metadata (for backward compat with VMInfo)
    """
    name: str
    host: str
    user: str
    key_file: str
    common_args: str = ""
    service_type: str = ""


def load_ansible_inventory(path: Path) -> list[HostInfo]:
    """Load hosts from an Ansible inventory YAML file.

    Traverses: all.children.{group}.hosts.{name}
    Extracts: all.vars.ansible_ssh_common_args as global default

    Args:
        path: Path to the inventory YAML file

    Returns:
        Flat list of HostInfo for all hosts in all groups
    """
    data = yaml.safe_load(path.read_text())
    return _parse_inventory(data)


def _parse_inventory(data: dict[str, Any]) -> list[HostInfo]:
    """Parse inventory dict into list of HostInfo."""
    if not data:
        return []

    all_section = data.get("all", {})
    children = all_section.get("children", {})
    vars_ = all_section.get("vars", {})

    # Extract global common_args from all.vars
    common_args = str(vars_.get("ansible_ssh_common_args") or "").strip()

    hosts: list[HostInfo] = []

    # Walk all groups under children
    for group in children.values():
        if not isinstance(group, dict):
            continue

        # Check for hosts directly in this group
        group_hosts = group.get("hosts", {})
        if group_hosts:
            hosts.extend(_parse_hosts(group_hosts, common_args))

        # Check for nested children (groups can nest)
        nested = group.get("children", {})
        for nested_group in nested.values():
            if isinstance(nested_group, dict):
                nested_hosts = nested_group.get("hosts", {})
                if nested_hosts:
                    hosts.extend(_parse_hosts(nested_hosts, common_args))

    return hosts


def _parse_hosts(hosts_dict: dict[str, Any], common_args: str) -> list[HostInfo]:
    """Parse hosts dict into list of HostInfo."""
    hosts: list[HostInfo] = []

    for host_name, host_data in hosts_dict.items():
        if not isinstance(host_data, dict):
            continue

        # Extract fields with defaults
        ansible_host = host_data.get("ansible_host", "")
        ansible_user = host_data.get("ansible_user", "deploy")
        key_file_raw = host_data.get("ansible_ssh_private_key_file", "")
        service_type = host_data.get("service_type", "")

        # Expand ~ in key_file path
        key_file = str(Path(key_file_raw).expanduser()) if key_file_raw else ""

        hosts.append(HostInfo(
            name=host_name,
            host=str(ansible_host),
            user=str(ansible_user),
            key_file=key_file,
            common_args=common_args,
            service_type=str(service_type),
        ))

    return hosts
