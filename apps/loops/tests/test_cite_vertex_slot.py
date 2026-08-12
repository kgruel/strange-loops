"""S4 (cli-honesty-wave): verb-first ``sl cite`` gains a vertex slot.

Contract (design/implementation/cli-honesty-wave, S4):
  * ``sl cite <vertex> REF...`` targets the named vertex — parity with
    emit's verb-first grammar (``sl <cmd> <vertex-if-required>``).
  * The first positional is the vertex ONLY when it resolves as one
    (``_resolve_vertex_for_dispatch``); emit's bare-"/" heuristic is NOT
    copied because a legacy slash-form ref (``thread/arc-name``) is a
    legal cite positional.
  * A named vertex bypasses the ambiguous-local-vertex refusal; the
    no-vertex form keeps emit-parity local resolution (.loops/-aware,
    refuses on ambiguity).
  * A cite whose refs ALL drop is an ERROR (nonzero, stderr, nothing
    stored) — not a WARN + empty attention signal. Partial drops keep
    the WARN + typed-pin behavior.

Driving friction: friction:cite-verb-first-lacks-vertex-slot.
"""
import argparse

import pytest

from engine import StoreReader

from loops.cli.invocation import Invocation
from loops.cli.output import BufferReporter
from loops.cli.views import cite as cite_view
from loops.commands.emit import cmd_emit


_VERTEX_TMPL = """\
name "{name}"
store "./{name}.db"

loops {{
  thread {{ fold {{ items "by" "name" }} }}
  cite {{ fold {{ items "collect" 0 }} }}
}}
"""


def _write_vertex(dirpath, name):
    p = dirpath / f"{name}.vertex"
    p.write_text(_VERTEX_TMPL.format(name=name))
    return p


def _ctx(vertex_path=None, vertex_name=None):
    return Invocation(
        reporter=BufferReporter(),
        vertex_path=vertex_path,
        vertex_name=vertex_name,
        observer="tester",
    )


def _emit(vpath, parts, *, kind="cite", **extra):
    """Raw cmd_emit shell — shared by every raw-emit path in this module
    (simplify pass, item 10b; was three per-class copies)."""
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts,
        observer="tester", dry_run=False, **extra,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed_thread(vpath, name):
    rc = _emit(
        vpath, [f"name={name}", "status=open", "message=referent"],
        kind="thread",
    )
    assert rc == 0


def _cite_facts(vpath):
    store = vpath.parent / f"{vpath.stem}.db"
    if not store.exists():
        return []  # nothing was ever stored — no store materialized
    with StoreReader(store) as reader:
        return reader.facts_by_kind("cite")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    # Isolate LOOPS_HOME (no config-level vertices) and run from tmp_path.
    monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def vpath(sandbox):
    """The module's stock vertex ("t") written into the sandbox — replaces
    the per-test `vpath = _write_vertex(sandbox, "t")` line (item 10c)."""
    return _write_vertex(sandbox, "t")


class TestVertexSlot:
    def test_cite_lands_in_named_vertex(self, vpath):
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["t", "thread:arc"], ctx) == 0
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None

    def test_vertex_named_but_no_refs_errors(self, sandbox):
        _write_vertex(sandbox, "t")
        ctx = _ctx()
        assert cite_view.run(["t"], ctx) == 2
        assert any("requires at least one ref" in l for l in ctx.reporter.err_lines)

    def test_named_vertex_bypasses_ambiguity_refusal(self, sandbox):
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        a = _write_vertex(loops_dir, "a")
        _write_vertex(loops_dir, "b")
        _seed_thread(a, "arc")
        ctx = _ctx()
        assert cite_view.run(["a", "thread:arc"], ctx) == 0
        assert len(_cite_facts(a)) == 1

    def test_no_vertex_with_ambiguous_local_refuses(self, sandbox):
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        a = _write_vertex(loops_dir, "a")
        _write_vertex(loops_dir, "b")
        _seed_thread(a, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 2
        assert any("refusing to guess" in l for l in ctx.reporter.err_lines)
        assert _cite_facts(a) == []

    def test_no_vertex_resolves_dot_loops_local(self, sandbox):
        # Emit-parity backward compatibility: the no-vertex form resolves
        # the local vertex .loops/-first, same as emit's no-vertex path.
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        vpath = _write_vertex(loops_dir, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 0
        assert len(_cite_facts(vpath)) == 1

    def test_no_vertex_no_local_errors(self, sandbox):
        ctx = _ctx()
        assert cite_view.run(["thread:arc"], ctx) == 1
        assert any("no local vertex found" in l for l in ctx.reporter.err_lines)

    def test_vertex_first_dispatch_does_not_peel(self, sandbox, vpath):
        # With ctx.vertex_path already resolved (sl <vertex> cite ...), the
        # first positional is a REF even when it happens to resolve as a
        # vertex name — no peel runs.
        decoy = _write_vertex(sandbox, "decoy")
        _seed_thread(vpath, "arc")
        ctx = _ctx(vertex_path=vpath.resolve(), vertex_name="t")
        # "decoy" resolves as a vertex name, but vertex-first dispatch already
        # fixed the vertex — so it must stay a (inert, non-address) ref and
        # the cite must land in t, never in decoy.
        rc = cite_view.run(["decoy", "thread:arc"], ctx)
        assert rc == 0
        assert len(_cite_facts(vpath)) == 1
        assert _cite_facts(decoy) == []

    def test_legacy_slash_ref_not_mistaken_for_vertex(self, sandbox):
        # A slash-form ref must stay a ref (emit's bare-"/" vertex rule is
        # deliberately not copied): thread/arc resolves against the local
        # vertex, not as a vertex named "thread/arc".
        loops_dir = sandbox / ".loops"
        loops_dir.mkdir()
        vpath = _write_vertex(loops_dir, "t")
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        assert cite_view.run(["thread/arc"], ctx) == 0
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None


class TestAllRefsDropError:
    def test_all_refs_drop_errors_and_stores_nothing(self, vpath, capsys):
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent"], ctx)
        assert rc == 2
        err = capsys.readouterr().err
        assert "ERROR" in err
        assert "thread:absent" in err
        assert _cite_facts(vpath) == []

    def test_all_refs_drop_dry_run_also_refuses(self, vpath, capsys):
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent", "--dry-run"], ctx)
        assert rc == 2
        assert "ERROR" in capsys.readouterr().err
        assert _cite_facts(vpath) == []

    def test_partial_drop_stores_with_warning(self, vpath, capsys):
        _seed_thread(vpath, "arc")
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:arc", "thread:absent"], ctx)
        assert rc == 0
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "thread:absent" in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None

    def test_mixed_inert_pin_refusal_message_discloses_counts(self, vpath, capsys):
        # Arbiter ruling (finding:chw-s4-refusal-message-inert-pins):
        # semantics STAND — all attempted (declared-kind) refs failing
        # refuses even when an inert pin rides along — but the message must
        # disclose attempted-vs-inert honestly, not claim "none resolved"
        # about a pin that was never attempted.
        ctx = _ctx()
        # thread is declared (attempted, fails); "atoms" is not declared on
        # this vertex or its topology → atoms/baz is an inert pin.
        rc = cite_view.run(["t", "thread:absent", "atoms/baz"], ctx)
        assert rc == 2
        err = capsys.readouterr().err
        assert "all 1 entity ref(s) failed to resolve" in err
        assert "1 inert pin(s) dropped with the refusal" in err
        assert "none of its refs resolved" not in err
        assert _cite_facts(vpath) == []

    def test_all_attempted_refusal_message_has_no_inert_clause(self, vpath, capsys):
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent", "thread:also-absent"], ctx)
        assert rc == 2
        err = capsys.readouterr().err
        assert "all 2 entity ref(s) failed to resolve" in err
        assert "inert pin" not in err
        assert _cite_facts(vpath) == []

    def test_all_inert_cite_stores_as_provenance_only(self, vpath, capsys):
        # No ref is attempted (no declared-kind address) → the gate never
        # fires and the cite stores as a provenance-only signal: the raw
        # addresses survive in payload, nothing resolved, nothing pinned.
        ctx = _ctx()
        rc = cite_view.run(["t", "atoms/baz", "atoms/qux"], ctx)
        assert rc == 0
        err = capsys.readouterr().err
        assert "ERROR" not in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        payload = facts[0]["payload"]
        assert payload["ref"] == "atoms/baz,atoms/qux"
        assert payload.get("ref_ref") is None
        assert payload.get("_unresolved_refs") is None

    def test_resolving_nonref_field_address_does_not_rescue(
        self, vpath, capsys,
    ):
        # finding:chw-sol-r1-s4-f1-nonref-field-bypass (arbiter ruling): the
        # gate counts ONLY field=="ref" resolutions. A resolvable address in
        # the message must not turn an all-drop cite into a store.
        _seed_thread(vpath, "other")
        ctx = _ctx()
        rc = cite_view.run(["t", "thread:absent", "-m", "thread:other"], ctx)
        assert rc == 2
        err = capsys.readouterr().err
        assert "thread:absent" in err
        assert "nothing stored" in err
        assert _cite_facts(vpath) == []

    def test_emit_path_gets_same_refusal(self, vpath, capsys):
        # The refusal is kind-level (lives in cmd_emit), so the raw emit
        # spelling of a cite refuses identically.
        ns = argparse.Namespace(
            vertex=None, kind="cite", parts=["ref=thread:absent"],
            observer="tester", dry_run=False,
        )
        assert cmd_emit(ns, vertex_path=vpath) == 2
        assert "ERROR" in capsys.readouterr().err
        assert _cite_facts(vpath) == []


class TestZeroAddressCite:
    """finding:chw-s4-raw-emit-empty-cite (arbiter ruling): a cite whose
    payload carries literally NO ref addresses refuses — there is nothing
    being cited. All-inert cites (addresses present, none attemptable as
    entities) still store as provenance-only."""

    def test_raw_emit_with_no_ref_field_refuses(self, vpath, capsys):
        rc = _emit(vpath, ["message=x"])
        err = capsys.readouterr().err
        assert rc == 2
        assert "no ref addresses" in err
        assert "nothing stored" in err
        assert _cite_facts(vpath) == []

    def test_resolving_message_address_does_not_rescue_zero_refs(
        self, vpath, capsys,
    ):
        # Composition with the ref-field-scoped gate: a resolvable address
        # in message does not manufacture a cite ref.
        _seed_thread(vpath, "other")
        rc = _emit(vpath, ["message=thread:other"])
        assert rc == 2
        assert "no ref addresses" in capsys.readouterr().err
        # only the seeded thread exists — no cite stored
        assert _cite_facts(vpath) == []

    def test_empty_ref_field_refuses(self, vpath, capsys):
        rc = _emit(vpath, ["ref=", "message=x"])
        assert rc == 2
        assert "no ref addresses" in capsys.readouterr().err
        assert _cite_facts(vpath) == []

    def test_all_inert_raw_emit_still_stores(self, vpath, capsys):
        # The ruling's explicit boundary: inert addresses ARE addresses.
        rc = _emit(vpath, ["ref=atoms/baz"])
        err = capsys.readouterr().err
        assert rc == 0
        assert "ERROR" not in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"]["ref"] == "atoms/baz"


class TestMalformedTokenGate:
    """finding:chw-sol-r2-f1-malformed-token-evades-gate (arbiter ruling):
    ref_addrs counts only tokens that PARSE under the canonical address
    grammar — resolve.parse_ref_token, the exact acceptance
    _resolve_entity_refs applies to ref-field tokens (dissolution: the
    discriminator already existed; no new validator). All-malformed refuses
    like zero-address; a malformed token riding with a storing cite gets a
    per-token WARN and keeps its current storage behavior (raw in refs)."""

    @pytest.mark.parametrize("token", [":x", "kind:", "not an address"])
    def test_all_malformed_refuses(self, vpath, capsys, token):
        rc = _emit(vpath, [f"ref={token}"])
        err = capsys.readouterr().err
        assert rc == 2
        assert f"ref '{token}' does not parse as an address" in err
        assert "nothing stored" in err
        assert _cite_facts(vpath) == []

    def test_bare_separatorless_key_is_malformed(self, vpath, capsys):
        # The resolver's ref-field acceptance requires a kind (self-
        # describing ref needs a separator) — a bare key never counts.
        rc = _emit(vpath, ["ref=barekey"])
        assert rc == 2
        assert "does not parse as an address" in capsys.readouterr().err
        assert _cite_facts(vpath) == []

    def test_malformed_with_inert_stores_with_warn_raw_kept(
        self, vpath, capsys,
    ):
        # An inert (undeclared-kind) address is well-formed → the cite
        # stores; the malformed token WARNs and stays raw in the payload.
        rc = _emit(vpath, ["ref=:x,atoms/baz"])
        err = capsys.readouterr().err
        assert rc == 0
        assert "WARN: ref ':x' does not parse as an address" in err
        assert "ERROR" not in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"]["ref"] == ":x,atoms/baz"

    def test_malformed_with_valid_stores_with_warn(self, vpath, capsys):
        _seed_thread(vpath, "arc")
        rc = _emit(vpath, ["ref=:x,thread:arc"])
        err = capsys.readouterr().err
        assert rc == 0
        assert "WARN: ref ':x' does not parse as an address" in err
        facts = _cite_facts(vpath)
        assert len(facts) == 1
        assert facts[0]["payload"].get("ref_ref") is not None
        assert facts[0]["payload"]["ref"] == ":x,thread:arc"

    def test_dry_run_all_malformed_also_refuses(self, vpath, capsys):
        ns = argparse.Namespace(
            vertex=None, kind="cite", parts=["ref=:x"],
            observer="tester", dry_run=True,
        )
        rc = cmd_emit(ns, vertex_path=vpath)
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""  # no fact-JSON preview on a refusal
        assert "does not parse as an address" in captured.err
        assert _cite_facts(vpath) == []

    def test_json_all_malformed_refuses_with_empty_stdout(
        self, vpath, capsys,
    ):
        # --json's receipt only fires post-store; a refusal must leave
        # stdout empty (no structured receipt for a fact that never landed).
        ns = argparse.Namespace(
            vertex=None, kind="cite", parts=["ref=kind:"],
            observer="tester", dry_run=False, json=True,
        )
        rc = cmd_emit(ns, vertex_path=vpath)
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "does not parse as an address" in captured.err
        assert _cite_facts(vpath) == []

    def test_verb_first_malformed_positional_refuses(self, vpath, capsys):
        rc = cite_view.run(["t", ":x"], _ctx())
        assert rc == 2
        assert "does not parse as an address" in capsys.readouterr().err
        assert _cite_facts(vpath) == []
