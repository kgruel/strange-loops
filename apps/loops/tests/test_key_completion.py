"""Tests for --key completion (shell completion T3 S3, key half).

Two surfaces, mirroring ``test_vertex_completion.py``'s shape:

- ``commands.resolve.enumerate_key_prefixes`` — the enumeration side: resolves
  the kind's fold-key field from the declaration, then probes the store
  read-only (``StoreReader.key_prefixes`` — see
  ``libs/engine/tests/test_store_reader.py::TestKeyPrefixes`` for the
  LIMIT-bounded probe itself).
- ``cli.completers.complete_key`` — the domain completer hung on ``--key``:
  needs both a resolvable vertex AND a ``--kind`` already on the line,
  empty-on-error, render-free import.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

from loops.commands.resolve import enumerate_key_prefixes

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS facts (
    id TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL,
    ts REAL NOT NULL,
    observer TEXT NOT NULL,
    origin TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_kind ON facts(kind);
"""


def _write_vertex(vertex_path: Path, store_path: Path, *, loops: str) -> None:
    vertex_path.parent.mkdir(parents=True, exist_ok=True)
    vertex_path.write_text(
        'name "test"\n'
        f'store "{store_path}"\n\n'
        "loops {\n"
        f"{loops}"
        "}\n",
        encoding="utf-8",
    )


def _write_store(store_path: Path, rows: list[tuple[str, str]]) -> None:
    """``rows`` are ``(kind, topic)`` pairs, one fact each, increasing ts."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(store_path))
    conn.executescript(_SCHEMA)
    for i, (kind, topic) in enumerate(rows):
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, payload) VALUES (?, ?, ?, ?, ?)",
            (f"f{i}", kind, float(i), "kyle", f'{{"topic": "{topic}"}}'),
        )
    conn.commit()
    conn.close()


class TestEnumerateKeyPrefixes:
    def test_namespace_prefixes_for_kind(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "test.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        _write_store(store, [
            ("decision", "practice/foo"),
            ("decision", "practice/bar"),
            ("decision", "design/baz"),
        ])
        assert enumerate_key_prefixes(vertex, "decision") == ["design/", "practice/"]

    def test_scoped_drill_when_prefix_has_slash(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "test.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        _write_store(store, [
            ("decision", "practice/foo"),
            ("decision", "practice/bar"),
            ("decision", "design/baz"),
        ])
        assert enumerate_key_prefixes(vertex, "decision", "practice/") == [
            "practice/bar", "practice/foo",
        ]

    def test_empty_when_kind_has_no_fold_key(self, tmp_path):
        # A collect/count-style kind has no key field to prefix.
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "test.db"
        _write_vertex(vertex, store, loops='  log { fold { count "inc" } }\n')
        _write_store(store, [("log", "irrelevant")])
        assert enumerate_key_prefixes(vertex, "log") == []

    def test_empty_when_kind_not_declared(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "test.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        _write_store(store, [("decision", "practice/foo")])
        assert enumerate_key_prefixes(vertex, "nonexistent") == []

    def test_empty_when_no_store_configured(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        vertex.write_text(
            'name "test"\n\nloops {\n  decision { fold { items "by" "topic" } }\n}\n',
            encoding="utf-8",
        )
        assert enumerate_key_prefixes(vertex, "decision") == []

    def test_empty_when_store_file_missing(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "missing.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        assert enumerate_key_prefixes(vertex, "decision") == []

    def test_empty_when_vertex_missing(self, tmp_path):
        assert enumerate_key_prefixes(tmp_path / "nope.vertex", "decision") == []

    def test_empty_on_broken_store(self, tmp_path):
        vertex = tmp_path / "test.vertex"
        store = tmp_path / "data" / "test.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("not a sqlite database", encoding="utf-8")
        assert enumerate_key_prefixes(vertex, "decision") == []


# ---------------------------------------------------------------------------
# The completer
# ---------------------------------------------------------------------------


def _ctx(tokens=None, kind=None, prefix=""):
    from painted.cli import CompletionContext
    from painted.cli.types import ArgsView

    data = {"tokens": tokens or []}
    if kind is not None:
        data["kind"] = kind
    return CompletionContext(args=ArgsView(data), prefix=prefix)


class TestCompleteKey:
    def test_returns_prefixes_for_vertex_and_kind(self, tmp_path, monkeypatch):
        vertex = tmp_path / "vx.vertex"
        store = tmp_path / "data" / "vx.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        _write_store(store, [("decision", "practice/foo"), ("decision", "design/bar")])

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        from painted.cli import Candidate
        from loops.cli.completers import complete_key

        cands = complete_key(_ctx(tokens=["vx"], kind="decision"))
        assert all(isinstance(c, Candidate) for c in cands)
        assert {c.value for c in cands} == {"practice/", "design/"}

    def test_empty_when_no_vertex_on_line(self):
        from loops.cli.completers import complete_key

        assert complete_key(_ctx(kind="decision")) == []

    def test_empty_when_no_kind_on_line(self, tmp_path, monkeypatch):
        vertex = tmp_path / "vx.vertex"
        store = tmp_path / "data" / "vx.db"
        _write_vertex(vertex, store, loops='  decision { fold { items "by" "topic" } }\n')
        _write_store(store, [("decision", "practice/foo")])

        monkeypatch.setattr(
            "loops.commands.resolve._resolve_vertex_for_dispatch",
            lambda name: vertex if name == "vx" else None,
        )
        from loops.cli.completers import complete_key

        # A vertex resolves but --kind hasn't been typed yet — defer to [].
        assert complete_key(_ctx(tokens=["vx"])) == []

    def test_empty_on_error(self, monkeypatch):
        from loops.cli import completers

        def boom(*a, **k):
            raise RuntimeError("lookup failed")

        monkeypatch.setattr("loops.cli.completers._vertex_path_on_line", boom)
        assert completers.complete_key(_ctx(kind="decision")) == []


class TestRenderFreeImport:
    def test_completers_import_pulls_no_renderer_or_lens_body(self):
        """Importing cli.completers loads neither the renderer nor a lens body.

        Same render-free guarantee the S1/S2 test files assert — checked
        again here because ``complete_key`` is a new import path, and it's
        the first completer whose enumeration side opens a store (only
        inside the callable body, never at import time).
        """
        script = (
            "import sys\n"
            "import loops.cli.completers\n"
            "renderer = [m for m in sys.modules "
            "if 'painted.core.block' in m or 'painted.core.doc' in m]\n"
            "lenses = [m for m in sys.modules if m.startswith('loops.lenses')]\n"
            "engine_store = [m for m in sys.modules if m == 'engine.store_reader']\n"
            "assert not renderer, f'renderer imported: {renderer}'\n"
            "assert not lenses, f'lens body imported: {lenses}'\n"
            "assert not engine_store, f'store reader imported at module load: {engine_store}'\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"render-free import violated:\nstdout={result.stdout}\n"
            f"stderr={result.stderr}"
        )
        assert result.stdout.strip() == "ok"
