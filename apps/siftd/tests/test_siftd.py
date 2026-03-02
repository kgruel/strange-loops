"""Tests for siftd — vertex template, lens, feedback, and app dispatch."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from atoms import Fact
from engine import SqliteStore
from painted import Zoom
from painted.writer import print_block

from loops.main import main


def _block_text(block) -> str:
    """Render a Block to plain text."""
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()


def _seed_siftd(workspace: Path) -> Path:
    """Create a siftd vertex + data dir in workspace, return store path."""
    vertex = workspace / "siftd.vertex"
    vertex.write_text(
        'name "siftd"\n'
        'store "./data/siftd.db"\n\n'
        "loops {\n"
        "  exchange {\n"
        '    fold { items "by" "conversation_id" }\n'
        '    search "prompt" "response"\n'
        "  }\n"
        "  tag {\n"
        '    fold { items "by" "name" }\n'
        "  }\n"
        "}\n"
    )
    (workspace / "data").mkdir()
    return workspace / "data" / "siftd.db"


def _emit_exchange(store_path: Path, conversation_id: str, prompt: str, response: str,
                   model: str = "claude", workspace: str = "/tmp/test", ts: float = 0) -> None:
    """Seed an exchange fact directly into the store."""
    import time
    fact_ts = ts or time.time()
    with SqliteStore(
        path=store_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
    ) as store:
        fact = Fact(
            kind="exchange",
            ts=fact_ts,
            payload={
                "conversation_id": conversation_id,
                "prompt": prompt,
                "response": response,
                "model": model,
                "workspace": workspace,
                "branch": "main",
                "tokens": 100,
                "tool_calls": 2,
            },
            observer=model,
            origin="",
        )
        store.append(fact)


def _emit_tag(store_path: Path, name: str, conversation_id: str, note: str = "") -> None:
    """Seed a tag fact directly into the store."""
    import time
    with SqliteStore(
        path=store_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
    ) as store:
        fact = Fact(
            kind="tag",
            ts=time.time(),
            payload={"name": name, "conversation_id": conversation_id, "note": note},
            observer="user",
            origin="",
        )
        store.append(fact)


class TestLens:
    """Test siftd_lens PayloadLens at different zoom levels."""

    def test_exchange_minimal(self):
        from siftd_loops.lens import siftd_lens
        result = siftd_lens("exchange", {"prompt": "How do vertex templates work?"}, Zoom.MINIMAL)
        assert result == "How do vertex templates work?"

    def test_exchange_summary_returns_block(self):
        from siftd_loops.lens import siftd_lens
        from painted import Block
        result = siftd_lens(
            "exchange",
            {"prompt": "What is fold?", "model": "claude"},
            Zoom.SUMMARY,
        )
        assert isinstance(result, Block)

    def test_tag_minimal(self):
        from siftd_loops.lens import siftd_lens
        result = siftd_lens("tag", {"name": "architecture"}, Zoom.MINIMAL)
        assert result == "#architecture"

    def test_tag_summary_returns_block(self):
        from siftd_loops.lens import siftd_lens
        from painted import Block
        result = siftd_lens(
            "tag",
            {"name": "architecture", "conversation_id": "abc12345-long-id", "note": "key decision"},
            Zoom.SUMMARY,
        )
        assert isinstance(result, Block)

    def test_unknown_kind_returns_empty(self):
        from siftd_loops.lens import siftd_lens
        result = siftd_lens("unknown", {"foo": "bar"}, Zoom.SUMMARY)
        assert result == ""


class TestStatusView:
    """Test siftd status rendering."""

    def test_empty_status(self):
        from siftd_loops.lens import status_view
        block = status_view({"conversations": 0, "tags": 0, "observers": {}, "recent": []}, Zoom.SUMMARY, 80)
        assert "No siftd data" in _block_text(block)

    def test_minimal_status(self):
        from siftd_loops.lens import status_view
        block = status_view(
            {"conversations": 3, "tags": 1, "observers": {"claude": 3}, "recent": []},
            Zoom.MINIMAL, 80,
        )
        rendered = _block_text(block)
        assert "3 conversations" in rendered

    def test_summary_status_shows_observers(self):
        from siftd_loops.lens import status_view
        block = status_view(
            {"conversations": 5, "tags": 2, "observers": {"claude": 3, "gemini": 2}, "recent": []},
            Zoom.SUMMARY, 80,
        )
        rendered = _block_text(block)
        assert "claude" in rendered
        assert "gemini" in rendered


class TestFetchStatus:
    """Test fetch_status transforms fold state correctly."""

    def test_empty_fold(self):
        from siftd_loops import fetch_status
        result = fetch_status({"exchange": {"items": {}}, "tag": {"items": {}}})
        assert result["conversations"] == 0
        assert result["tags"] == 0
        assert result["observers"] == {}

    def test_counts_conversations(self):
        from siftd_loops import fetch_status
        result = fetch_status({
            "exchange": {"items": {
                "conv1": {"model": "claude", "_ts": 1000, "prompt": "hi"},
                "conv2": {"model": "gemini", "_ts": 2000, "prompt": "hello"},
            }},
            "tag": {"items": {"arch": {"name": "arch"}}},
        })
        assert result["conversations"] == 2
        assert result["tags"] == 1
        assert result["observers"]["claude"] == 1
        assert result["observers"]["gemini"] == 1

    def test_recent_sorted_by_ts(self):
        from siftd_loops import fetch_status
        result = fetch_status({
            "exchange": {"items": {
                "old": {"model": "claude", "_ts": 1000, "prompt": "old"},
                "new": {"model": "claude", "_ts": 2000, "prompt": "new"},
            }},
            "tag": {"items": {}},
        })
        assert result["recent"][0]["conversation_id"] == "new"
        assert result["recent"][1]["conversation_id"] == "old"


class TestAppDispatch:
    """Test `loops siftd <command>` dispatch through main."""

    def test_siftd_status(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        store_path = _seed_siftd(tmp_path)
        _emit_exchange(store_path, "conv1", "How do vertex templates work?", "Templates create...", ts=1000.0)
        _emit_exchange(store_path, "conv2", "What is fold?", "Fold replays...", model="gemini", ts=2000.0)

        result = main(["siftd", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Conversations (2):" in out

    def test_siftd_log(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        store_path = _seed_siftd(tmp_path)
        _emit_exchange(store_path, "conv1", "How do vertex templates work?", "Templates create...")

        result = main(["siftd", "log", "--since", "1h"])
        assert result == 0

        out = capsys.readouterr().out
        assert "vertex templates" in out.lower()

    def test_siftd_search(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        store_path = _seed_siftd(tmp_path)
        _emit_exchange(store_path, "conv1", "How do vertex templates work?", "Templates create local instances")

        result = main(["siftd", "search", "vertex templates"])
        assert result == 0

        out = capsys.readouterr().out
        assert "vertex" in out.lower() or "1 match" in out.lower() or "exchange" in out

    def test_siftd_tag(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        store_path = _seed_siftd(tmp_path)
        _emit_exchange(store_path, "conv1", "Design discussion", "Let's use vertex...")

        result = main(["siftd", "tag", "architecture", "--conversation", "conv1"])
        assert result == 0

        out = capsys.readouterr().out
        assert "tagged" in out
        assert "#architecture" in out

        # Verify the tag fact was stored
        from engine import vertex_read
        vertex_path = tmp_path / "siftd.vertex"
        fold_state = vertex_read(vertex_path)
        tag_items = fold_state.get("tag", {}).get("items", {})
        assert "architecture" in tag_items

    def test_siftd_no_command(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        result = main(["siftd"])
        assert result == 1

    def test_siftd_no_vertex(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        result = main(["siftd", "status"])
        assert result == 1


class TestTemplate:
    """Test `loops init siftd` creates the right vertex."""

    def test_init_siftd(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "loops_home"))

        result = main(["init", "--template", "siftd"])
        assert result == 0

        vertex_path = tmp_path / "siftd.vertex"
        assert vertex_path.exists()

        content = vertex_path.read_text()
        assert 'name "siftd"' in content
        assert "exchange" in content
        assert "search" in content
        assert "tag" in content
