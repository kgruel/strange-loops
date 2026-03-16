"""Tests for content_gist — payload summarization for store lenses."""

from loops.lenses.gist import content_gist


class TestContentGist:
    def test_empty_payload(self):
        assert content_gist("any", {}) == ""

    def test_non_dict_payload(self):
        assert content_gist("any", "raw string") == "raw string"

    def test_message_field(self):
        assert "hello" in content_gist("observation", {"message": "hello world"})

    def test_decision_topic(self):
        result = content_gist("decision", {"topic": "design/api", "message": "Use REST"})
        assert "design/api" in result or "REST" in result

    def test_thread(self):
        result = content_gist("thread", {"name": "fix-bug", "status": "open", "message": "Working"})
        assert "fix-bug" in result

    def test_task(self):
        result = content_gist("task", {"name": "deploy", "status": "pending"})
        assert "deploy" in result

    def test_generic_fallback(self):
        """Unknown kind falls back to scanning common field names."""
        result = content_gist("custom_kind", {"summary": "Important update"})
        assert "Important" in result

    def test_no_known_fields(self):
        """Payload with no common fields falls back to first string value."""
        result = content_gist("custom", {"x": "value1", "y": "value2"})
        assert result  # Should return something

    def test_truncation(self):
        long = "x" * 200
        result = content_gist("any", {"message": long}, max_width=50)
        assert len(result) <= 53  # 50 + "..."

    def test_none_payload(self):
        assert content_gist("any", None) == ""

    def test_dissolution(self):
        result = content_gist("dissolution", {"subject": "old-module", "into": "new-module"})
        assert result  # Should extract meaningful content

    def test_notes(self):
        result = content_gist("note", {"text": "Remember to update docs"})
        assert "docs" in result
