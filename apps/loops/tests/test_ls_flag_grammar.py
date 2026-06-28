"""Tests for the fix/ls-flag-grammar grammar convergence.

`sl ls` accepts narrowing in two equivalent shapes:

  Flag form (canonical, composes, matches `sl read`):
    sl ls <v> --kind             KINDS section only
    sl ls <v> --kind decision    narrow KINDS to one entry
    sl ls <v> --kind --observer  KINDS + OBSERVERS sections (order-independent)

  Positional alias (back-compat, single section, no name narrowing):
    sl ls <v> kind               equivalent to --kind (bare)

Mixing both forms in one invocation is an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from engine.builder import fold_by, fold_collect, vertex
from loops.commands.add import _run_add
from loops.commands.ls import _peel_section_flags, _run_ls, fetch_declarations

from .helpers import block_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def proj(loops_home) -> Path:
    """A vertex with two kinds and two observers — exercises kind/observer narrowing."""
    vdir = loops_home / "proj"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "proj.vertex"
    (
        vertex("proj")
        .store("./data/proj.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
        .loop("change", fold_collect("items", max_items=20))
        .write(vpath)
    )
    _run_add(["proj", "observer", "kyle"])
    _run_add(["proj", "observer", "alcove"])
    return vpath


# ---------------------------------------------------------------------------
# argparse edge case (PLAN.md §A) — chained bare flags with nargs="?"
# ---------------------------------------------------------------------------


class TestFlagPeelChainedBare:
    """nargs='?' must NOT consume a following --flag as the value."""

    def test_kind_then_observer(self):
        filters, narrows, leftover = _peel_section_flags(["--kind", "--observer"])
        assert filters == ["kind", "observer"]
        assert narrows == {}
        assert leftover == []

    def test_observer_then_kind(self):
        filters, narrows, leftover = _peel_section_flags(["--observer", "--kind"])
        assert filters == ["kind", "observer"]  # _SECTION_FLAGS order
        assert narrows == {}
        assert leftover == []

    def test_kind_value_then_bare_observer(self):
        filters, narrows, leftover = _peel_section_flags(
            ["--kind", "decision", "--observer"]
        )
        assert filters == ["kind", "observer"]
        assert narrows == {"kind": "decision"}
        assert leftover == []

    def test_three_chained_bare(self):
        filters, narrows, _ = _peel_section_flags(
            ["--observer", "--combine", "--kind"]
        )
        assert filters == ["kind", "observer", "combine"]
        assert narrows == {}

    def test_no_flags(self):
        filters, narrows, leftover = _peel_section_flags([])
        assert filters == []
        assert narrows == {}
        assert leftover == []

    def test_unrelated_args_left_alone(self):
        filters, narrows, leftover = _peel_section_flags(["--plain", "-v"])
        assert filters == []
        assert narrows == {}
        assert leftover == ["--plain", "-v"]


# ---------------------------------------------------------------------------
# fetch_declarations — both legacy and new narrowing inputs
# ---------------------------------------------------------------------------


class TestFetchDeclarationsNarrowing:
    def test_legacy_filter_still_works(self, proj):
        data = fetch_declarations("proj", filter_="kind")
        assert data["filter"] == "kind"
        # The new shape is back-filled for lens consumption.
        assert data["filters"] == ["kind"]

    def test_filters_single_section(self, proj):
        data = fetch_declarations("proj", filters=["kind"])
        assert data["filters"] == ["kind"]
        # Single-section filters back-fill legacy `filter`.
        assert data["filter"] == "kind"

    def test_filters_multi_section(self, proj):
        data = fetch_declarations("proj", filters=["kind", "observer"])
        assert data["filters"] == ["kind", "observer"]
        # Multi-section: no legacy single value.
        assert data["filter"] is None

    def test_narrow_by_name(self, proj):
        data = fetch_declarations(
            "proj", filters=["kind"], narrows={"kind": "decision"}
        )
        assert data["narrows"] == {"kind": "decision"}

    def test_narrowing_does_not_drop_raw_items(self, proj):
        # fetch returns all rows — narrowing is the lens's job.
        data = fetch_declarations(
            "proj", filters=["kind"], narrows={"kind": "decision"}
        )
        kind_names = {k["name"] for k in data["kinds"]}
        assert {"decision", "thread", "change"} <= kind_names


# ---------------------------------------------------------------------------
# Lens rendering with new narrowing inputs
# ---------------------------------------------------------------------------


class TestLensNarrowing:
    def test_flag_form_kind_only(self, proj):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj", filters=["kind"])
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "KINDS" in text
        assert "OBSERVERS" not in text

    def test_flag_form_multi_section(self, proj):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj", filters=["kind", "observer"])
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "KINDS" in text
        assert "OBSERVERS" in text
        assert "COMBINE" not in text  # not selected
        assert "SOURCES" not in text

    def test_narrow_by_name_shows_one_row(self, proj):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations(
            "proj", filters=["kind"], narrows={"kind": "decision"}
        )
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "decision" in text
        # The other kinds should NOT appear.
        assert "thread" not in text
        assert "change" not in text

    def test_narrow_by_unknown_name_renders_empty(self, proj):
        """Consistent with read --kind <unknown>: render an empty section."""
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations(
            "proj", filters=["kind"], narrows={"kind": "nonexistent"}
        )
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        # Section header present with zero count, no real declarations.
        assert "KINDS (—)" in text or "KINDS (0)" in text
        assert "decision" not in text

    def test_narrow_observer_by_name(self, proj):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations(
            "proj", filters=["observer"], narrows={"observer": "kyle"}
        )
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "kyle" in text
        assert "alcove" not in text

    def test_minimal_zoom_counts_after_narrowing(self, proj):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations(
            "proj", filters=["kind"], narrows={"kind": "decision"}
        )
        text = block_text(declarations_view(data, Zoom.MINIMAL, 80))
        # MINIMAL respects the narrow — count reflects filtered items.
        assert "kinds=1" in text


# ---------------------------------------------------------------------------
# _run_ls end-to-end — verifies argv parsing + dispatch
# ---------------------------------------------------------------------------


def _capture_run_ls(argv: list[str], capsys) -> tuple[int, str, str]:
    """Run _run_ls and capture stdout/stderr text."""
    rc = _run_ls(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


class TestRunLsGrammar:
    def test_flag_form_bare_kind(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "--kind"], capsys)
        assert rc == 0
        assert "KINDS" in out
        assert "OBSERVERS" not in out

    def test_flag_form_bare_observer(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "--observer"], capsys)
        assert rc == 0
        assert "OBSERVERS" in out
        assert "KINDS" not in out

    def test_flag_form_narrow(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "--kind", "decision"], capsys)
        assert rc == 0
        assert "decision" in out
        assert "thread" not in out

    def test_flag_form_chained_bare(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "--kind", "--observer"], capsys)
        assert rc == 0
        assert "KINDS" in out
        assert "OBSERVERS" in out

    def test_flag_form_chained_bare_order_independent(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "--observer", "--kind"], capsys)
        assert rc == 0
        assert "KINDS" in out
        assert "OBSERVERS" in out

    def test_flag_form_narrow_plus_bare(self, proj, capsys):
        rc, out, _ = _capture_run_ls(
            ["proj", "--kind", "decision", "--observer"], capsys
        )
        assert rc == 0
        assert "decision" in out
        assert "thread" not in out  # narrowed
        assert "OBSERVERS" in out
        assert "kyle" in out
        assert "alcove" in out  # not narrowed

    def test_positional_form_kind_still_works(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "kind"], capsys)
        assert rc == 0
        assert "KINDS" in out
        assert "OBSERVERS" not in out

    def test_positional_form_observer_still_works(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj", "observer"], capsys)
        assert rc == 0
        assert "OBSERVERS" in out
        assert "KINDS" not in out

    def test_unnarrowed_shows_all_sections(self, proj, capsys):
        rc, out, _ = _capture_run_ls(["proj"], capsys)
        assert rc == 0
        assert "KINDS" in out
        assert "OBSERVERS" in out
        assert "COMBINE" in out
        assert "SOURCES" in out

    def test_mixed_form_errors(self, proj, capsys):
        """Positional sub-verb plus any section flag → error with hint."""
        rc, _, err = _capture_run_ls(["proj", "kind", "--kind"], capsys)
        assert rc == 2
        assert "don't mix" in err
        assert "flag form is canonical" in err

    def test_mixed_form_different_sections_errors(self, proj, capsys):
        """Mixing positional `kind` with --observer is also a mix-form error."""
        rc, _, err = _capture_run_ls(["proj", "kind", "--observer"], capsys)
        assert rc == 2
        assert "don't mix" in err

    def test_unknown_name_renders_empty(self, proj, capsys):
        """Consistent with read: unknown kind name → empty section, rc=0."""
        rc, out, _ = _capture_run_ls(["proj", "--kind", "nonexistent"], capsys)
        assert rc == 0
        # Section header present with empty/zero count.
        assert "KINDS" in out
        assert "nonexistent" not in out


# ---------------------------------------------------------------------------
# Help output documents both forms (smoke test)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _peel_observer must not collide with ls's --observer section flag
# ---------------------------------------------------------------------------


class TestPeelObserverNonCollision:
    """The global identity peel only consumes `--observer VALUE`, never the
    bare flag — otherwise vertex-first `sl proj ls --observer` would lose
    the section selector to the identity machinery.
    """

    def test_bare_observer_left_in_place(self):
        from loops.cli.app import _peel_observer

        obs, rest = _peel_observer(["ls", "--observer"])
        # Default fallback observer is whatever resolve produces — but the
        # bare token must survive the peel.
        assert "--observer" in rest

    def test_observer_value_consumed(self):
        from loops.cli.app import _peel_observer

        obs, rest = _peel_observer(["emit", "decision", "--observer", "kyle"])
        assert obs == "kyle"
        assert "--observer" not in rest
        assert "kyle" not in rest

    def test_observer_equals_value_consumed(self):
        from loops.cli.app import _peel_observer

        obs, rest = _peel_observer(["emit", "decision", "--observer=kyle"])
        assert obs == "kyle"
        assert all("--observer" not in t for t in rest)

    def test_bare_observer_followed_by_flag(self):
        """`--observer --kind` — bare flag survives, --kind survives."""
        from loops.cli.app import _peel_observer

        obs, rest = _peel_observer(["ls", "--observer", "--kind"])
        assert "--observer" in rest
        assert "--kind" in rest


# ---------------------------------------------------------------------------
# End-to-end through cli.app.main — exercises the full dispatcher chain
# (including the vertex-first `_peel_observer` interaction). These cover
# the gap that let `sl proj ls --observer kyle` regress through
# isolated-unit tests.
# ---------------------------------------------------------------------------


def _capture_main(argv: list[str], capsys) -> tuple[int, str, str]:
    """Invoke cli.app.main with argv; return (rc, stdout, stderr)."""
    from loops.main import main

    rc = main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


class TestVertexFirstObserverFlag:
    """`--observer` on ls (vertex-first) must reach ls, not the identity peel.

    The bug fix is context-aware-at-call-site: `_vertex_first` peeks at the
    verb and skips the global observer-peel when the verb itself uses
    `--observer` as a section flag (currently just `ls`).
    """

    def test_vertex_first_ls_observer_name(self, proj, capsys):
        """sl proj ls --observer kyle → narrow OBSERVERS to kyle."""
        rc, out, _ = _capture_main(["proj", "ls", "--observer", "kyle"], capsys)
        assert rc == 0
        assert "OBSERVERS" in out
        assert "kyle" in out
        assert "alcove" not in out

    def test_vertex_first_ls_observer_equals(self, proj, capsys):
        """sl proj ls --observer=kyle → same as space-separated form."""
        rc, out, _ = _capture_main(["proj", "ls", "--observer=kyle"], capsys)
        assert rc == 0
        assert "OBSERVERS" in out
        assert "kyle" in out
        assert "alcove" not in out

    def test_vertex_first_ls_observer_bare(self, proj, capsys):
        """sl proj ls --observer → OBSERVERS section (bare flag)."""
        rc, out, _ = _capture_main(["proj", "ls", "--observer"], capsys)
        assert rc == 0
        assert "OBSERVERS" in out
        assert "kyle" in out
        assert "alcove" in out
        # OBSERVERS is the only visible section.
        assert "KINDS" not in out

    def test_verb_first_ls_observer_name(self, proj, capsys):
        """sl ls proj --observer kyle (verb-first) — same behaviour."""
        rc, out, _ = _capture_main(["ls", "proj", "--observer", "kyle"], capsys)
        assert rc == 0
        assert "kyle" in out
        assert "alcove" not in out

    def test_verb_first_ls_observer_equals(self, proj, capsys):
        """sl ls proj --observer=kyle (verb-first) — equals form."""
        rc, out, _ = _capture_main(["ls", "proj", "--observer=kyle"], capsys)
        assert rc == 0
        assert "kyle" in out
        assert "alcove" not in out


class TestEmitObserverOverrideRegression:
    """`--observer NAME` on emit must STILL behave as the identity override —
    we mustn't fix ls by breaking the path that was correct.
    """

    def test_emit_observer_space_form_overrides_identity(self, proj, capsys):
        """sl proj emit decision topic=x --observer kyle --dry-run → identity is kyle."""
        rc, out, _ = _capture_main(
            ["proj", "emit", "decision", "topic=x", "--observer", "kyle", "--dry-run"],
            capsys,
        )
        assert rc == 0
        # --dry-run emits the fact JSON to stdout (no store write).
        assert '"observer": "kyle"' in out
        assert '"kind": "decision"' in out

    def test_emit_observer_equals_form_overrides_identity(self, proj, capsys):
        """sl proj emit decision topic=x --observer=kyle --dry-run → identity is kyle."""
        rc, out, _ = _capture_main(
            ["proj", "emit", "decision", "topic=x", "--observer=kyle", "--dry-run"],
            capsys,
        )
        assert rc == 0
        assert '"observer": "kyle"' in out


class TestOpTokenValueAwareness:
    """Codex follow-up: when a value-taking global flag's value collides
    with a verb name, the op-token identifier must respect the value slot.

    Without value-awareness, ``sl proj --observer ls emit ...`` would
    mis-identify ``"ls"`` (the observer value) as the op and skip the
    identity peel — corrupting dispatch.
    """

    def test_observer_value_collides_with_verb_name(self, proj, capsys):
        """sl proj --observer ls emit ... → routes to emit, not ls.

        The observer value is "ls" (an unfortunate but legal identifier).
        Dispatch must identify ``emit`` as the op, peel ``--observer ls``
        as the global identity, and let emit run with observer="ls".
        Since S6 forgives undeclared observers, emit succeeds (dry-run, exit 0)
        and the WARN "Observer 'ls' not declared" proves the routing reached
        emit with observer="ls".
        """
        rc, _, err = _capture_main(
            ["proj", "--observer", "ls", "emit", "decision", "topic=t", "--dry-run"],
            capsys,
        )
        # Dispatch reached emit; emit forgave the undeclared "ls" observer and
        # WARNed. The wrong routing would have surfaced a different error (e.g.
        # ls-shape complaints) or rendered ls output.
        assert rc == 0
        assert "Observer 'ls' not declared" in err

    def test_observer_value_collides_equals_form(self, proj, capsys):
        """sl proj --observer=ls emit ... → equals form, same outcome."""
        rc, _, err = _capture_main(
            ["proj", "--observer=ls", "emit", "decision", "topic=t", "--dry-run"],
            capsys,
        )
        assert rc == 0
        assert "Observer 'ls' not declared" in err

    def test_global_observer_before_ls(self, proj, capsys):
        """sl proj --observer kyle ls → kyle is global identity; ls runs unnarrowed.

        The user's intent: kyle is the global identity override (this is
        the canonical position for global flags — BEFORE the op). The
        --observer kyle pair is peeled from before_op; ls receives no
        narrowing flags, so it renders the full vertex.
        """
        rc, out, _ = _capture_main(["proj", "--observer", "kyle", "ls"], capsys)
        assert rc == 0
        # All sections visible — no narrowing applied to ls.
        assert "KINDS" in out
        assert "OBSERVERS" in out

    def test_global_observer_then_ls_then_section_observer(self, proj, capsys):
        """sl proj --observer alice ls --observer kyle.

        Compound case: alice is global identity (peeled from before_op),
        kyle is the section-narrow on OBSERVERS (passed to ls).
        """
        rc, out, _ = _capture_main(
            ["proj", "--observer", "alice", "ls", "--observer", "kyle"], capsys,
        )
        assert rc == 0
        assert "OBSERVERS" in out
        assert "kyle" in out
        # alice was peeled globally; she doesn't appear in OBSERVERS output
        # (and isn't a declared observer anyway).
        assert "alcove" not in out

    def test_original_blocker_still_works(self, proj, capsys):
        """Regression guard: sl proj ls --observer kyle still narrows OBSERVERS.

        This is the bug af5abaa fixed — making sure the value-aware peek
        didn't accidentally break it.
        """
        rc, out, _ = _capture_main(["proj", "ls", "--observer", "kyle"], capsys)
        assert rc == 0
        assert "kyle" in out
        assert "alcove" not in out

    def test_identify_op_token_basic(self):
        """Direct test of the helper — basic verbs without value-taking flags."""
        from loops.cli.app import _identify_op_token

        op, before, after = _identify_op_token(["ls"])
        assert op == "ls"
        assert before == []
        assert after == ["ls"]

    def test_identify_op_token_skips_value_pair(self):
        """`--observer X` consumes X; op is the next non-flag token."""
        from loops.cli.app import _identify_op_token

        op, before, after = _identify_op_token(
            ["--observer", "ls", "emit", "decision"]
        )
        assert op == "emit"
        assert before == ["--observer", "ls"]
        assert after == ["emit", "decision"]

    def test_identify_op_token_skips_equals_form(self):
        """`--observer=X` is a single token; op is the next non-flag token."""
        from loops.cli.app import _identify_op_token

        op, before, after = _identify_op_token(
            ["--observer=ls", "emit", "decision"]
        )
        assert op == "emit"
        assert before == ["--observer=ls"]
        assert after == ["emit", "decision"]

    def test_identify_op_token_bare_global_flag(self):
        """Bare `--observer` (no following value) is a flag, not a value-pair."""
        from loops.cli.app import _identify_op_token

        op, before, after = _identify_op_token(["--observer", "--kind"])
        assert op is None  # no non-flag token at all
        assert before == ["--observer", "--kind"]
        assert after == []

    def test_identify_op_token_no_op(self):
        """Empty argv returns (None, [], [])."""
        from loops.cli.app import _identify_op_token

        op, before, after = _identify_op_token([])
        assert op is None
        assert before == []
        assert after == []


class TestVertexFirstMixedFormErrorThroughDispatcher:
    """The mixed-form error path also needs to fire through the dispatcher,
    not just `_run_ls` in isolation — the vertex-first wrapper rewrites
    argv (slash-encoding the qualifier), so the message must survive.
    """

    def test_mixed_form_error_through_dispatcher(self, proj, capsys):
        rc, _, err = _capture_main(["proj", "ls", "kind", "--kind"], capsys)
        assert rc == 2
        assert "don't mix" in err
        assert "flag form is canonical" in err


class TestHelpOutput:
    def test_top_level_help_mentions_both_forms(self, capsys):
        rc = _run_ls(["--help"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "--kind" in out
        assert "--observer" in out
        assert "--combine" in out
        assert "--row" in out
        assert "Positional alias" in out or "positional" in out.lower()

    def test_per_vertex_help_mentions_both_forms(self, proj, capsys):
        rc = _run_ls(["proj", "--help"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "--kind" in out
        assert "--observer" in out


# ---------------------------------------------------------------------------
# preview_fields surfaced through ls
# ---------------------------------------------------------------------------


class TestPreviewFieldsSurfaced:
    """preview_fields declared in spec appear in fetch_declarations and render."""

    @pytest.fixture
    def proj_with_preview(self, loops_home) -> Path:
        vdir = loops_home / "prev"
        vdir.mkdir(parents=True, exist_ok=True)
        vpath = vdir / "prev.vertex"
        vpath.write_text(
            'name "prev"\n'
            'store "./data/prev.db"\n'
            'loops {\n'
            '  decision {\n'
            '    fold { items "by" "topic" }\n'
            '    preview "message" "status"\n'
            '  }\n'
            '  thread {\n'
            '    fold { items "by" "name" }\n'
            '  }\n'
            '}\n'
        )
        return vpath

    def test_fetch_includes_preview_fields(self, proj_with_preview):
        data = fetch_declarations("prev", filters=["kind"])
        kinds = {k["name"]: k for k in data["kinds"]}
        assert kinds["decision"]["preview_fields"] == ("message", "status")
        assert kinds["thread"]["preview_fields"] == ()  # undeclared → empty

    def test_render_shows_preview_at_detailed(self, proj_with_preview):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("prev", filters=["kind"])
        text = block_text(declarations_view(data, Zoom.DETAILED, 80))
        assert "preview=message,status" in text

    def test_render_omits_preview_at_summary(self, proj_with_preview):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("prev", filters=["kind"])
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "preview=" not in text
