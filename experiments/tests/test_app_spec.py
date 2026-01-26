"""Tests for app spec parsing, especially inventory syntax."""

import tempfile
from pathlib import Path

import pytest

from framework.app_spec import (
    AppSpec,
    HostInfo,
    VMInfo,
    parse_app_spec,
    _parse_inventory_node,
)


class TestInventorySyntax:
    """Tests for inventory node parsing."""

    def test_legacy_positional_syntax(self):
        """inventory "path" syntax (backward compat)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        test:
          ansible_host: "1.2.3.4"
          ansible_user: "deploy"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert app.inventory_type == "ansible"
            assert app.inventory_path == (tmp / "inventory.yml").resolve()
            assert len(app.hosts) == 1
            assert app.hosts[0].name == "test"

    def test_new_from_path_syntax(self):
        """inventory from="ansible" path="..." syntax."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        host1:
          ansible_host: "10.0.0.1"
        host2:
          ansible_host: "10.0.0.2"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory from="ansible" path="inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert app.inventory_type == "ansible"
            assert len(app.hosts) == 2

    def test_from_defaults_to_ansible(self):
        """inventory path="..." without from= defaults to ansible."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        test:
          ansible_host: "1.2.3.4"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory path="inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert app.inventory_type == "ansible"

    def test_path_expansion(self):
        """Paths with ~ are expanded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory from="ansible" path="~/nonexistent.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            # Path should be expanded, even if file doesn't exist
            assert "~" not in str(app.inventory_path)


class TestHostsField:
    """Tests for hosts field and vms backward compat."""

    def test_hosts_field(self):
        """AppSpec.hosts contains HostInfo instances."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        media:
          ansible_host: "192.168.1.40"
          ansible_user: "deploy"
          service_type: "media"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert len(app.hosts) == 1
            assert isinstance(app.hosts[0], HostInfo)
            assert app.hosts[0].name == "media"
            assert app.hosts[0].host == "192.168.1.40"

    def test_vms_property_aliases_hosts(self):
        """AppSpec.vms property returns same as hosts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        test:
          ansible_host: "1.2.3.4"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory "inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert app.vms == app.hosts
            assert len(app.vms) == 1

    def test_vminfo_alias(self):
        """VMInfo is an alias for HostInfo."""
        assert VMInfo is HostInfo


class TestCommonArgs:
    """Tests for common_args propagation from inventory."""

    def test_common_args_in_hostinfo(self):
        """common_args from inventory is available in HostInfo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("""
all:
  children:
    vms:
      hosts:
        test:
          ansible_host: "1.2.3.4"
  vars:
    ansible_ssh_common_args: "-o ProxyJump=jump"
""")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory from="ansible" path="inventory.yml"
                }
            ''')
            app = parse_app_spec(tmp / "test.app.kdl")
            assert app.hosts[0].common_args == "-o ProxyJump=jump"


class TestUnknownInventoryType:
    """Tests for error handling on unknown inventory types."""

    def test_unknown_type_raises(self):
        """Unknown inventory type raises ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            (tmp / "inventory.yml").write_text("all: {}")
            (tmp / "test.app.kdl").write_text('''
                app "test" {
                    inventory from="unknown" path="inventory.yml"
                }
            ''')
            with pytest.raises(ValueError, match="Unknown inventory type: unknown"):
                parse_app_spec(tmp / "test.app.kdl")
