"""Tests for tools/discord_chat.py."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add tools to path so we can import discord_chat
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))

import discord_chat


class TestPost(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
        },
    )
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

    @patch.dict(
        "os.environ",
        {
            "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/123/abc",
        },
    )
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
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit):
            discord_chat.post_message("mrbits", "hi", {})


class TestRead(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "DISCORD_BOT_TOKEN": "Bot fake-token",
            "DISCORD_CHANNEL_ID": "999888777",
        },
    )
    @patch("discord_chat.urlopen")
    def test_read_returns_formatted_messages(self, mock_urlopen):
        api_response = json.dumps(
            [
                {"author": {"username": "mrbits"}, "content": "hello world"},
                {"author": {"username": "noodle"}, "content": "hey mrbits"},
            ]
        ).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = api_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = discord_chat.read_messages(limit=10)

        assert len(result) == 2
        # Discord API returns newest first, we reverse for chronological
        assert result[0] == "[noodle] hey mrbits"
        assert result[1] == "[mrbits] hello world"

    @patch.dict(
        "os.environ",
        {
            "DISCORD_BOT_TOKEN": "Bot fake-token",
            "DISCORD_CHANNEL_ID": "999888777",
        },
    )
    @patch("discord_chat.urlopen")
    def test_read_respects_limit(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"[]"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        discord_chat.read_messages(limit=5)

        req = mock_urlopen.call_args[0][0]
        assert "limit=5" in req.full_url

    def test_read_missing_token_raises(self):
        with patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit):
            discord_chat.read_messages()
