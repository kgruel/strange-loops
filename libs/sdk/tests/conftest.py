"""Test configuration and fixtures for libs/sdk tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def sample_vertex(tmp_path: Path) -> Path:
    """Create a minimal test vertex file."""
    vertex_path = tmp_path / "test.vertex"
    vertex_content = """
name "test"
store ".loops/data/test.db"

loops {
  note {
    fold {
      items "collect" 100
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")
    return vertex_path


@pytest.fixture
def jsonl_vertex(tmp_path: Path) -> Path:
    """Create a test vertex backed by a JSONL canonical store."""
    vertex_path = tmp_path / "journal.vertex"
    vertex_content = """
name "journal"
store ".loops/data/journal.jsonl"

loops {
  entry {
    fold {
      items "collect" 50
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")
    return vertex_path


@pytest.fixture
def strict_vertex(tmp_path: Path) -> Path:
    """Create a test vertex with strict admission policy enabled."""
    vertex_path = tmp_path / "strict.vertex"
    vertex_content = """
name "strict"
store ".loops/data/strict.db"
strict true

loops {
  note {
    fold {
      items "collect" 100
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")
    return vertex_path


@pytest.fixture
def multi_kind_vertex(tmp_path: Path) -> Path:
    """Create a test vertex with multiple declared kinds."""
    vertex_path = tmp_path / "multi_kind.vertex"
    vertex_content = """
name "multi_kind"
store ".loops/data/multi_kind.db"

loops {
  note {
    fold {
      items "collect" 100
    }
  }
  task {
    fold {
      items "collect" 100
    }
  }
}
"""
    vertex_path.write_text(vertex_content.strip() + "\n", encoding="utf-8")
    return vertex_path
