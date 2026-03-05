"""Tests for fetch — kind/key parsing and key matching."""

import pytest

from loops.commands.fetch import _split_kind_key, _item_matches_key, _fact_matches_key


class TestSplitKindKey:
    def test_plain_kind(self):
        assert _split_kind_key("thread") == ("thread", None)

    def test_kind_with_key(self):
        assert _split_kind_key("thread/fold-state-types") == ("thread", "fold-state-types")

    def test_key_with_slash(self):
        # Split on first / only — key can contain /
        assert _split_kind_key("decision/arch/emit-runtime") == ("decision", "arch/emit-runtime")

    def test_none(self):
        assert _split_kind_key(None) == (None, None)


class TestItemMatchesKey:
    def _item(self, **payload):
        from atoms import FoldItem
        return FoldItem(payload=payload)

    def test_matches_key_field(self):
        item = self._item(name="fold-state-types", status="open")
        assert _item_matches_key(item, "name", "fold-state-types")

    def test_case_insensitive(self):
        item = self._item(name="Fold-State-Types")
        assert _item_matches_key(item, "name", "fold-state-types")

    def test_no_match(self):
        item = self._item(name="other-thread")
        assert not _item_matches_key(item, "name", "fold-state-types")

    def test_falls_back_to_common_fields(self):
        item = self._item(topic="auth", position="JWT")
        assert _item_matches_key(item, None, "auth")

    def test_key_field_matches_first(self):
        item = self._item(name="real", topic="other")
        assert _item_matches_key(item, "name", "real")
        # Also matches on fallback fields
        assert _item_matches_key(item, "name", "other")


class TestFactMatchesKey:
    def test_matches_payload_field(self):
        fact = {"kind": "thread", "payload": {"name": "fold-state-types"}}
        assert _fact_matches_key(fact, "name", "fold-state-types")

    def test_case_insensitive(self):
        fact = {"kind": "task", "payload": {"name": "Daemon-Local"}}
        assert _fact_matches_key(fact, "name", "daemon-local")

    def test_no_match(self):
        fact = {"kind": "thread", "payload": {"name": "other"}}
        assert not _fact_matches_key(fact, "name", "fold-state-types")

    def test_empty_payload(self):
        fact = {"kind": "thread", "payload": {}}
        assert not _fact_matches_key(fact, "name", "anything")
