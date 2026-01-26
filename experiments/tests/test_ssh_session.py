"""Tests for SSHSession common_args parsing."""

import sys
from pathlib import Path

# Import directly from module to avoid framework/__init__.py (which pulls kdl)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from framework.ssh_session import _parse_common_args, SSHSession


class TestParseCommonArgs:
    """Tests for _parse_common_args helper."""

    def test_empty_args_returns_empty_dict(self):
        """Empty string returns empty dict."""
        assert _parse_common_args("") == {}

    def test_parse_proxy_jump_short_form(self):
        """-J jump_host parses to tunnel."""
        result = _parse_common_args("-J bastion.example.com")
        assert result == {"tunnel": "bastion.example.com"}

    def test_parse_proxy_jump_with_user(self):
        """-J user@host parses correctly."""
        result = _parse_common_args("-J admin@bastion.example.com")
        assert result == {"tunnel": "admin@bastion.example.com"}

    def test_parse_proxy_jump_long_form(self):
        """-o ProxyJump=host parses to tunnel."""
        result = _parse_common_args("-o ProxyJump=jump.example.com")
        assert result == {"tunnel": "jump.example.com"}

    def test_parse_port_short_form(self):
        """-p port parses to port."""
        result = _parse_common_args("-p 2222")
        assert result == {"port": 2222}

    def test_parse_port_long_form(self):
        """-o Port=port parses to port."""
        result = _parse_common_args("-o Port=2222")
        assert result == {"port": 2222}

    def test_parse_multiple_args(self):
        """Multiple args combine into one dict."""
        result = _parse_common_args("-J bastion -p 2222")
        assert result == {"tunnel": "bastion", "port": 2222}

    def test_parse_quoted_args(self):
        """Quoted args with spaces parse correctly."""
        result = _parse_common_args('-J "bastion host"')
        assert result == {"tunnel": "bastion host"}

    def test_unknown_args_ignored(self):
        """Unknown args are silently ignored."""
        result = _parse_common_args("-v -X -J bastion")
        assert result == {"tunnel": "bastion"}


class TestSSHSessionDataclass:
    """Tests for SSHSession dataclass fields."""

    def test_common_args_defaults_to_empty(self):
        """common_args defaults to empty string."""
        session = SSHSession(host="test", user="user", key_file="/path/to/key")
        assert session.common_args == ""

    def test_common_args_can_be_set(self):
        """common_args can be provided."""
        session = SSHSession(
            host="test",
            user="user",
            key_file="/path/to/key",
            common_args="-J bastion",
        )
        assert session.common_args == "-J bastion"

    def test_backward_compatible_construction(self):
        """Original 3-arg construction still works."""
        session = SSHSession("host", "user", "/key")
        assert session.host == "host"
        assert session.user == "user"
        assert session.key_file == "/key"
        assert session.common_args == ""
