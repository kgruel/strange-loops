"""Tests for content_gist — kind-aware payload extraction."""


class TestContentGist:
    def test_empty_payload(self):
        from loops.lenses.gist import content_gist
        assert content_gist("metric", {}) == ""

    def test_non_dict_payload(self):
        from loops.lenses.gist import content_gist
        assert content_gist("metric", "raw text") == "raw text"

    def test_message_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("message", {"sender_name": "Alice", "text": "hello", "chat_title": "general"})
        assert "Alice" in result
        assert "hello" in result
        assert "general" in result

    def test_decision_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("decision", {"topic": "auth", "message": "Use JWT"})
        assert "auth" in result
        assert "JWT" in result

    def test_thread_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("thread", {"name": "perf", "status": "open"})
        assert "perf" in result
        assert "[open]" in result

    def test_task_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("task", {"name": "fix-bug", "status": "done", "summary": "Fixed it"})
        assert "fix-bug" in result
        assert "[done]" in result

    def test_dissolution_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("dissolution", {"concept": "old", "dissolved_into": "new"})
        assert "old" in result
        assert "new" in result

    def test_notes_extractor(self):
        from loops.lenses.gist import content_gist
        result = content_gist("notes", {"message": "Note content"})
        assert "Note content" in result

    def test_prefix_match(self):
        from loops.lenses.gist import content_gist
        result = content_gist("telegram.message", {"sender_name": "Bob", "text": "hi"})
        assert "Bob" in result

    def test_generic_fallback(self):
        from loops.lenses.gist import content_gist
        result = content_gist("unknown", {"title": "My Title"})
        assert "My Title" in result

    def test_first_string_fallback(self):
        from loops.lenses.gist import content_gist
        result = content_gist("unknown", {"x": 42, "y": "some text"})
        assert "some text" in result

    def test_dict_repr_fallback(self):
        from loops.lenses.gist import content_gist
        result = content_gist("unknown", {"x": 42, "y": 43})
        assert "42" in result


class TestTruncate:
    def test_short(self):
        from loops.lenses.gist import _truncate
        assert _truncate("short", 80) == "short"

    def test_long(self):
        from loops.lenses.gist import _truncate
        result = _truncate("a" * 100, 20)
        assert len(result) == 20
        assert result.endswith("\u2026")

    def test_newlines_collapsed(self):
        from loops.lenses.gist import _truncate
        assert "\n" not in _truncate("a\nb\nc", 80)

    def test_zero_width(self):
        from loops.lenses.gist import _truncate
        assert _truncate("text", 0) == ""
