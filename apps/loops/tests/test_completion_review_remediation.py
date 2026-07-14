"""Regression net for the Sol review of feat/completion-t3 (2026-07-13).

One test group per finding, each anchored on the reviewer's own repro
(practice: reviewer-repro-becomes-regression-test). Finding numbers refer to
the review reply in ``.subtask/tasks/review--completion-t3/history.jsonl``.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace


from atoms import Fact
from engine.sqlite_store import SqliteStore
from lang import parse_vertex_file
from lang.document import genesis_payload

from loops.cli.completers import (
    _clean,
    complete_read_vertex,
    complete_vertex,
)
from painted.cli import Candidate


def _signer(observer: str, digest: str) -> str:
    return hashlib.sha256(f"k:{observer}:{digest}".encode()).hexdigest()


_KDL = '''name "t"
store "{store}"
loops {{
  decision {{ fold {{ items "by" "topic" }} }}
}}
observers {{
  kyle {{ key "AAAA" }}
}}
'''


def _scaffold_and_absorb(tmp_path: Path) -> Path:
    store = tmp_path / "t.db"
    vpath = tmp_path / "t.vertex"
    vpath.write_text(_KDL.format(store=store))
    docs = genesis_payload(parse_vertex_file(vpath))["documents"]
    s = SqliteStore(
        path=store, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict
    )
    s.absorb_genesis(docs, observer="kyle", fact_signer=_signer)
    s.close()
    return vpath


def _ctx(tokens: list[str], prefix: str = "", **flags):
    """Minimal CompletionContext stand-in: .args view + .prefix."""
    ns = {"tokens": tokens, **flags}
    return SimpleNamespace(args=SimpleNamespace(get=ns.get), prefix=prefix)


# --- #1: completion never advertises a flag the runtime parser rejects -----


class TestAdvertisedFlagsAreAccepted:
    def _advertised(self, add_args) -> set[str]:
        from painted.cli import build_parser

        parser = build_parser(prog="x", add_args=add_args)
        return {
            opt
            for a in parser._actions
            for opt in a.option_strings
            if opt not in ("-h", "--help")
        }

    def test_emit_runtime_accepts_every_advertised_flag(self):
        from loops.cli.emit_args import add_emit_args
        from loops.commands.emit import _build_emit_parser

        runtime = _build_emit_parser(prog="loops emit")
        accepted = {
            opt for a in runtime._actions for opt in a.option_strings
        }
        missing = self._advertised(add_emit_args) - accepted
        assert not missing, f"completion advertises unaccepted flags: {missing}"

    def test_read_runtime_accepts_every_advertised_flag(self):
        from loops.cli.read_args import add_read_args
        from loops.cli.views.fold import _build_parser

        runtime = _build_parser()
        accepted = {
            opt for a in runtime._actions for opt in a.option_strings
        }
        missing = self._advertised(add_read_args) - accepted
        assert not missing, f"completion advertises unaccepted flags: {missing}"

    def test_emit_reviewer_repro_plain(self):
        from loops.commands.emit import _build_emit_parser

        args = _build_emit_parser(prog="loops emit").parse_intermixed_args(
            ["project", "log", "--plain", "--no-input"]
        )
        assert args.plain and args.no_input


# --- #2: the real TAB entry path never imports the renderer ----------------


class TestRenderFreeEntryPath:
    def test_importing_cli_app_does_not_import_renderer(self):
        code = (
            "import sys; import loops.cli.app; "
            "bad = [m for m in sys.modules if m == 'painted.core.block']; "
            "sys.exit(1 if bad else 0)"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
        assert proc.returncode == 0, proc.stderr.decode()


# --- #3: kind completion follows the store, not the mutable file -----------


class TestKindCompletionHonesty:
    def test_post_genesis_file_mutation_is_inert(self, tmp_path):
        from loops.commands.resolve import _declared_kind_names

        vpath = _scaffold_and_absorb(tmp_path)
        vpath.write_text(vpath.read_text().replace("decision", "renamed"))
        assert _declared_kind_names(vpath) == ["decision"]

    def test_pre_genesis_file_is_the_declaration(self, tmp_path):
        from loops.commands.resolve import _declared_kind_names

        vpath = tmp_path / "t.vertex"
        vpath.write_text(_KDL.format(store=tmp_path / "t.db"))
        assert _declared_kind_names(vpath) == ["decision"]


# --- #4: completion classification mirrors the read runtime ----------------


class TestReadClassifierParity:
    def test_slash_bareword_is_entity_not_vertex(self, tmp_path, monkeypatch):
        """A slash token targets the LOCAL vertex, exactly like the runtime."""
        from loops.cli import completers

        local = _scaffold_and_absorb(tmp_path)
        monkeypatch.setattr(
            "loops.commands.resolve._find_local_vertex", lambda: local
        )
        got = completers._vertex_path_on_line(_ctx(["decision/foo"]))
        assert got == local

    def test_parity_with_fold_classifier(self, tmp_path, monkeypatch):
        """Whenever fold classifies vname=None, the completer must not
        resolve the token as a vertex either."""
        from loops.cli import completers
        from loops.cli.views.fold import _classify_tokens

        local = _scaffold_and_absorb(tmp_path)
        monkeypatch.setattr(
            "loops.commands.resolve._find_local_vertex", lambda: local
        )
        for tokens in (["decision/foo"], ["a/b", "x"], [], ["status=open"]):
            vname, _entity, _w, _o = _classify_tokens(tokens, has_vertex_path=False)
            if vname is None:
                assert completers._vertex_path_on_line(_ctx(tokens)) == local

    def test_read_vertex_candidates_exclude_slashed(self, monkeypatch):
        monkeypatch.setattr(
            "loops.commands.resolve.enumerate_vertices",
            lambda: [
                SimpleNamespace(name="project", description="instance"),
                SimpleNamespace(name="comms/discord", description="instance"),
            ],
        )
        names = {c.value for c in complete_read_vertex(_ctx([]))}
        assert names == {"project"}
        # emit's completer keeps the slashed name — its resolver accepts it
        names = {c.value for c in complete_vertex(_ctx([]))}
        assert "comms/discord" in names


# --- #5: lens enumeration only offers what resolve_lens can load -----------


class TestLensEnumerationResolvable:
    def test_phantom_view_module_is_not_enumerated(self, tmp_path, monkeypatch):
        from loops.lens_resolver import enumerate_lenses

        lens_dir = tmp_path / "lenses"
        lens_dir.mkdir()
        (lens_dir / "phantom.py").write_text(
            "def unrelated_view(data, zoom, width):\n    return None\n"
        )
        (lens_dir / "real.py").write_text(
            '"""Real lens."""\ndef real_view(data, zoom, width):\n    return None\n'
        )
        monkeypatch.chdir(tmp_path)
        names = {info.name for info in enumerate_lenses()}
        assert "real" in names
        assert "phantom" not in names


# --- #6: the key probe's work is actually bounded ---------------------------


class TestKeyProbeBounded:
    def test_query_plan_has_no_temp_btree(self, tmp_path):
        import sqlite3

        from engine import StoreReader

        vpath = _scaffold_and_absorb(tmp_path)
        store = tmp_path / "t.db"
        reader = StoreReader(store)
        try:
            # Same shape key_prefixes executes — hold the two together.
            plan = "".join(
                str(r)
                for r in reader._conn.execute(
                    "EXPLAIN QUERY PLAN "
                    "SELECT json_extract(payload, '$.topic') FROM facts "
                    "WHERE kind = 'decision' ORDER BY rowid DESC LIMIT 200"
                ).fetchall()
            )
            assert "TEMP B-TREE" not in plan.upper(), plan
        finally:
            reader.close()
        del sqlite3, vpath


# --- #7: a locked store cannot hang TAB -------------------------------------


class TestLockedStoreDoesNotHangTab:
    def test_exclusive_lock_returns_fast_and_empty(self, tmp_path):
        import sqlite3

        from loops.commands.resolve import enumerate_key_prefixes

        vpath = _scaffold_and_absorb(tmp_path)
        holder = sqlite3.connect(str(tmp_path / "t.db"))
        holder.execute("BEGIN EXCLUSIVE")
        try:
            start = time.monotonic()
            got = enumerate_key_prefixes(vpath, "decision")
            elapsed = time.monotonic() - start
        finally:
            holder.rollback()
            holder.close()
        assert got == []
        assert elapsed < 2.0, f"TAB blocked {elapsed:.2f}s on a locked store"


# --- #8: hostile values cannot corrupt the shell protocol -------------------


class TestProtocolSafety:
    def test_newline_bearing_value_is_dropped(self):
        got = _clean([Candidate("safe/value\n--strict"), Candidate("ok")])
        assert [c.value for c in got] == ["ok"]

    def test_newline_in_description_is_collapsed(self):
        got = _clean([Candidate("ok", "line one\nline two")])
        assert got[0].description == "line one line two"

    def test_carriage_return_and_nul_dropped(self):
        got = _clean([Candidate("a\rb"), Candidate("a\x00b")])
        assert got == []


# --- Round 2 -----------------------------------------------------------------


class TestRound2RenderFreeRealEntry:
    def test_importing_loops_main_does_not_import_renderer(self):
        """R2-1: python -m loops enters via loops.main, not loops.cli.app."""
        code = (
            "import sys; import loops.main; "
            "sys.exit(1 if 'painted.core.block' in sys.modules else 0)"
        )
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True)
        assert proc.returncode == 0, proc.stderr.decode()

    def test_lazy_reexports_still_resolve(self):
        import loops.main as m

        assert callable(m._run_store)
        assert callable(m._looks_like_vertex_path)


class TestRound2LockedStoreHonesty:
    def test_exclusive_lock_on_delete_journal_underlists_fast(self, tmp_path):
        """R2-2: locked canonical store → [] quickly, NEVER the stale file."""
        import sqlite3

        from loops.commands.resolve import _declared_kind_names

        vpath = _scaffold_and_absorb(tmp_path)
        db = tmp_path / "t.db"
        prep = sqlite3.connect(str(db))
        prep.execute("PRAGMA journal_mode=DELETE")
        prep.close()
        vpath.write_text(vpath.read_text().replace("decision", "renamed"))
        holder = sqlite3.connect(str(db))
        holder.execute("BEGIN EXCLUSIVE")
        try:
            start = time.monotonic()
            got = _declared_kind_names(vpath)
            elapsed = time.monotonic() - start
        finally:
            holder.rollback()
            holder.close()
        assert got == []  # honest under-list — not ['renamed'] from the file
        assert elapsed < 2.0, f"blocked {elapsed:.2f}s"


class TestRound2KeyFieldHonesty:
    def test_file_fold_key_flip_is_inert(self, tmp_path):
        """R2-3: --key completes the CANONICAL fold-key field's namespaces."""
        import json
        import sqlite3

        from loops.commands.resolve import enumerate_key_prefixes

        vpath = _scaffold_and_absorb(tmp_path)
        db = tmp_path / "t.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO facts (id, kind, ts, observer, payload) "
            "VALUES ('f1', 'decision', 1.0, 'kyle', ?)",
            (json.dumps({"topic": "real/a", "slug": "fake/b"}),),
        )
        conn.commit()
        conn.close()
        # File-only flip of the fold key: topic → slug.
        vpath.write_text(
            vpath.read_text().replace('items "by" "topic"', 'items "by" "slug"')
        )
        assert enumerate_key_prefixes(vpath, "decision") == ["real/"]


class TestRound2EmitFlagsVisibleAndWired:
    def test_emit_help_shows_framework_flags(self):
        from loops.commands.emit import _build_emit_parser

        text = _build_emit_parser(prog="loops emit").format_help()
        for flag in ("--plain", "--no-input", "--static", "--live"):
            assert flag in text, f"{flag} hidden from emit -h"

    def test_plain_receipt_has_no_ansi(self, capsys, monkeypatch):
        import loops.commands.emit as emit_mod

        monkeypatch.setattr(emit_mod, "_PLAIN_RECEIPT", True)
        emit_mod._emit_lines([("stored: x", "muted")])
        err = capsys.readouterr().err
        assert "stored: x" in err and "\x1b[" not in err


class TestRound2EqualsBearingVertexPath:
    def test_explicit_path_with_equals_wins_over_local(self, tmp_path, monkeypatch):
        """R2-5: ./x=y.vertex is a path, not a predicate — runtime parity."""
        from loops.cli import completers

        target_dir = tmp_path / "explicit"
        target_dir.mkdir()
        explicit = _scaffold_and_absorb(target_dir)
        weird = tmp_path / "x=y.vertex"
        weird.write_text(explicit.read_text())
        monkeypatch.chdir(tmp_path)
        got = completers._vertex_path_on_line(_ctx([f"./{weird.name}"]))
        assert got is not None and got.name == "x=y.vertex"


class TestRound2ControlCharacters:
    def test_unit_separator_and_escape_dropped(self):
        """R2-6: \\x1f collides with painted's file directive; \\x1b injects."""
        got = _clean([Candidate("\x1ffiles/"), Candidate("\x1b[31mred")])
        assert got == []

    def test_escape_in_description_collapsed(self):
        got = _clean([Candidate("ok", "a\x1b[31mb")])
        assert "\x1b" not in got[0].description


