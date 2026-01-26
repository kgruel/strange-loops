"""Tests for inventory loader."""

import tempfile
from pathlib import Path

import pytest

from framework.inventory import HostInfo, load_ansible_inventory, _parse_inventory


class TestHostInfo:
    def test_fields(self):
        host = HostInfo(
            name="media",
            host="192.168.1.40",
            user="deploy",
            key_file="/home/user/.ssh/key",
            common_args="-o StrictHostKeyChecking=no",
        )
        assert host.name == "media"
        assert host.host == "192.168.1.40"
        assert host.user == "deploy"
        assert host.key_file == "/home/user/.ssh/key"
        assert host.common_args == "-o StrictHostKeyChecking=no"

    def test_default_common_args(self):
        host = HostInfo(name="test", host="1.2.3.4", user="root", key_file="")
        assert host.common_args == ""


class TestLoadAnsibleInventory:
    def test_parse_basic_inventory(self):
        inventory = {
            "all": {
                "children": {
                    "vms": {
                        "hosts": {
                            "media": {
                                "ansible_host": "192.168.1.40",
                                "ansible_user": "deploy",
                                "ansible_ssh_private_key_file": "~/.ssh/key",
                            }
                        }
                    }
                },
                "vars": {
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no"
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert len(hosts) == 1
        assert hosts[0].name == "media"
        assert hosts[0].host == "192.168.1.40"
        assert hosts[0].user == "deploy"
        assert hosts[0].common_args == "-o StrictHostKeyChecking=no"

    def test_common_args_extraction(self):
        inventory = {
            "all": {
                "children": {
                    "vms": {
                        "hosts": {
                            "test": {"ansible_host": "1.2.3.4"}
                        }
                    }
                },
                "vars": {
                    "ansible_ssh_common_args": "-o ProxyCommand='ssh jump -W %h:%p'"
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert hosts[0].common_args == "-o ProxyCommand='ssh jump -W %h:%p'"

    def test_common_args_missing(self):
        inventory = {
            "all": {
                "children": {
                    "vms": {
                        "hosts": {
                            "test": {"ansible_host": "1.2.3.4"}
                        }
                    }
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert hosts[0].common_args == ""

    def test_path_expansion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inv_path = Path(tmpdir) / "inventory.yml"
            inv_path.write_text("""
all:
  children:
    vms:
      hosts:
        test:
          ansible_host: "1.2.3.4"
          ansible_ssh_private_key_file: "~/.ssh/mykey"
""")
            hosts = load_ansible_inventory(inv_path)
            # Path should be expanded
            assert "~" not in hosts[0].key_file
            assert hosts[0].key_file.endswith(".ssh/mykey")

    def test_multiple_groups(self):
        inventory = {
            "all": {
                "children": {
                    "vms": {
                        "hosts": {
                            "media": {"ansible_host": "192.168.1.40"},
                            "infra": {"ansible_host": "192.168.1.30"},
                        }
                    },
                    "runners": {
                        "hosts": {
                            "runner_01": {"ansible_host": "192.168.1.50"},
                        }
                    }
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert len(hosts) == 3
        names = {h.name for h in hosts}
        assert names == {"media", "infra", "runner_01"}

    def test_default_user(self):
        inventory = {
            "all": {
                "children": {
                    "vms": {
                        "hosts": {
                            "test": {"ansible_host": "1.2.3.4"}
                            # No ansible_user specified
                        }
                    }
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert hosts[0].user == "deploy"

    def test_empty_inventory(self):
        hosts = _parse_inventory({})
        assert hosts == []

    def test_nested_children(self):
        """Inventory can have nested children groups."""
        inventory = {
            "all": {
                "children": {
                    "netbird_peers": {
                        "children": {
                            "vms": {
                                "hosts": {
                                    "nested_host": {"ansible_host": "10.0.0.1"}
                                }
                            }
                        }
                    }
                },
                "vars": {
                    "ansible_ssh_common_args": "-o BatchMode=yes"
                }
            }
        }
        hosts = _parse_inventory(inventory)
        assert len(hosts) == 1
        assert hosts[0].name == "nested_host"
        assert hosts[0].common_args == "-o BatchMode=yes"

    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inv_path = Path(tmpdir) / "inventory.yml"
            inv_path.write_text("""
all:
  children:
    vms:
      hosts:
        media:
          ansible_host: "192.168.1.40"
          ansible_user: "deploy"
          ansible_ssh_private_key_file: "~/.ssh/homelab"
        infra:
          ansible_host: "192.168.1.30"
          ansible_user: "admin"
  vars:
    ansible_ssh_common_args: "-o StrictHostKeyChecking=no"
""")
            hosts = load_ansible_inventory(inv_path)
            assert len(hosts) == 2
            media = next(h for h in hosts if h.name == "media")
            assert media.host == "192.168.1.40"
            assert media.user == "deploy"
            assert media.common_args == "-o StrictHostKeyChecking=no"
