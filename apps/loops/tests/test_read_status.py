"""S1 cli-honesty-wave — ``read --status``: payload-equality filter + honesty.

The flag is sugar over the ``status=VALUE`` bareword predicate (it merges into
``SurfaceSpec.where``), plus an honesty layer the predicate never had: a
fetched kind whose rows carry no status field is REPORTED (stderr note on a
mixed fetch; exit-2 refusal when no fetched rowful kind carries one) instead
of yielding a plausible-empty — the silent loss that drove
friction:read-status-filter-missing. Composability with --kind/--key and the
error discipline (nonzero exit, error on stderr) are pinned here too.

Contract: design:implementation/cli-honesty-wave (S1).
"""
from __future__ import annotations

import argparse
import json

import pytest

from engine.builder import fold_by, vertex
from loops.main import cmd_emit, main


# --- Fixtures + helpers ----------------------------------------------------


@pytest.fixture
def status_vertex(tmp_path):
    """Two by-fold kinds: ``thread`` rows carry ``status``; ``decision`` rows
    deliberately do NOT (the honesty-note target)."""
    v = (
        vertex("statusv")
        .store("./s.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
    )
    vpath = tmp_path / "statusv.vertex"
    v.write(vpath)
    return vpath


def _emit(vpath, kind, **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer="kyle", dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed(vpath):
    assert _emit(vpath, "decision", topic="design/a", message="alpha") == 0
    assert _emit(vpath, "decision", topic="arch/b", message="beta") == 0
    assert _emit(vpath, "thread", name="t-open", message="one", status="open") == 0
    assert _emit(vpath, "thread", name="t-res", message="two", status="resolved") == 0
    assert _emit(vpath, "thread", name="t-also-open", message="three", status="open") == 0


def _json_read(capsys, *argv):
    """Run ``read <argv> --json``; return (rc, surface-dict-or-None, stderr)."""
    capsys.readouterr()
    rc = main(["read", *argv, "--json"])
    captured = capsys.readouterr()
    surface = json.loads(captured.out) if captured.out.strip() else None
    return rc, surface, captured.err


def _keys(surface):
    return sorted(r["key"] for r in surface["rows"])


# --- The filter ------------------------------------------------------------


class TestStatusFilter:
    def test_basic_filter(self, status_vertex, capsys):
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex), "--kind", "thread", "--status", "open",
        )
        assert rc == 0
        assert _keys(s) == ["t-also-open", "t-open"]
        assert err == ""

    def test_comma_or(self, status_vertex, capsys):
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--kind", "thread", "--status", "open,resolved",
        )
        assert rc == 0
        assert _keys(s) == ["t-also-open", "t-open", "t-res"]

    def test_composes_with_key(self, status_vertex, capsys):
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--kind", "thread", "--key", "t-open", "--status", "open",
        )
        assert rc == 0
        assert _keys(s) == ["t-open"]

    def test_no_match_on_status_bearing_kind_is_silent_honest_empty(
        self, status_vertex, capsys,
    ):
        """The r2 gate's load-bearing read: rows CARRY status, none match the
        value → empty, exit 0, NO note. Honest empty, not plausible-empty."""
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex), "--kind", "thread", "--status", "closed",
        )
        assert rc == 0
        assert s["rows"] == []
        assert err == ""

    def test_facts_view_composes(self, status_vertex, capsys):
        """Bare ``--facts`` (no window) rides the fold route — --status applies."""
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--kind", "thread", "--status", "open", "--facts",
        )
        assert rc == 0
        assert _keys(s) == ["t-also-open", "t-open"]


# --- Honesty: kinds without a status field ---------------------------------


class TestStatuslessKindHonesty:
    def test_single_statusless_kind_refuses(self, status_vertex, capsys):
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex), "--kind", "decision", "--status", "open",
        )
        assert rc == 2
        assert s is None  # nothing on stdout — refusal, not a plausible-empty
        assert "kind 'decision' has no status field" in err

    def test_mixed_fetch_notes_and_filters(self, status_vertex, capsys):
        _seed(status_vertex)
        rc, s, err = _json_read(capsys, str(status_vertex), "--status", "open")
        assert rc == 0
        # decisions (statusless) dropped by the filter, threads filtered to open
        assert _keys(s) == ["t-also-open", "t-open"]
        assert "note: kind 'decision' has no status field" in err

    def test_empty_store_is_honest_empty_not_refusal(self, status_vertex, capsys):
        """Zero rows anywhere: nothing to claim a missing field from."""
        rc, s, err = _json_read(capsys, str(status_vertex), "--status", "open")
        assert rc == 0
        assert s["rows"] == []
        assert "has no status field" not in err


# --- r1 remediation: census on the post-key_or set --------------------------
# finding:chw-sol-r1-s1-f1-comma-key-census — a single --key narrows at fetch,
# but comma-OR --key is applied by the Surface AFTER the census ran; censusing
# the un-narrowed fetch let an unrelated status-bearing kind flip the
# statusless refusal into a plausible-empty exit 0.


class TestCommaKeyCensus:
    def test_comma_key_selecting_only_statusless_rows_refuses(
        self, status_vertex, capsys,
    ):
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--key", "design/a,missing", "--status", "open",
        )
        assert rc == 2
        assert s is None
        assert "kind 'decision' has no status field" in err

    def test_comma_key_parity_with_single_key(self, status_vertex, capsys):
        """The comma spelling of the same selection answers identically."""
        _seed(status_vertex)
        rc1, s1, err1 = _json_read(
            capsys, str(status_vertex), "--key", "design/a", "--status", "open",
        )
        rc2, s2, err2 = _json_read(
            capsys, str(status_vertex),
            "--key", "design/a,missing", "--status", "open",
        )
        assert (rc1, s1) == (2, None)
        assert (rc2, s2) == (2, None)
        assert err1 == err2

    def test_comma_key_all_prefixes_miss_is_honest_empty(
        self, status_vertex, capsys,
    ):
        """No surviving rows anywhere: nothing to claim a missing field from
        — honest empty at exit 0, parity with a single missing --key."""
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--key", "nope1,nope2", "--status", "open",
        )
        assert rc == 0
        assert s["rows"] == []
        assert "has no status field" not in err

    def test_comma_key_reaching_status_rows_filters_with_note(
        self, status_vertex, capsys,
    ):
        """Mixed post-key_or set: statusless decision noted, threads filter."""
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex),
            "--key", "design/a,t-", "--status", "open",
        )
        assert rc == 0
        assert _keys(s) == ["t-also-open", "t-open"]
        assert "note: kind 'decision' has no status field" in err


# --- r1 remediation: custom-lens --status refuses ---------------------------
# finding:chw-sol-r1-s1-f2-custom-lens-inert (arbiter ruling: REFUSE) — a
# gate-fail static read never applies the Surface transforms, so an accepted
# --status rendering unfiltered rows at exit 0 was script-misreadable. The
# prior inert-note-and-continue behavior for --status is overturned; the note
# survives only for the other transforms (and the bareword predicate).


class TestCustomLensStatusRefusal:
    def test_lens_override_with_status_refuses(self, status_vertex, capsys):
        _seed(status_vertex)
        capsys.readouterr()
        rc = main([
            "read", str(status_vertex), "--kind", "decision",
            "--status", "open", "--lens", "autoresearch", "--plain",
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "read --status" in captured.err
        assert "custom lens" in captured.err
        assert "does not apply the status filter" in captured.err
        assert "--lens autoresearch" in captured.err

    def test_lens_override_with_status_json_also_refuses(
        self, status_vertex, capsys,
    ):
        """The refusal sits before the Format branch — --json cannot fall
        through to the raw dump."""
        _seed(status_vertex)
        rc, s, err = _json_read(
            capsys, str(status_vertex), "--kind", "decision",
            "--status", "open", "--lens", "autoresearch",
        )
        assert rc == 2
        assert s is None
        assert "read --status" in err

    def test_bareword_status_predicate_keeps_inert_note(
        self, status_vertex, capsys,
    ):
        """S1 scoped the honesty layer to the explicit flag — the bareword
        ``status=`` predicate keeps its pre-S1 note-and-render behavior, and
        the note no longer lists --status (it refuses instead)."""
        _seed(status_vertex)
        capsys.readouterr()
        rc = main([
            "read", str(status_vertex), "--kind", "decision",
            "status=open", "--lens", "autoresearch", "--plain",
        ])
        captured = capsys.readouterr()
        assert rc == 0
        assert "note: read-grammar transforms" in captured.err
        assert "--status" not in captured.err


# --- Error discipline (nonzero exit, error on stderr) ----------------------


class TestStatusErrorDiscipline:
    @pytest.mark.parametrize(
        ("argv_tail", "expected"),
        [
            pytest.param(
                ["--status", ","], "empty --status value",
                id="empty-value",
            ),
            pytest.param(
                ["status=open", "--status", "open"], "same filter",
                id="conflict-with-bareword-predicate",
            ),
            pytest.param(
                ["--facts", "--since", "7d", "--status", "open"],
                "read --status",
                id="windowed-facts-route",
            ),
            pytest.param(
                ["--ticks", "--status", "open"], "read --status",
                id="ticks-route",
            ),
        ],
    )
    def test_refuses(self, status_vertex, capsys, argv_tail, expected):
        _seed(status_vertex)
        rc, s, err = _json_read(capsys, str(status_vertex), *argv_tail)
        assert rc == 2
        assert s is None
        assert expected in err

    def test_why_refuses(self, status_vertex, capsys):
        _seed(status_vertex)
        capsys.readouterr()
        rc = main([
            "read", str(status_vertex), "thread/t-open", "--why",
            "--status", "open",
        ])
        captured = capsys.readouterr()
        assert rc == 2
        assert captured.out == ""
        assert "--why" in captured.err
