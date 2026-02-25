"""Tests for tools/discord_chat.py."""

import json
import unittest
from unittest.mock import patch, MagicMock

import sys
from pathlib import Path

# Add tools to path so we can import discord_chat
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import discord_chat


class TestPost(unittest.TestCase):
    @patch.dict("os.environ", {
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
    })
    @patch("discord_chat.urlopen")
    def test_post_sends_webhook_with_persona(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        discord_chat.post_message(
            persona="mrbits",
            message="hello from test",
            personas={"mrbits": {"avatar_url": "https://example.com/mrbits.png"}},
        )

        mock_urlopen.assert_called_once()
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        body = json.loads(req.data)
        assert body["username"] == "mrbits"
        assert body["avatar_url"] == "https://example.com/mrbits.png"
        assert body["content"] == "hello from test"

    @patch.dict("os.environ", {
        "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
    })
    @patch("discord_chat.urlopen")
    def test_post_unknown_persona_uses_name_only(self, mock_urlopen):
        mock_response = MagicMock()
        mock_response.status = 204
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        discord_chat.post_message(
            persona="unknown",
            message="test",
            personas={},
        )

        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data)
        assert body["username"] == "unknown"
        assert "avatar_url" not in body

    def test_post_missing_webhook_url_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SystemExit):
                discord_chat.post_message("mrbits", "hi", {})
