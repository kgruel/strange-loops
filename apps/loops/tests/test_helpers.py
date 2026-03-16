"""Tests for shared lens helpers — _helpers.py at 0% coverage."""

from loops.lenses._helpers import label, body, RESOLVED_STATUSES, LABEL_FIELDS


class _FakeItem:
    """Minimal FoldItem stand-in for testing."""
    def __init__(self, payload=None, ts=0):
        self.payload = payload or {}
        self.ts = ts


class TestLabel:
    def test_from_key_field(self):
        item = _FakeItem({"name": "fix-bug", "other": "x"})
        assert label(item, "name") == "fix-bug"

    def test_fallback_to_label_fields(self):
        item = _FakeItem({"topic": "design/api"})
        assert label(item, None) == "design/api"

    def test_falls_through_label_fields(self):
        item = _FakeItem({"message": "hello"})
        assert label(item, None) == "hello"

    def test_no_label_found(self):
        item = _FakeItem({"random": "data"})
        result = label(item, None)
        # Should return something (maybe empty or repr)
        assert isinstance(result, str)


class TestBody:
    def test_returns_first_non_label_value(self):
        item = _FakeItem({"name": "x", "status": "open", "message": "hello"})
        result = body(item, "name")
        assert isinstance(result, str)
        assert result in ("open", "hello")

    def test_skips_label_value(self):
        item = _FakeItem({"name": "x", "other": "x"})  # "x" matches label
        result = body(item, "name")
        # "other" has same value as label, so it's skipped
        assert result == ""

    def test_empty_payload(self):
        item = _FakeItem({})
        assert body(item, None) == ""


class TestBodyFromPayload:
    def test_basic(self):
        from loops.lenses._helpers import body_from_payload
        result = body_from_payload({"name": "x", "status": "open"}, "x")
        assert result == "open"

    def test_skips_label(self):
        from loops.lenses._helpers import body_from_payload
        result = body_from_payload({"name": "x", "other": "x"}, "x")
        assert result == ""

    def test_empty(self):
        from loops.lenses._helpers import body_from_payload
        assert body_from_payload({}, "") == ""


class TestRenderSession:
    def test_renders_items(self):
        from loops.lenses._helpers import render_session
        from atoms import FoldSection, FoldItem
        items = (
            FoldItem(payload={"name": "s1", "status": "open"}, ts=1.0),
            FoldItem(payload={"name": "s2", "status": "closed"}, ts=2.0),
        )
        section = FoldSection(kind="session", items=items, sections=(),
                             fold_type="by", key_field="name", scalars={})
        lines = render_session(section)
        assert any("s1" in line for line in lines)
        assert any("s2" in line for line in lines)


class TestFindItem:
    def test_found(self):
        from loops.lenses._helpers import find_item
        from atoms import FoldItem
        items = (
            FoldItem(payload={"name": "a"}, ts=1.0),
            FoldItem(payload={"name": "b"}, ts=2.0),
        )
        assert find_item(items, "b").payload["name"] == "b"

    def test_not_found(self):
        from loops.lenses._helpers import find_item
        from atoms import FoldItem
        items = (FoldItem(payload={"name": "a"}, ts=1.0),)
        assert find_item(items, "z") is None


class TestConstants:
    def test_resolved_statuses(self):
        assert "resolved" in RESOLVED_STATUSES
        assert "completed" in RESOLVED_STATUSES
        assert "open" not in RESOLVED_STATUSES

    def test_label_fields(self):
        assert "name" in LABEL_FIELDS
        assert "topic" in LABEL_FIELDS
