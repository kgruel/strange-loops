"""Tests for loops emit command."""

from __future__ import annotations

import io
import json
from datetime import datetime as py_datetime, timezone
from pathlib import Path

import pytest

from atoms import Fact
from engine import SqliteStore

from loops.commands.emit import _apply_input_sources, _parse_emit_parts
from loops.errors import LoopsError
from loops.main import main


class TestParseEmitParts:
    """_parse_emit_parts — payload parsing with ref accumulation."""

    def test_basic_kv(self):
        payload = _parse_emit_parts(["topic=auth", "status=open"])
        assert payload == {"topic": "auth", "status": "open"}

    def test_trailing_message(self):
        payload = _parse_emit_parts(["name=x", "some", "message", "text"])
        assert payload == {"name": "x", "message": "some message text"}

    def test_explicit_message_wins_over_trailing_bareword(self):
        # B4: explicit message= beats trailing barewords (explicit-over-implicit);
        # the ignored words surface via the warnings sink, never a silent clobber.
        warnings: list[str] = []
        payload = _parse_emit_parts(
            ["topic=x", "message=explicit body", "stray", "word"], warnings=warnings
        )
        assert payload["message"] == "explicit body"
        assert warnings and "stray word" in warnings[0]

    def test_trailing_message_without_explicit_emits_no_warning(self):
        # Boundary: no competing message= → trailing barewords still become the
        # message and no warning fires (the precedence branch must not trip).
        warnings: list[str] = []
        payload = _parse_emit_parts(["topic=x", "trailing", "body"], warnings=warnings)
        assert payload["message"] == "trailing body"
        assert warnings == []

    def test_ref_comma_separated(self):
        payload = _parse_emit_parts(["topic=t", "ref=a,b,c"])
        assert payload == {"topic": "t", "ref": "a,b,c"}

    def test_multiple_ref_accumulates(self):
        """ref=X ref=Y ref=Z accumulates instead of silently dropping earlier ones."""
        payload = _parse_emit_parts(["topic=t", "ref=a", "ref=b", "ref=c"])
        assert payload == {"topic": "t", "ref": "a,b,c"}

    def test_mixed_ref_forms(self):
        """Both ref=A,B and ref=C accumulate into one comma-separated value."""
        payload = _parse_emit_parts(["topic=t", "ref=a,b", "ref=c"])
        assert payload == {"topic": "t", "ref": "a,b,c"}

    def test_ref_dedup_preserves_order(self):
        """Duplicate refs are collapsed; first-seen order preserved."""
        payload = _parse_emit_parts(["topic=t", "ref=a,b", "ref=b,c", "ref=a"])
        assert payload == {"topic": "t", "ref": "a,b,c"}

    def test_ref_blank_segments_ignored(self):
        payload = _parse_emit_parts(["topic=t", "ref=a,,b", "ref="])
        assert payload == {"topic": "t", "ref": "a,b"}

    def test_ref_absent_no_key(self):
        """No ref= at all → no ref key in payload (not an empty string)."""
        payload = _parse_emit_parts(["topic=t"])
        assert "ref" not in payload


class _FakeStdin:
    """Fake sys.stdin for testing — read() returns canned text, isatty configurable."""

    def __init__(self, content: str, *, tty: bool = False):
        self._buf = io.StringIO(content)
        self._tty = tty

    def read(self) -> str:
        return self._buf.read()

    def isatty(self) -> bool:
        return self._tty


class TestApplyInputSources:
    """_apply_input_sources — --stdin and --file flag application."""

    def test_no_flags_unchanged(self):
        """No --stdin, no --file → parts returned unchanged."""
        out = _apply_input_sources(["topic=t", "message=hi"], None, [])
        assert out == ["topic=t", "message=hi"]

    def test_stdin_injects_field(self, monkeypatch):
        """--stdin FIELD reads stdin and appends FIELD=<content>."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("hello world"))
        out = _apply_input_sources(["topic=t"], "message", [])
        assert out == ["topic=t", "message=hello world"]

    def test_stdin_strips_single_trailing_newline(self, monkeypatch):
        """Echo adds a trailing \\n — strip exactly one. Internal newlines kept."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("line one\nline two\n"))
        out = _apply_input_sources([], "message", [])
        assert out == ["message=line one\nline two"]

    def test_stdin_preserves_double_trailing_newline(self, monkeypatch):
        """Two trailing \\n → strip only one (the last); the other is intentional."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("body\n\n"))
        out = _apply_input_sources([], "message", [])
        assert out == ["message=body\n"]

    def test_stdin_tty_errors(self, monkeypatch):
        """--stdin with TTY-attached stdin errors (would hang silently)."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("", tty=True))
        with pytest.raises(LoopsError, match="stdin is a TTY"):
            _apply_input_sources([], "message", [])

    def test_stdin_invalid_field_errors(self, monkeypatch):
        """--stdin with non-identifier field name errors."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("x"))
        with pytest.raises(LoopsError, match="not a valid identifier"):
            _apply_input_sources([], "bad-field", [])

    def test_file_injects_field(self, tmp_path):
        """--file FIELD=PATH reads file and appends FIELD=<content>."""
        p = tmp_path / "note.md"
        p.write_text("file body")
        out = _apply_input_sources(["topic=t"], None, [f"message={p}"])
        assert out == ["topic=t", "message=file body"]

    def test_file_strips_single_trailing_newline(self, tmp_path):
        """Files commonly end with \\n — strip one."""
        p = tmp_path / "note.md"
        p.write_text("line one\nline two\n")
        out = _apply_input_sources([], None, [f"message={p}"])
        assert out == ["message=line one\nline two"]

    def test_file_tilde_expansion(self, tmp_path, monkeypatch):
        """~/foo expands to user home."""
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "tilde-note.md").write_text("from home")
        out = _apply_input_sources([], None, ["message=~/tilde-note.md"])
        assert out == ["message=from home"]

    def test_file_nonexistent_errors(self, tmp_path):
        """--file with missing path errors with the path in the message."""
        missing = tmp_path / "nope.md"
        with pytest.raises(LoopsError, match="nope.md"):
            _apply_input_sources([], None, [f"message={missing}"])

    def test_file_missing_equals_errors(self):
        """--file without FIELD=PATH form errors."""
        with pytest.raises(LoopsError, match="FIELD=PATH form"):
            _apply_input_sources([], None, ["just-a-path.md"])

    def test_file_invalid_field_errors(self, tmp_path):
        """--file with non-identifier field name errors."""
        p = tmp_path / "x"
        p.write_text("x")
        with pytest.raises(LoopsError, match="not a valid identifier"):
            _apply_input_sources([], None, [f"bad-field={p}"])

    def test_file_duplicate_field_errors(self, tmp_path):
        """--file specified multiple times for the same field errors."""
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("A")
        b.write_text("B")
        with pytest.raises(LoopsError, match="multiple times for field 'message'"):
            _apply_input_sources([], None, [f"message={a}", f"message={b}"])

    def test_stdin_and_file_same_field_errors(self, tmp_path, monkeypatch):
        """--stdin and --file targeting the same field errors."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("x"))
        p = tmp_path / "n"
        p.write_text("y")
        with pytest.raises(LoopsError, match="both target field"):
            _apply_input_sources([], "message", [f"message={p}"])

    def test_inline_collision_with_stdin_errors(self, monkeypatch):
        """parts has message=foo AND --stdin message → error (ambiguous intent)."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("y"))
        with pytest.raises(LoopsError, match="ambiguous intent"):
            _apply_input_sources(["message=inline"], "message", [])

    def test_inline_collision_with_file_errors(self, tmp_path):
        """parts has topic=foo AND --file topic=path → error."""
        p = tmp_path / "n"
        p.write_text("x")
        with pytest.raises(LoopsError, match="ambiguous intent"):
            _apply_input_sources(["topic=inline"], None, [f"topic={p}"])

    def test_multiple_file_different_fields(self, tmp_path):
        """--file body=a --file notes=b → both fields appended."""
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.write_text("body-content")
        b.write_text("notes-content")
        out = _apply_input_sources([], None, [f"body={a}", f"notes={b}"])
        assert out == ["body=body-content", "notes=notes-content"]

    def test_stdin_plus_file_combine(self, tmp_path, monkeypatch):
        """--stdin and --file on different fields combine cleanly."""
        monkeypatch.setattr("sys.stdin", _FakeStdin("stdin-msg"))
        p = tmp_path / "notes"
        p.write_text("file-notes")
        out = _apply_input_sources(["topic=t"], "message", [f"notes={p}"])
        assert out == ["topic=t", "message=stdin-msg", "notes=file-notes"]

    def test_at_in_inline_value_stays_literal(self):
        """Universal-magic-syntax would break this — explicit flags do not.

        Regression bar: topic=foo@example.com must store the @ literally.
        Verifying empirically that no @-handling logic touches inline values.
        """
        out = _apply_input_sources(["topic=foo@example.com"], None, [])
        assert out == ["topic=foo@example.com"]


def _write_vertex(home: Path, name: str, *, store: str | None) -> Path:
    vdir = home / name
    vdir.mkdir(parents=True)
    vertex_path = vdir / f"{name}.vertex"
    store_line = f'store "{store}"\n' if store is not None else ""
    vertex_path.write_text(
        f'name "{name}"\n'
        f"{store_line}"
        "loops {\n"
        "  counter {\n"
        "    fold { count \"inc\" }\n"
        "  }\n"
        "}\n"
    )
    return vertex_path


def _read_all_facts(db_path: Path) -> list[Fact]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return store.since(0)


class TestEmit:
    def test_fact_construction_and_kv_parsing(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        fixed = py_datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                return fixed

        import loops.commands.emit as emit_mod

        monkeypatch.setattr(emit_mod, "datetime", FakeDateTime)

        result = main(
            [
                "session",
                "emit",
                "decision",
                "topic=sigil",
                "{{var}} over ${var}",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        d = json.loads(captured.out)
        assert d["kind"] == "decision"
        assert d["observer"] == ""
        assert d["origin"] == ""
        assert d["ts"] == fixed.timestamp()
        assert d["payload"]["topic"] == "sigil"
        assert d["payload"]["message"] == "{{var}} over ${var}"

    def test_value_with_spaces_if_quoted(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "session",
                "emit",
                "change",
                "summary=structural AST",
                "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["summary"] == "structural AST"

    def test_store_injection_round_trip(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "session",
                "emit",
                "task",
                "name=fix/review",
                "status=merged",
            ]
        )
        assert result == 0

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        facts = _read_all_facts(db_path)
        assert len(facts) == 1
        assert facts[0].kind == "task"
        assert dict(facts[0].payload) == {"name": "fix/review", "status": "merged"}

    def test_dry_run_prints_without_storing(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        assert not db_path.exists()

        result = main(
            [
                "session",
                "emit",
                "thread",
                "name=env-passthrough",
                "status=open",
                "literal override bug",
                "--dry-run",
            ]
        )
        assert result == 0
        out = capsys.readouterr().out
        assert json.loads(out)["payload"]["message"] == "literal override bug"
        assert not db_path.exists()

    def test_stdin_flag_end_to_end(self, tmp_path, monkeypatch, capsys):
        """--stdin message reads sys.stdin and stores it as the message field."""
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setattr(
            "sys.stdin",
            _FakeStdin("Kyle's point: declaration was overreach.\n"),
        )

        result = main(
            [
                "session", "emit", "decision",
                "topic=sigil",
                "--stdin", "message",
                "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["message"] == "Kyle's point: declaration was overreach."
        assert d["payload"]["topic"] == "sigil"

    def test_file_flag_end_to_end(self, tmp_path, monkeypatch, capsys):
        """--file message=path reads the file and stores it as the message field."""
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        note = tmp_path / "note.md"
        note.write_text("Multi-line\nfile content with 'apostrophes' and \"quotes\".\n")

        result = main(
            [
                "session", "emit", "decision",
                "topic=sigil",
                "--file", f"message={note}",
                "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["message"] == (
            "Multi-line\nfile content with 'apostrophes' and \"quotes\"."
        )

    def test_stdin_inline_collision_errors_via_main(self, tmp_path, monkeypatch, capsys):
        """Inline message=foo + --stdin message → exit 1 with collision error."""
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setattr("sys.stdin", _FakeStdin("piped"))

        result = main(
            [
                "session", "emit", "decision",
                "topic=t", "message=inline",
                "--stdin", "message",
                "--dry-run",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "ambiguous intent" in err

    def test_missing_store_clause_errors(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store=None)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "emit", "decision", "topic=sigil"])
        assert result == 1
        captured = capsys.readouterr()
        assert "vertex has no store configured" in captured.err

    def test_observer_flag(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session",
                "emit",
                "decision",
                "--observer",
                "human",
                "topic=sigil",
            ]
        )
        assert result == 0

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        facts = _read_all_facts(db_path)
        assert facts[0].observer == "human"

    def test_order_stable_flags_intermixed(self, tmp_path, monkeypatch, capsys):
        """parse_intermixed_args: a flag between kind and parts doesn't break the
        positional split, and trailing barewords still join as the message."""
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main([
            "session", "emit", "decision",
            "--dry-run", "topic=sigil", "trailing", "message", "words",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["topic"] == "sigil"
        assert d["payload"]["message"] == "trailing message words"

    def test_key_value_never_classified_as_vertex_or_kind(self, tmp_path, monkeypatch, capsys):
        """Verb-first emit: a leading KEY=VALUE is payload, never the vertex/kind.

        ``emit <vertex> decision topic=design/foo`` keeps topic as payload even
        though its value carries a slash (the old greedy-positional footgun)."""
        home = tmp_path / "home"
        vdir = home / "proj"
        vdir.mkdir(parents=True)
        (vdir / "proj.vertex").write_text(
            'name "proj"\n'
            'store "./data/proj.db"\n'
            'loops {\n  decision { fold { items "by" "topic" } }\n}\n'
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # Verb-first: "emit" verb, "proj" vertex, "decision" kind.
        result = main([
            "emit", "proj", "decision", "topic=design/foo", "body", "text",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["kind"] == "decision"
        assert d["payload"]["topic"] == "design/foo"
        assert d["payload"]["message"] == "body text"

    def test_missing_kind_errors_cleanly_both_paths(self, tmp_path, monkeypatch, capsys):
        """All-KEY=VALUE bucket → kind=None must error exit 2 on BOTH dry-run and
        real path, never a kind:null false-success preview or an opaque crash.

        Regression bar: the token-bucket grammar made kind structurally optional;
        the guard restores the pre-S6 clean refusal (argparse exit 2)."""
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # dry-run: NO kind:null fact on stdout, clean error on stderr, exit 2.
        rc = main(["session", "emit", "topic=x", "message=y", "--dry-run"])
        assert rc == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "requires a kind" in captured.err

        # real path: same clean refusal (not an opaque NoneType crash).
        rc = main(["session", "emit", "topic=x", "message=y"])
        assert rc == 2
        assert "requires a kind" in capsys.readouterr().err


class TestEntityRefResolution:
    """Entity address resolution at emit time."""

    def _write_vertex_with_kinds(self, home: Path, name: str) -> Path:
        """Create a vertex with thread (by name) and decision (by topic) kinds."""
        vdir = home / name
        vdir.mkdir(parents=True)
        vertex_path = vdir / f"{name}.vertex"
        vertex_path.write_text(
            f'name "{name}"\n'
            'store "./data/project.db"\n'
            "loops {\n"
            '  thread { fold { items "by" "name" } }\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )
        return vertex_path

    def test_entity_ref_resolved_to_ulid(self, tmp_path, monkeypatch):
        """A payload value matching kind/fold_key_value gets a _ref sibling with the ULID."""
        home = tmp_path / "home"
        vertex_path = self._write_vertex_with_kinds(home, "project")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # First: emit a thread so there's something to reference
        result = main(["project", "emit", "thread", "name=cli-dissolution", "status=open"])
        assert result == 0

        # Second: emit a task that references the thread
        result = main(["project", "emit", "task", "name=fact-drill-down", "status=parked",
                        "reason=superseded", "superseded_by=thread/cli-dissolution"])
        assert result == 0

        db_path = (vertex_path.parent / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        assert len(facts) == 2

        task_fact = facts[1]
        assert task_fact.kind == "task"
        payload = dict(task_fact.payload)
        # Original address preserved
        assert payload["superseded_by"] == "thread/cli-dissolution"
        # ULID reference added
        assert "superseded_by_ref" in payload
        # The ref should be the ULID of the thread fact
        thread_ulid = facts[0].payload.get("_id") if hasattr(facts[0].payload, "get") else None
        # Read the actual ULID from the store
        from engine import StoreReader

        reader = StoreReader(db_path)
        try:
            resolved = reader.resolve_entity_id("thread", "name", "cli-dissolution")
            assert payload["superseded_by_ref"] == resolved
        finally:
            reader.close()

    def test_no_ref_for_nonexistent_entity(self, tmp_path, monkeypatch):
        """If the referenced entity doesn't exist in the store, no _ref is added."""
        home = tmp_path / "home"
        self._write_vertex_with_kinds(home, "project")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # Emit a task referencing a thread that doesn't exist
        result = main(["project", "emit", "task", "name=orphan-task", "status=parked",
                        "superseded_by=thread/nonexistent"])
        assert result == 0

        db_path = (home / "project" / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        assert len(facts) == 1
        payload = dict(facts[0].payload)
        assert payload["superseded_by"] == "thread/nonexistent"
        assert "superseded_by_ref" not in payload

    def test_no_ref_for_undeclared_kind(self, tmp_path, monkeypatch):
        """Values with slash but non-matching kind are not treated as references."""
        home = tmp_path / "home"
        self._write_vertex_with_kinds(home, "project")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # "fix/review" — "fix" is not a declared kind, should pass through unchanged
        result = main(["project", "emit", "task", "name=fix/review", "status=merged"])
        assert result == 0

        db_path = (home / "project" / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        payload = dict(facts[0].payload)
        assert payload["name"] == "fix/review"
        assert "name_ref" not in payload

    def test_decision_topic_with_slash(self, tmp_path, monkeypatch):
        """Decision topics containing slashes resolve correctly (split on first / only)."""
        home = tmp_path / "home"
        self._write_vertex_with_kinds(home, "project")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # Emit a decision with a slashed topic
        result = main(["project", "emit", "decision", "topic=design/format-dissolves",
                        "message=Format dissolves into lens"])
        assert result == 0

        # Emit a thread that references that decision
        result = main(["project", "emit", "thread", "name=format-work", "status=resolved",
                        "decided_by=decision/design/format-dissolves"])
        assert result == 0

        db_path = (home / "project" / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        thread_fact = facts[1]
        payload = dict(thread_fact.payload)
        assert payload["decided_by"] == "decision/design/format-dissolves"
        assert "decided_by_ref" in payload

        from engine import StoreReader

        reader = StoreReader(db_path)
        try:
            resolved = reader.resolve_entity_id("decision", "topic", "design/format-dissolves")
            assert payload["decided_by_ref"] == resolved
        finally:
            reader.close()

    def test_dry_run_shows_resolved_refs(self, tmp_path, monkeypatch, capsys):
        """--dry-run output includes resolved entity references."""
        home = tmp_path / "home"
        self._write_vertex_with_kinds(home, "project")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # Seed a thread
        main(["project", "emit", "thread", "name=target-thread", "status=open"])

        # Dry-run an emit that references it
        result = main(["project", "emit", "task", "name=ref-test", "status=open",
                        "related=thread/target-thread", "--dry-run"])
        assert result == 0

        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["related"] == "thread/target-thread"
        assert "related_ref" in d["payload"]

    def _setup_cross_vertex_workspace(self, tmp_path, monkeypatch, *, meta_kinds: str):
        """Set up a workspace with project + meta vertices discoverable from root.

        LOOPS_HOME is the workspace .loops/ dir itself, matching production layout:
          .loops/
            .vertex              # root discover
            project/
              project.vertex     # store "./data/project.db"
            meta/
              meta.vertex        # store "./data/meta.db"

        resolve_vertex("project", LOOPS_HOME) → .loops/project/project.vertex
        discover "./**/*.vertex" finds both project.vertex and meta.vertex
        Both emit and discover resolve to the same store paths.

        Returns (loops_dir,) where loops_dir is LOOPS_HOME.
        """
        workspace = tmp_path / "workspace"
        loops_dir = workspace / ".loops"

        # Root discover vertex
        loops_dir.mkdir(parents=True)
        (loops_dir / ".vertex").write_text('discover "./**/*.vertex"\n')

        # Project vertex — thread/decision/task
        pdir = loops_dir / "project"
        pdir.mkdir()
        (pdir / "project.vertex").write_text(
            'name "project"\n'
            'store "./data/project.db"\n'
            "loops {\n"
            '  thread { fold { items "by" "name" } }\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  task { fold { items "by" "name" } }\n'
            "}\n"
        )

        # Meta vertex
        mdir = loops_dir / "meta"
        mdir.mkdir()
        (mdir / "meta.vertex").write_text(
            'name "meta"\n'
            'store "./data/meta.db"\n'
            f"loops {{\n{meta_kinds}}}\n"
        )

        monkeypatch.setenv("LOOPS_HOME", str(loops_dir))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(workspace)

        return loops_dir

    def test_cross_vertex_entity_ref(self, tmp_path, monkeypatch):
        """Entity ref resolves across vertices when kind exists in a sibling store."""
        loops_dir = self._setup_cross_vertex_workspace(
            tmp_path, monkeypatch,
            meta_kinds=(
                '  dissolution { fold { items "by" "concept" } }\n'
                '  decision { fold { items "by" "topic" } }\n'
            ),
        )

        # Emit a dissolution fact to meta
        result = main(["meta", "emit", "dissolution", "concept=siftd",
                        "message=siftd dissolved into config-level vertex"])
        assert result == 0

        # Emit a thread to project that references the dissolution in meta
        result = main(["project", "emit", "thread", "name=siftd-redesign",
                        "status=resolved", "dissolved_by=dissolution/siftd"])
        assert result == 0

        # Verify the cross-vertex ref was resolved
        db_path = (loops_dir / "project" / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        thread_fact = [f for f in facts if f.kind == "thread"][0]
        payload = dict(thread_fact.payload)

        assert payload["dissolved_by"] == "dissolution/siftd"
        assert "dissolved_by_ref" in payload

        # Verify the ref points to the actual dissolution fact in meta's store
        from engine import StoreReader

        meta_db = (loops_dir / "meta" / "data" / "meta.db").resolve()
        reader = StoreReader(meta_db)
        try:
            resolved = reader.resolve_entity_id("dissolution", "concept", "siftd")
            assert payload["dissolved_by_ref"] == resolved
        finally:
            reader.close()

    def test_cross_vertex_local_miss_topology_hit(self, tmp_path, monkeypatch):
        """Same kind declared in both vertices, entity exists only in sibling."""
        loops_dir = self._setup_cross_vertex_workspace(
            tmp_path, monkeypatch,
            meta_kinds='  decision { fold { items "by" "topic" } }\n',
        )

        # Emit a decision to meta only
        result = main(["meta", "emit", "decision", "topic=design/scaffold-minimalism",
                        "message=Scaffold includes only what every project needs"])
        assert result == 0

        # Emit a thread to project referencing meta's decision
        result = main(["project", "emit", "thread", "name=scaffold-work",
                        "status=resolved",
                        "decided_by=decision/design/scaffold-minimalism"])
        assert result == 0

        db_path = (loops_dir / "project" / "data" / "project.db").resolve()
        facts = _read_all_facts(db_path)
        thread_fact = [f for f in facts if f.kind == "thread"][0]
        payload = dict(thread_fact.payload)

        # Decision doesn't exist in project store, but was found in meta store
        assert payload["decided_by"] == "decision/design/scaffold-minimalism"
        assert "decided_by_ref" in payload


class TestCite:
    """loops cite — attention signal, emits kind=cite with refs only.

    The cite verb no longer accepts a vertex positional. Vertex targeting
    uses vertex-first dispatch (``sl <vertex> cite REF1 ...``) or local
    vertex auto-resolution when running from a vertex directory.
    """

    def _write_cite_vertex(self, home: Path, name: str = "project") -> Path:
        vdir = home / name
        vdir.mkdir(parents=True)
        vertex_path = vdir / f"{name}.vertex"
        vertex_path.write_text(
            f'name "{name}"\n'
            'store "./data/project.db"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  cite { fold { items "collect" 0 } }\n'
            "}\n"
        )
        return vertex_path

    def test_cite_emits_kind_cite_with_comma_joined_refs(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Positional refs become a single comma-separated ref payload.

        Vertex-first dispatch: ``sl project cite REF1 REF2 REF3``.
        """
        home = tmp_path / "home"
        self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite",
            "design/foo", "thread/bar", "atoms/baz",
            "--dry-run",
        ])
        assert result == 0
        captured = capsys.readouterr()
        d = json.loads(captured.out)
        assert d["kind"] == "cite"
        assert d["payload"]["ref"] == "design/foo,thread/bar,atoms/baz"
        assert "message" not in d["payload"]

    def test_cite_context_becomes_payload_field(
        self, tmp_path, monkeypatch, capsys,
    ):
        """--context lands as a plain payload field, not a ref."""
        home = tmp_path / "home"
        self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite", "design/foo",
            "--context", "my-thread",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["ref"] == "design/foo"
        assert d["payload"]["context"] == "my-thread"

    def test_cite_message_becomes_payload_field(
        self, tmp_path, monkeypatch, capsys,
    ):
        """--message lands as a payload field, not a ref. Closes the partial-information gap."""
        home = tmp_path / "home"
        self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite", "design/foo",
            "--message", "informs the salience composition",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["ref"] == "design/foo"
        assert d["payload"]["message"] == "informs the salience composition"

    def test_cite_message_short_flag(
        self, tmp_path, monkeypatch, capsys,
    ):
        """-m is the short form of --message."""
        home = tmp_path / "home"
        self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite", "design/foo",
            "-m", "short form",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["message"] == "short form"

    def test_cite_message_and_context_coexist(
        self, tmp_path, monkeypatch, capsys,
    ):
        """--message and --context land as distinct payload fields."""
        home = tmp_path / "home"
        self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite", "design/foo",
            "--context", "my-thread",
            "--message", "rope-winding moment",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["ref"] == "design/foo"
        assert d["payload"]["context"] == "my-thread"
        assert d["payload"]["message"] == "rope-winding moment"

    def test_cite_persists_as_collect_fold_with_refs(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Cite facts land as collect-fold items with _refs populated."""
        home = tmp_path / "home"
        vertex_path = self._write_cite_vertex(home)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "tester")
        monkeypatch.chdir(tmp_path)

        rc = main(["project", "cite", "design/a", "thread/b"])
        out = capsys.readouterr()
        assert rc == 0, f"cite 1 failed: stdout={out.out!r} stderr={out.err!r}"
        rc = main(["project", "cite", "design/a"])
        out = capsys.readouterr()
        assert rc == 0, f"cite 2 failed: stdout={out.out!r} stderr={out.err!r}"

        from engine import vertex_fold
        data = vertex_fold(vertex_path, observer=None)
        cite_section = next((s for s in data.sections if s.kind == "cite"), None)
        assert cite_section is not None
        assert cite_section.fold_type == "collect"
        assert len(cite_section.items) == 2
        assert cite_section.items[0].refs == ("design/a", "thread/b")
        assert cite_section.items[1].refs == ("design/a",)


class TestCiteVerbRegression:
    """Regression tests for sl-cite-malformed-kind (Bug 1).

    Before the fix, ``sl cite REF1 REF2 -m MSG`` silently absorbed REF1
    into an optional vertex positional and stored only REF2.  These tests
    lock the correct behaviour: all refs are captured and local vertex
    resolution fires when no explicit vertex is given.
    """

    def _write_local_vertex(self, tmp_path: Path) -> Path:
        """Create a .loops/project.vertex resolvable from tmp_path as cwd."""
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        vertex_path = loops_dir / "project.vertex"
        vertex_path.write_text(
            'name "project"\n'
            'store "./data/project.db"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        return vertex_path

    def test_cite_verb_captures_all_refs_without_explicit_vertex(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Bug 1 regression: both REF1 and REF2 appear in stored fact.

        Old behaviour: REF1 absorbed into vertex positional → only REF2 stored.
        New behaviour: no vertex positional → both refs captured in payload.
        """
        self._write_local_vertex(tmp_path)
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        # LOOPS_HOME not set — relies on local vertex discovery from cwd

        result = main([
            "cite",
            "decision:design/foo", "thread:open-arc",
            "-m", "both refs must survive",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["kind"] == "cite"
        ref = d["payload"]["ref"]
        assert "decision:design/foo" in ref
        assert "thread:open-arc" in ref

    def test_cite_verb_vertex_first_form_unchanged(
        self, tmp_path, monkeypatch, capsys,
    ):
        """Vertex-first dispatch (``sl project cite REF1``) is unaffected by Bug 1 fix."""
        home = tmp_path / "home"
        vdir = home / "project"
        vdir.mkdir(parents=True)
        vertex_path = vdir / "project.vertex"
        vertex_path.write_text(
            'name "project"\n'
            'store "./data/project.db"\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main([
            "project", "cite",
            "decision:design/bar",
            "-m", "vertex-first unchanged",
            "--dry-run",
        ])
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["kind"] == "cite"
        assert "decision:design/bar" in d["payload"]["ref"]

    def test_cite_no_local_vertex_errors_clearly(
        self, tmp_path, monkeypatch, capsys,
    ):
        """When no vertex is specified and no local vertex is found, exit 1
        with a message that clearly identifies the problem.
        """
        # chdir to an empty directory — no .vertex files, no LOOPS_HOME
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(empty)
        monkeypatch.delenv("LOOPS_HOME", raising=False)
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(["cite", "decision:design/foo", "-m", "should fail"])
        assert result == 1
        err = capsys.readouterr().err
        assert "no vertex specified" in err


class TestObserverResolution:
    """Observer resolution from .vertex declarations."""

    def _write_vertex_with_observers(
        self, home: Path, name: str, *, observers_kdl: str
    ) -> Path:
        vdir = home / name
        vdir.mkdir(parents=True)
        vertex_path = vdir / f"{name}.vertex"
        vertex_path.write_text(
            f'name "{name}"\n'
            'store "./data/session.db"\n'
            f"{observers_kdl}\n"
            "loops {\n"
            '  counter { fold { count "inc" } }\n'
            "}\n"
        )
        return vertex_path

    def test_observer_from_global_dotvertex(self, tmp_path, monkeypatch, capsys):
        """Single observer in global .vertex auto-resolves."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        # Write global .vertex with observer
        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  test-human { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        # Ensure cwd has no .loops/.vertex in ancestry (avoid project-level pickup)
        monkeypatch.chdir(tmp_path)

        result = main(
            ["session", "emit", "decision", "topic=test", "--dry-run"]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "test-human"

    def test_observer_env_overrides_declaration(self, tmp_path, monkeypatch, capsys):
        """LOOPS_OBSERVER env var selects observer (must still be declared)."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  declared-obs { }\n  env-obs { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "env-obs")

        result = main(
            ["session", "emit", "decision", "topic=test", "--dry-run"]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "env-obs"

    def test_observer_flag_overrides_all(self, tmp_path, monkeypatch, capsys):
        """--observer flag takes highest priority (must still be declared)."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  declared-obs { }\n  flag-obs { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "env-obs")

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "flag-obs",
                "topic=test", "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "flag-obs"

    def test_grant_potential_rejects_invalid_kind(self, tmp_path, monkeypatch, capsys):
        """Observer with grant.potential rejects kinds outside the set."""
        home = tmp_path / "home"
        vertex_path = self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  ci-bot {\n    grant {\n      potential "change" "log"\n    }\n  }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "ci-bot",
                "topic=test",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "cannot emit kind" in err
        assert "decision" in err

    def test_grant_potential_allows_valid_kind(self, tmp_path, monkeypatch):
        """Observer with grant.potential accepts kinds in the set."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  ci-bot {\n    grant {\n      potential "change" "counter"\n    }\n  }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "ci-bot",
                "count=1",
            ]
        )
        assert result == 0

    def test_undeclared_observer_forgiven_by_default(self, tmp_path, monkeypatch, capsys):
        """Undeclared observer is FORGIVEN by default — WARN + store, exit 0 (S6).

        The forgive path (design/declare-observer-print-not-write): the stored
        Row carries the observer regardless, so a missing observers{} declaration
        no longer loses the fact. Grant violations and --strict still refuse.
        """
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  kyle { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        # 'counter' IS declared on this vertex — isolates the observer behavior
        # from kind-not-declared (which would add its own WARN).
        result = main(
            [
                "session", "emit", "counter",
                "--observer", "unknown-user",
                "count=1",
            ]
        )
        assert result == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "not declared" in err
        assert "unknown-user" in err

    def test_undeclared_observer_refused_under_strict(self, tmp_path, monkeypatch, capsys):
        """--strict turns the forgiven undeclared-observer WARN into a refusal (exit 1)."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  kyle { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "unknown-user",
                "count=1",
                "--strict",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "not declared" in err
        assert "unknown-user" in err

    def test_declare_observer_prints_even_when_strict_refuses(self, tmp_path, monkeypatch, capsys):
        """--declare-observer prints the snippet BEFORE the strict refusal — that
        is exactly when the declaration hint is most actionable."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  kyle { }\n}',
        )
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "stranger",
                "count=1",
                "--strict",
                "--declare-observer",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "observers {" in err
        assert "stranger { }" in err

    def test_undeclared_observer_declare_snippet_printed(self, tmp_path, monkeypatch, capsys):
        """--declare-observer prints the observers{} KDL snippet (PRINT-not-write)."""
        home = tmp_path / "home"
        vertex_path = self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  kyle { }\n}',
        )
        original = vertex_path.read_text()

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "kyle/loops-claude",
                "count=1",
                "--declare-observer",
            ]
        )
        assert result == 0
        err = capsys.readouterr().err
        assert "observers {" in err
        assert "loops-claude { }" in err  # bare agent name, namespace stripped
        # PRINT-NOT-WRITE: the .vertex is byte-identical after.
        assert vertex_path.read_text() == original

    def test_namespaced_observer_matches_bare_declaration(self, tmp_path, monkeypatch, capsys):
        """Namespaced observer kyle/loops-claude matches bare declaration loops-claude."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  loops-claude { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "kyle/loops-claude",
                "count=1",
            ]
        )
        assert result == 0

    def test_namespaced_observer_via_env(self, tmp_path, monkeypatch, capsys):
        """LOOPS_OBSERVER=kyle/loops-claude accepted when loops-claude is declared."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  loops-claude { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "kyle/loops-claude")

        result = main(
            ["session", "emit", "counter", "count=1", "--dry-run"]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "kyle/loops-claude"

    def test_namespaced_observer_wrong_agent_forgiven(self, tmp_path, monkeypatch, capsys):
        """kyle/unknown-agent is undeclared (only loops-claude declared) → forgiven
        by default: WARN + store, exit 0 (S6 forgive path)."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  loops-claude { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "kyle/unknown-agent",
                "count=1",
            ]
        )
        assert result == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "not declared" in err

    def test_namespaced_grant_potential_enforced(self, tmp_path, monkeypatch, capsys):
        """Grant potential is still enforced for namespaced observers."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  ci-bot {\n    grant {\n      potential "change" "log"\n    }\n  }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "kyle/ci-bot",
                "topic=test",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "cannot emit kind" in err

    def test_combine_cascade_inherits_source_observers(self, tmp_path, monkeypatch, capsys):
        """Aggregation vertex inherits observers from combine source vertices."""
        home = tmp_path / "home"
        home.mkdir(parents=True)

        # Source vertex with observer declared in its workspace root
        src_dir = tmp_path / "project" / ".loops"
        src_dir.mkdir(parents=True)
        src_vertex = src_dir / "project.vertex"
        src_vertex.write_text(
            'name "project"\n'
            'store "./data/project.db"\n'
            'loops {\n  decision { fold { items "by" "topic" } }\n}\n'
        )
        # Workspace root declares the observer
        ws_root = src_dir / ".vertex"
        ws_root.write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  src-agent { }\n}\n'
        )

        # Aggregation vertex that combines from the source
        agg_dir = home / "project"
        agg_dir.mkdir(parents=True)
        agg_vertex = agg_dir / "project.vertex"
        agg_vertex.write_text(
            'name "project"\n\n'
            f'combine {{\n  vertex "{src_vertex}"\n}}\n'
        )

        # Global .vertex has only kyle — src-agent not declared here
        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  kyle { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.chdir(tmp_path)

        # src-agent should be accepted via cascade
        result = main(
            [
                "project", "emit", "decision",
                "--observer", "src-agent",
                "topic=cascade-test",
                "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "src-agent"
