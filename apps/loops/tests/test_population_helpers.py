"""Direct tests for population helper branches not covered by CLI flows."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from loops.commands.pop import _load, _maybe_bootstrap_from_list, fetch_ls
from loops.pop_store import (
    POP_ADD_KIND,
    POP_RM_KIND,
    pop_fold_rows,
    pop_materialize_list,
    pop_read_facts,
    pop_store_has_facts,
)


_FILE_BACKED = """\
name "reading"
store "./data/reading.db"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
    }
  }
}
"""

_INLINE_ONLY = """\
name "reading"
store "./data/reading.db"
sources {
  template "./sources/feed.loop" {
    with kind="feed" feed_url="https://example.com/rss"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
    }
  }
}
"""

_NO_STORE = """\
name "reading"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
    }
  }
}
"""

_MULTI = """\
name "economy"
store "./data/economy.db"
sources {
  template "./sources/fred.loop" {
    from file "./fred.list"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
    }
  }
  template "./sources/bls.loop" {
    from file "./bls.list"
    loop {
      fold { count "inc" }
      boundary when="{{kind}}.complete"
    }
  }
}
"""


def _setup_reading(home: Path, text: str = _FILE_BACKED) -> Path:
    reading = home / "reading"
    reading.mkdir(parents=True)
    (reading / "reading.vertex").write_text(text)
    (reading / "feeds.list").write_text("kind feed_url\nlobsters https://lobste.rs/rss\n")
    (reading / "sources").mkdir()
    (reading / "sources" / "feed.loop").write_text('source "curl"\nkind "{{kind}}"\n')
    return reading


class TestLoad:
    def test_missing_vertex(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        with pytest.raises(ValueError, match="not found"):
            _load("reading")

    def test_inline_template_rejected(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        _setup_reading(home, _INLINE_ONLY)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        with pytest.raises(ValueError, match="file-backed"):
            _load("reading")

    def test_vertex_without_store_rejected(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        _setup_reading(home, _NO_STORE)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        with pytest.raises(ValueError, match="no store configured"):
            _load("reading")

    def test_multi_template_marks_is_multi(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        economy = home / "economy"
        economy.mkdir(parents=True)
        (economy / "economy.vertex").write_text(_MULTI)
        (economy / "fred.list").write_text("kind series\nFEDFUNDS FEDFUNDS\n")
        (economy / "bls.list").write_text("kind series\nCPI CPI\n")
        (economy / "sources").mkdir()
        (economy / "sources" / "fred.loop").write_text('source "x"\nkind "{{kind}}"\n')
        (economy / "sources" / "bls.loop").write_text('source "x"\nkind "{{kind}}"\n')
        monkeypatch.setenv("LOOPS_HOME", str(home))
        _vertex, template, list_path, header, store_path, _vpath, is_multi = _load("economy/fred")
        assert template.template.stem == "fred"
        assert list_path.name == "fred.list"
        assert header == ["kind", "series"]
        assert store_path.name == "economy.db"
        assert is_multi is True


class TestMaybeBootstrap:
    def test_missing_list_file_noop(self, tmp_path):
        store = tmp_path / "x.db"
        _maybe_bootstrap_from_list(
            store_path=store,
            list_path=tmp_path / "missing.list",
            template_name=None,
            include_unscoped=True,
            observer="",
        )
        assert not store.exists()

    def test_empty_header_or_rows_noop(self, tmp_path):
        store = tmp_path / "x.db"
        list_path = tmp_path / "x.list"
        list_path.write_text("")
        _maybe_bootstrap_from_list(
            store_path=store,
            list_path=list_path,
            template_name=None,
            include_unscoped=True,
            observer="",
        )
        assert pop_read_facts(store) == []

    def test_bootstraps_with_template_field(self, tmp_path):
        store = tmp_path / "x.db"
        list_path = tmp_path / "fred.list"
        list_path.write_text("kind series\nFEDFUNDS FUNDS\n")
        _maybe_bootstrap_from_list(
            store_path=store,
            list_path=list_path,
            template_name="fred",
            include_unscoped=False,
            observer="me",
        )
        facts = pop_read_facts(store)
        assert len(facts) == 1
        assert facts[0]["kind"] == POP_ADD_KIND
        assert facts[0]["payload"]["template"] == "fred"


class TestFetchLs:
    def test_fetch_ls_legacy_file_without_header_returns_empty(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        reading = _setup_reading(home)
        (reading / "feeds.list").write_text("")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        assert fetch_ls("reading") == {"header": [], "rows": []}

    def test_fetch_ls_legacy_file_reads_rows(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        _setup_reading(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        data = fetch_ls("reading")
        assert data["header"] == ["kind", "feed_url"]
        assert data["rows"][0]["kind"] == "lobsters"


class TestPopStoreHelpers:
    def test_pop_store_has_facts_scoped_and_unscoped(self, tmp_path):
        from loops.commands.pop import _append_fact

        store = tmp_path / "x.db"
        _append_fact(store, POP_ADD_KIND, {"key": "a"}, observer="")
        assert pop_store_has_facts(store, template="fred", include_unscoped=True) is True
        assert pop_store_has_facts(store, template="fred", include_unscoped=False) is False

    def test_pop_fold_rows_empty_header(self):
        assert pop_fold_rows([], []) == []

    def test_pop_fold_rows_template_filtering(self):
        facts = [
            {"kind": POP_ADD_KIND, "payload": {"key": "a", "series": "A", "template": "fred"}},
            {"kind": POP_ADD_KIND, "payload": {"key": "b", "series": "B"}},
            {"kind": POP_ADD_KIND, "payload": {"key": "c", "series": "C", "template": "bls"}},
            {"kind": POP_RM_KIND, "payload": {"key": "b"}},
            {"kind": POP_ADD_KIND, "payload": {}},
        ]
        rows = pop_fold_rows(facts, ["kind", "series"], template="fred", include_unscoped=True)
        assert [r.key for r in rows] == ["a"]

    def test_pop_materialize_list_writes_sorted_rows(self, tmp_path):
        from loops.commands.pop import _append_fact

        store = tmp_path / "x.db"
        list_path = tmp_path / "x.list"
        _append_fact(store, POP_ADD_KIND, {"key": "b", "series": "B"}, observer="")
        _append_fact(store, POP_ADD_KIND, {"key": "a", "series": "A"}, observer="")
        rows = pop_materialize_list(store_path=store, list_path=list_path, header=["kind", "series"])
        assert [r.key for r in rows] == ["a", "b"]
        content = list_path.read_text()
        assert "a A" in content and "b B" in content

    def test_pop_store_has_facts_template_match(self, tmp_path):
        """pop_store_has_facts returns True when template field matches (L58)."""
        from loops.commands.pop import _append_fact
        from loops.pop_store import POP_ADD_KIND

        store = tmp_path / "y.db"
        # Add a fact with a specific template field
        _append_fact(store, POP_ADD_KIND, {"key": "a", "template": "fred"}, observer="")
        assert pop_store_has_facts(store, template="fred", include_unscoped=False) is True
