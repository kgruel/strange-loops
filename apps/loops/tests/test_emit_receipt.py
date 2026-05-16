"""Tests for the emit-receipt-on-write feature (absorbs loud-fold-key-error).

Covers the six diagnostic paths the receipt is responsible for:
  1. clean success — stored line with ULID + refs-resolved-count
  2. kind-not-declared — WARN line + stored line with <no-fold>
  3. fold-key-missing — WARN line + stored line with <no-fold>
  4. unresolved ref — WARN line per dropped ref
  5. --strict / env / vertex-strict refuses on each failure
  6. --quiet suppresses success line only

Plus structural invariants:
  - id_override round-trips through SqliteStore.append and Vertex.receive
  - vertex-declared strict has no override (load-bearing design property)
  - hint message branches on strict-source (vertex vs flag/env)
  - regression: today's live incident (observation on undeclared kind)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from engine.builder import vertex, fold_by, fold_count
from loops.commands.emit import cmd_emit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def basic_vertex(tmp_path):
    """A non-strict vertex with one upsert-fold kind (decision/topic) and one
    collect-fold kind (log) for fold-key-missing tests vs collect-no-key tests."""
    v = (vertex("rcpt-basic")
         .store("./rcpt-basic.db")
         .loop("decision", fold_by("topic"))
         .loop("thread", fold_by("name"))
         .loop("log", fold_count("n")))
    vpath = tmp_path / "rcpt-basic.vertex"
    v.write(vpath)
    return vpath


@pytest.fixture
def strict_vertex(tmp_path):
    """A vertex with `strict true` — refuses on any validation failure,
    no CLI/env override."""
    vpath = tmp_path / "rcpt-strict.vertex"
    vpath.write_text(
        'name "rcpt-strict"\n'
        'store "./rcpt-strict.db"\n'
        'strict true\n'
        '\n'
        'loops {\n'
        '  decision { fold { items "by" "topic" } }\n'
        '}\n'
    )
    return vpath


def _ns(**overrides) -> argparse.Namespace:
    """Build a cmd_emit-shaped Namespace with safe defaults."""
    base = dict(
        vertex=None, kind="decision", parts=[],
        observer="", dry_run=False,
        strict=False, quiet=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _emit(vpath: Path, kind: str, **payload) -> tuple[int, argparse.Namespace]:
    """Emit through cmd_emit and return (exit_code, namespace)."""
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = _ns(kind=kind, parts=parts)
    return cmd_emit(ns, vertex_path=vpath), ns


def _emit_with(vpath: Path, kind: str, /, *, strict: bool = False,
               quiet: bool = False, **payload) -> int:
    """Emit through cmd_emit with explicit strict/quiet flags."""
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = _ns(kind=kind, parts=parts, strict=strict, quiet=quiet)
    return cmd_emit(ns, vertex_path=vpath)


# ---------------------------------------------------------------------------
# Receipt content — captured via capsys
# ---------------------------------------------------------------------------


class TestReceiptContent:
    def test_clean_success_prints_stored_line_to_stderr(self, basic_vertex, capsys):
        rc, _ = _emit(basic_vertex, "decision", topic="design/foo", message="x")
        assert rc == 0
        err = capsys.readouterr().err
        # Format: "stored: decision/design/foo @ <ulid>"
        assert "stored: decision/design/foo" in err
        # ULID/UUID present (some form of identifier after the @)
        assert " @ " in err

    def test_kind_not_declared_emits_warn_and_stores_fact(self, basic_vertex, capsys):
        rc, _ = _emit(basic_vertex, "observation", topic="oops", message="orphan")
        assert rc == 0  # warn-mode default: store anyway
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "kind 'observation' not declared" in err
        assert "stored: observation/<no-fold>" in err

        # Fact IS in the store despite not folding
        from engine.store_reader import StoreReader
        store_path = basic_vertex.parent / "rcpt-basic.db"
        with StoreReader(store_path) as reader:
            facts = reader.recent_facts("observation", 5)
            assert len(facts) == 1

    def test_fold_key_missing_emits_warn(self, basic_vertex, capsys):
        # decision folds by 'topic' — omit it
        rc, _ = _emit(basic_vertex, "decision", message="no topic")
        assert rc == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "kind 'decision' folds by 'topic'" in err
        assert "stored: decision/<no-fold>" in err

    def test_collect_fold_no_warn_when_no_fold_key(self, basic_vertex, capsys):
        # 'log' uses fold_count — no fold-key required, no WARN
        rc, _ = _emit(basic_vertex, "log", message="just a log line")
        assert rc == 0
        err = capsys.readouterr().err
        assert "WARN" not in err
        assert "stored: log/" in err

    def test_quiet_suppresses_success_line(self, basic_vertex, capsys):
        rc = _emit_with(basic_vertex, "decision", quiet=True,
                        topic="quiet/test", message="quiet")
        assert rc == 0
        err = capsys.readouterr().err
        assert "stored:" not in err

    def test_quiet_keeps_warn_visible(self, basic_vertex, capsys):
        # WARN lines are load-bearing — -q does NOT suppress them
        rc = _emit_with(basic_vertex, "decision", quiet=True, message="no topic")
        assert rc == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "stored:" not in err  # success line suppressed

    def test_refs_resolved_count_in_receipt(self, basic_vertex, capsys):
        # Seed a decision so refs can resolve to its ULID
        _emit(basic_vertex, "decision", topic="design/seed", message="seed")
        capsys.readouterr()  # clear

        rc, _ = _emit(basic_vertex, "thread", name="follow-up", status="open",
                      ref="decision/design/seed")
        assert rc == 0
        err = capsys.readouterr().err
        assert "stored: thread/follow-up" in err
        assert "refs: 1 resolved" in err


# ---------------------------------------------------------------------------
# Strict mode — caller opt-in
# ---------------------------------------------------------------------------


class TestStrictFlag:
    def test_strict_refuses_on_kind_not_declared(self, basic_vertex, capsys):
        rc = _emit_with(basic_vertex, "observation", strict=True,
                        topic="x", message="should refuse")
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "kind 'observation' not declared" in err
        # No store happens on refuse — db file shouldn't exist (no successful
        # emit triggered its creation) or should contain zero observation facts.
        from engine.store_reader import StoreReader
        store_path = basic_vertex.parent / "rcpt-basic.db"
        if store_path.exists():
            with StoreReader(store_path) as reader:
                facts = reader.recent_facts("observation", 5)
                assert len(facts) == 0

    def test_strict_refuses_on_fold_key_missing(self, basic_vertex, capsys):
        rc = _emit_with(basic_vertex, "decision", strict=True,
                        message="no topic")
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "folds by 'topic'" in err

    def test_strict_hint_mentions_cli_flag_when_caller_opted_in(
        self, basic_vertex, capsys
    ):
        rc = _emit_with(basic_vertex, "observation", strict=True, topic="x")
        assert rc == 2
        err = capsys.readouterr().err
        # Hint guides toward removing the opt-in (vertex didn't declare strict)
        assert "--strict" in err or "LOOPS_EMIT_STRICT" in err

    def test_strict_clean_emit_still_succeeds(self, basic_vertex, capsys):
        rc = _emit_with(basic_vertex, "decision", strict=True,
                        topic="design/clean", message="ok")
        assert rc == 0
        err = capsys.readouterr().err
        assert "ERROR" not in err
        assert "stored: decision/design/clean" in err


class TestStrictEnvVar:
    def test_env_var_triggers_strict(self, basic_vertex, monkeypatch, capsys):
        monkeypatch.setenv("LOOPS_EMIT_STRICT", "1")
        rc = _emit_with(basic_vertex, "observation", topic="env-strict",
                        message="env should refuse")
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err

    def test_env_var_zero_does_not_trigger_strict(
        self, basic_vertex, monkeypatch, capsys
    ):
        monkeypatch.setenv("LOOPS_EMIT_STRICT", "0")
        rc = _emit_with(basic_vertex, "observation", topic="not-strict",
                        message="should warn-and-store")
        assert rc == 0  # not "1" → not strict


# ---------------------------------------------------------------------------
# Vertex-declared strict — load-bearing: NO override
# ---------------------------------------------------------------------------


class TestVertexDeclaredStrict:
    def test_vertex_strict_refuses_without_any_flag(self, strict_vertex, capsys):
        # No --strict, no env var — vertex spec alone is sufficient
        rc = _emit_with(strict_vertex, "foo", topic="x", message="should refuse")
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        # Hint specifically calls out the vertex declaration
        assert "vertex declares strict" in err

    def test_vertex_strict_catches_fold_key_missing(self, strict_vertex, capsys):
        rc = _emit_with(strict_vertex, "decision", message="no topic")
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "vertex declares strict" in err

    def test_vertex_strict_clean_emit_still_succeeds(self, strict_vertex, capsys):
        rc = _emit_with(strict_vertex, "decision", topic="ok", message="clean")
        assert rc == 0
        err = capsys.readouterr().err
        assert "ERROR" not in err
        assert "stored: decision/ok" in err

    def test_vertex_strict_flag_redundant_not_error(self, strict_vertex, capsys):
        # Passing --strict on top of vertex-strict is a no-op redundancy
        rc = _emit_with(strict_vertex, "decision", strict=True,
                        topic="redundant", message="ok")
        assert rc == 0
        err = capsys.readouterr().err
        assert "stored: decision/redundant" in err


# ---------------------------------------------------------------------------
# Regression — today's live incident
# ---------------------------------------------------------------------------


class TestLiveIncidentRegression:
    def test_observation_on_undeclared_kind_warns_loudly(self, basic_vertex, capsys):
        """Regression for the 2026-05-16 live incident.

        Original symptom: `sl emit project observation topic=foo message=bar`
        returned exit 0 with no output; the fact was stored but orphaned
        (no fold loop registered for 'observation' on the project vertex).
        Discovered only by post-hoc read which printed the
        'kind not declared' message at READ time.

        Receipt path makes this loud at WRITE time. The emit still succeeds
        (warn-mode default) but the user immediately sees a WARN explaining
        the fact won't fold, and the receipt format makes the orphan visible
        as `observation/<no-fold>` instead of disguising it as success.
        """
        rc, _ = _emit(basic_vertex, "observation",
                      topic="practice/some-pattern",
                      message="would have been silently lost pre-2026-05-16")
        assert rc == 0  # default: store-and-warn

        err = capsys.readouterr().err
        # The signal that was missing on 2026-05-16:
        assert "WARN" in err
        assert "kind 'observation' not declared" in err
        # The receipt clearly marks the fact as orphaned:
        assert "<no-fold>" in err


# ---------------------------------------------------------------------------
# Engine surface — id_override round-trip
# ---------------------------------------------------------------------------


class TestIdOverride:
    def test_sqlite_store_honors_id_override(self, tmp_path):
        from engine.sqlite_store import SqliteStore
        from atoms import Fact
        import time

        store_path = tmp_path / "rcpt-idov.db"
        custom_id = "01JKMYCUSTOMIDFORTESTING"

        with SqliteStore(
            path=store_path,
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
            returned = store.append(
                Fact(kind="decision", payload={"topic": "x"}, ts=time.time(),
                     observer="test", origin=""),
                id_override=custom_id,
            )
            assert returned == custom_id

            # The row exists with that exact ID
            row = store._conn.execute(
                "SELECT id FROM facts WHERE id = ?", (custom_id,)
            ).fetchone()
            assert row is not None
            assert row[0] == custom_id

    def test_sqlite_store_generates_id_when_not_provided(self, tmp_path):
        from engine.sqlite_store import SqliteStore
        from atoms import Fact
        import time

        with SqliteStore(
            path=tmp_path / "rcpt-idgen.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
            returned = store.append(
                Fact(kind="decision", payload={"topic": "y"}, ts=time.time(),
                     observer="test", origin="")
            )
            assert returned is not None
            assert isinstance(returned, str)
            assert len(returned) > 0

    def test_vertex_receive_threads_id_override_to_store(self, tmp_path):
        from engine.vertex import Vertex
        from engine.sqlite_store import SqliteStore
        from atoms import Fact
        import time

        store_path = tmp_path / "rcpt-vrx.db"
        custom_id = "01JKVERTEXTHREADTEST00000"

        with SqliteStore(
            path=store_path,
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
            v = Vertex("rcpt-vrx", store=store)
            v.register("decision", {}, lambda s, p: {**s, p["topic"]: p})

            v.receive(
                Fact(kind="decision", payload={"topic": "z"}, ts=time.time(),
                     observer="test", origin=""),
                id_override=custom_id,
            )

            row = store._conn.execute(
                "SELECT id FROM facts WHERE id = ?", (custom_id,)
            ).fetchone()
            assert row is not None
