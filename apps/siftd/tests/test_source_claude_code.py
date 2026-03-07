"""Tests for claude_code source script — discovery, parsing, NDJSON emission."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

from siftd_loops.sources.claude_code import (
    conversation_id_from_path,
    discover,
    emit,
    main,
    parse_exchanges,
)


# ---------------------------------------------------------------------------
# Fixtures — minimal Claude Code JSONL session files
# ---------------------------------------------------------------------------


def _write_session(path: Path, records: list[dict]) -> Path:
    """Write a list of dicts as JSONL lines to a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")
    return path


def _user_record(
    text: str, *, session_id: str = "sess-1", cwd: str = "/tmp/project", ts: str = "2025-01-15T10:00:00Z"
) -> dict:
    return {
        "type": "user",
        "sessionId": session_id,
        "cwd": cwd,
        "timestamp": ts,
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def _assistant_record(
    text: str, *, model: str = "claude-sonnet-4-20250514", ts: str = "2025-01-15T10:00:05Z"
) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": text}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        },
    }


def _tool_use_record(
    tool_name: str, tool_id: str, inp: dict, *, ts: str = "2025-01-15T10:00:10Z"
) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4-20250514",
            "content": [{"type": "tool_use", "id": tool_id, "name": tool_name, "input": inp}],
            "usage": {"input_tokens": 50, "output_tokens": 25},
        },
    }


def _tool_result_record(tool_id: str, content: str, *, ts: str = "2025-01-15T10:00:15Z") -> dict:
    return {
        "type": "user",
        "timestamp": ts,
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": content}],
        },
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscover:
    def test_finds_jsonl_files(self, tmp_path):
        project_dir = tmp_path / ".claude" / "projects" / "myproject"
        _write_session(project_dir / "session1.jsonl", [_user_record("hi")])
        _write_session(project_dir / "session2.jsonl", [_user_record("hello")])

        paths = discover(locations=[str(tmp_path / ".claude" / "projects")])
        assert len(paths) == 2
        assert all(p.suffix == ".jsonl" for p in paths)

    def test_skips_missing_locations(self):
        paths = discover(locations=["/nonexistent/path"])
        assert paths == []

    def test_since_filters_old_files(self, tmp_path):
        project_dir = tmp_path / ".claude" / "projects" / "myproject"
        old = _write_session(project_dir / "old.jsonl", [_user_record("old")])
        # Set old file mtime to the past
        import os
        os.utime(old, (1000, 1000))

        new = _write_session(project_dir / "new.jsonl", [_user_record("new")])

        # since is after old file's mtime
        paths = discover(locations=[str(tmp_path / ".claude" / "projects")], since=2000)
        assert len(paths) == 1
        assert paths[0].name == "new.jsonl"

    def test_returns_sorted_by_mtime(self, tmp_path):
        project_dir = tmp_path / ".claude" / "projects" / "myproject"
        import os
        a = _write_session(project_dir / "a.jsonl", [_user_record("a")])
        os.utime(a, (3000, 3000))
        b = _write_session(project_dir / "b.jsonl", [_user_record("b")])
        os.utime(b, (1000, 1000))
        c = _write_session(project_dir / "c.jsonl", [_user_record("c")])
        os.utime(c, (2000, 2000))

        paths = discover(locations=[str(tmp_path / ".claude" / "projects")])
        names = [p.name for p in paths]
        assert names == ["b.jsonl", "c.jsonl", "a.jsonl"]


# ---------------------------------------------------------------------------
# Conversation ID
# ---------------------------------------------------------------------------


class TestConversationId:
    def test_uses_session_id_from_first_user_record(self, tmp_path):
        path = _write_session(tmp_path / "test.jsonl", [
            _user_record("hi", session_id="abc-123"),
        ])
        assert conversation_id_from_path(path) == "abc-123"

    def test_falls_back_to_filename_stem(self, tmp_path):
        # No sessionId field
        path = _write_session(tmp_path / "fallback.jsonl", [
            {"type": "user", "message": {"role": "user", "content": "hi"}},
        ])
        assert conversation_id_from_path(path) == "fallback"

    def test_skips_non_user_records(self, tmp_path):
        path = _write_session(tmp_path / "test.jsonl", [
            _assistant_record("hello"),
            _user_record("hi", session_id="found-it"),
        ])
        assert conversation_id_from_path(path) == "found-it"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParseExchanges:
    def test_simple_exchange(self, tmp_path):
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("What is fold?", ts="2025-01-15T10:00:00Z"),
            _assistant_record("Fold replays facts over state.", ts="2025-01-15T10:00:05Z"),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1

        ex = exchanges[0]
        assert ex["prompt"] == "What is fold?"
        assert ex["response"] == "Fold replays facts over state."
        assert ex["model"] == "claude-sonnet-4-20250514"
        assert ex["workspace"] == "/tmp/project"
        assert ex["conversation_id"] == "sess-1"
        assert isinstance(ex["_ts"], float)
        assert ex["_ts"] > 0

    def test_multiple_exchanges(self, tmp_path):
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Question 1", ts="2025-01-15T10:00:00Z"),
            _assistant_record("Answer 1", ts="2025-01-15T10:00:05Z"),
            _user_record("Question 2", ts="2025-01-15T10:01:00Z"),
            _assistant_record("Answer 2", ts="2025-01-15T10:01:05Z"),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 2
        assert exchanges[0]["prompt"] == "Question 1"
        assert exchanges[1]["prompt"] == "Question 2"

    def test_tool_result_not_counted_as_exchange(self, tmp_path):
        """Tool result messages (user records with only tool_result blocks) are skipped."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Read file X"),
            _tool_use_record("Read", "tool-1", {"file_path": "/tmp/x.py"}),
            _tool_result_record("tool-1", "contents of x.py"),
            _assistant_record("The file contains..."),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert exchanges[0]["prompt"] == "Read file X"

    def test_tool_use_in_response_summarized(self, tmp_path):
        """Tool use blocks in assistant responses are summarized as [tool:Name]."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Read the config"),
            {
                "type": "assistant",
                "timestamp": "2025-01-15T10:00:05Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": [
                        {"type": "text", "text": "Let me read that."},
                        {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/etc/config"}},
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 25},
                },
            },
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert "Let me read that." in exchanges[0]["response"]
        assert "[tool:Read]" in exchanges[0]["response"]

    def test_multi_assistant_messages_concatenated(self, tmp_path):
        """Multiple assistant messages for one prompt are concatenated."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Explain folds"),
            _assistant_record("Part 1 of explanation."),
            _assistant_record("Part 2 of explanation."),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert "Part 1" in exchanges[0]["response"]
        assert "Part 2" in exchanges[0]["response"]

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        assert parse_exchanges(path) == []

    def test_no_user_records(self, tmp_path):
        """Files with only assistant records produce no exchanges."""
        path = _write_session(tmp_path / "session.jsonl", [
            _assistant_record("Hello"),
        ])
        assert parse_exchanges(path) == []

    def test_string_content(self, tmp_path):
        """Content as a plain string (not list of blocks) is handled."""
        path = _write_session(tmp_path / "session.jsonl", [
            {
                "type": "user",
                "sessionId": "s1",
                "cwd": "/tmp",
                "timestamp": "2025-01-15T10:00:00Z",
                "message": {"role": "user", "content": "Plain string prompt"},
            },
            {
                "type": "assistant",
                "timestamp": "2025-01-15T10:00:05Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "content": "Plain string response",
                },
            },
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert exchanges[0]["prompt"] == "Plain string prompt"
        assert exchanges[0]["response"] == "Plain string response"

    def test_workspace_from_cwd(self, tmp_path):
        """Workspace is taken from the cwd field of user records."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("hi", cwd="/home/user/myproject"),
            _assistant_record("hello"),
        ])
        exchanges = parse_exchanges(path)
        assert exchanges[0]["workspace"] == "/home/user/myproject"

    def test_prompt_without_response(self, tmp_path):
        """A prompt with no following assistant response still produces an exchange."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Unanswered question"),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert exchanges[0]["prompt"] == "Unanswered question"
        assert exchanges[0]["response"] == ""

    def test_malformed_lines_skipped(self, tmp_path):
        """Malformed JSON lines are skipped without crashing."""
        path = tmp_path / "session.jsonl"
        with path.open("w") as f:
            f.write("not json\n")
            f.write(json.dumps(_user_record("valid prompt")) + "\n")
            f.write(json.dumps(_assistant_record("valid response")) + "\n")
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1
        assert exchanges[0]["prompt"] == "valid prompt"


# ---------------------------------------------------------------------------
# NDJSON emission
# ---------------------------------------------------------------------------


class TestEmit:
    def test_emits_ndjson(self, tmp_path):
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("What is a vertex?"),
            _assistant_record("A vertex is..."),
        ])
        buf = io.StringIO()
        count = emit([path], out=buf)
        assert count == 1

        line = buf.getvalue().strip()
        obj = json.loads(line)
        assert obj["conversation_id"] == "sess-1"
        assert obj["prompt"] == "What is a vertex?"
        assert obj["response"] == "A vertex is..."
        assert "model" in obj
        assert "workspace" in obj
        assert "_ts" in obj

    def test_multiple_files(self, tmp_path):
        dir1 = tmp_path / "project1"
        dir2 = tmp_path / "project2"
        _write_session(dir1 / "s1.jsonl", [
            _user_record("Q1", session_id="s1"),
            _assistant_record("A1"),
        ])
        _write_session(dir2 / "s2.jsonl", [
            _user_record("Q2", session_id="s2"),
            _assistant_record("A2"),
            _user_record("Q3", session_id="s2"),
            _assistant_record("A3"),
        ])

        paths = sorted(tmp_path.rglob("*.jsonl"))
        buf = io.StringIO()
        count = emit(paths, out=buf)
        assert count == 3

        lines = buf.getvalue().strip().split("\n")
        assert len(lines) == 3
        # Each line is valid JSON
        for line in lines:
            obj = json.loads(line)
            assert "conversation_id" in obj
            assert "prompt" in obj

    def test_no_kind_in_output(self, tmp_path):
        """NDJSON output should NOT include 'kind' — that comes from Source config."""
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("test"),
            _assistant_record("response"),
        ])
        buf = io.StringIO()
        emit([path], out=buf)
        obj = json.loads(buf.getvalue().strip())
        assert "kind" not in obj




# ---------------------------------------------------------------------------
# Manifest (cursor / idempotent re-sync)
# ---------------------------------------------------------------------------


class TestManifest:
    def test_load_manifest_missing_file(self, tmp_path):
        from siftd_loops.sources.claude_code import load_manifest
        result = load_manifest(tmp_path / "nonexistent" / ".manifest")
        assert result == {}

    def test_load_manifest_none(self):
        from siftd_loops.sources.claude_code import load_manifest
        assert load_manifest(None) == {}

    def test_save_and_load_manifest(self, tmp_path):
        from siftd_loops.sources.claude_code import load_manifest, save_manifest
        manifest_path = tmp_path / ".manifest"
        data = {"/tmp/session.jsonl": {"size": 1234, "exchanges": 5}}
        save_manifest(data, manifest_path)
        loaded = load_manifest(manifest_path)
        assert loaded == data

    def test_save_manifest_none_is_noop(self):
        from siftd_loops.sources.claude_code import save_manifest
        save_manifest({"key": "val"}, None)  # should not raise

    def test_file_changed_new_file(self, tmp_path):
        from siftd_loops.sources.claude_code import file_changed
        path = _write_session(tmp_path / "new.jsonl", [_user_record("hi")])
        assert file_changed(path, {}) is True

    def test_file_changed_same_size(self, tmp_path):
        from siftd_loops.sources.claude_code import file_changed
        path = _write_session(tmp_path / "same.jsonl", [_user_record("hi")])
        manifest = {str(path): {"size": path.stat().st_size, "exchanges": 1}}
        assert file_changed(path, manifest) is False

    def test_file_changed_different_size(self, tmp_path):
        from siftd_loops.sources.claude_code import file_changed
        path = _write_session(tmp_path / "grew.jsonl", [_user_record("hi")])
        manifest = {str(path): {"size": 1, "exchanges": 1}}  # wrong size
        assert file_changed(path, manifest) is True


class TestEmitWithManifest:
    def test_skips_unchanged_files(self, tmp_path):
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("What is a vertex?"),
            _assistant_record("A vertex is..."),
        ])
        manifest_path = tmp_path / ".manifest"

        # First emit — should process
        buf1 = io.StringIO()
        count1 = emit([path], out=buf1, manifest_path=manifest_path)
        assert count1 == 1

        # Second emit — should skip (unchanged)
        buf2 = io.StringIO()
        count2 = emit([path], out=buf2, manifest_path=manifest_path)
        assert count2 == 0
        assert buf2.getvalue() == ""

    def test_reprocesses_grown_file(self, tmp_path):
        path = tmp_path / "session.jsonl"
        _write_session(path, [
            _user_record("Q1"),
            _assistant_record("A1"),
        ])
        manifest_path = tmp_path / ".manifest"

        # First emit
        buf1 = io.StringIO()
        emit([path], out=buf1, manifest_path=manifest_path)

        # Grow the file
        with path.open("a") as f:
            f.write(json.dumps(_user_record("Q2")) + "\n")
            f.write(json.dumps(_assistant_record("A2")) + "\n")

        # Second emit — should reprocess (file grew)
        buf2 = io.StringIO()
        count2 = emit([path], out=buf2, manifest_path=manifest_path)
        assert count2 == 2  # re-emits all exchanges from the file

    def test_no_manifest_processes_all(self, tmp_path):
        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Q1"),
            _assistant_record("A1"),
        ])

        # Without manifest — always processes
        buf1 = io.StringIO()
        count1 = emit([path], out=buf1, manifest_path=None)
        assert count1 == 1

        buf2 = io.StringIO()
        count2 = emit([path], out=buf2, manifest_path=None)
        assert count2 == 1  # processes again, no cursor


# ---------------------------------------------------------------------------
# CLI (main)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_main_discovers_and_emits(self, tmp_path, capsys):
        project_dir = tmp_path / ".claude" / "projects" / "test"
        _write_session(project_dir / "session.jsonl", [
            _user_record("How does the engine work?"),
            _assistant_record("The engine processes facts..."),
        ])

        result = main(["--locations", str(tmp_path / ".claude" / "projects")])
        assert result == 0

        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["prompt"] == "How does the engine work?"

    def test_main_since_flag(self, tmp_path, capsys):
        import os
        project_dir = tmp_path / ".claude" / "projects" / "test"
        old = _write_session(project_dir / "old.jsonl", [_user_record("old")])
        os.utime(old, (1000, 1000))
        _write_session(project_dir / "new.jsonl", [
            _user_record("new"),
            _assistant_record("new response"),
        ])

        # since is after old file
        result = main([
            "--locations", str(tmp_path / ".claude" / "projects"),
            "--since", "2000",
        ])
        assert result == 0

        out = capsys.readouterr().out
        lines = [l for l in out.strip().split("\n") if l]
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["prompt"] == "new"


# ---------------------------------------------------------------------------
# Integration: Source output → engine Fact
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_ndjson_compatible_with_fact_of(self, tmp_path):
        """Source output can be spread into Fact.of() without conflicts."""
        from atoms import Fact

        path = _write_session(tmp_path / "session.jsonl", [
            _user_record("Test integration"),
            _assistant_record("Works!"),
        ])
        exchanges = parse_exchanges(path)
        assert len(exchanges) == 1

        payload = exchanges[0]
        # This must not raise — Fact.of spreads payload as **kwargs
        fact = Fact.of("exchange", "siftd", **payload)
        assert fact.kind == "exchange"
        assert fact.observer == "siftd"
        assert fact.payload["prompt"] == "Test integration"
        assert fact.payload["response"] == "Works!"
        assert fact.payload["conversation_id"] == "sess-1"

    def test_exchange_stored_and_searchable(self, tmp_path):
        """Exchange facts can be stored in SqliteStore and found via vertex_search."""
        from atoms import Fact
        from engine import SqliteStore, vertex_search

        # Create a minimal siftd vertex
        vertex_path = tmp_path / "siftd.vertex"
        vertex_path.write_text(
            'name "siftd"\n'
            'store "./data/siftd.db"\n\n'
            "loops {\n"
            "  exchange {\n"
            '    fold { items "by" "conversation_id" }\n'
            '    search "prompt" "response"\n'
            "  }\n"
            "}\n"
        )
        (tmp_path / "data").mkdir()

        # Parse and store
        session_path = _write_session(tmp_path / "session.jsonl", [
            _user_record("How do vertex templates work?"),
            _assistant_record("Templates create local instances with store + data dir."),
        ])
        exchanges = parse_exchanges(session_path)

        store_path = tmp_path / "data" / "siftd.db"
        with SqliteStore(
            path=store_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
        ) as store:
            for ex in exchanges:
                store.append(Fact.of("exchange", "siftd", **ex))

        # Search should find the exchange (vertex_search returns list[dict] of serialized Facts)
        results = vertex_search(vertex_path, "vertex templates")
        assert len(results) >= 1
        found = results[0]
        payload = found.get("payload", found)
        assert "vertex templates" in payload.get("prompt", "").lower()
