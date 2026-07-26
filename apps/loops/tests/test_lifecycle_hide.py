"""S5 — declarative entity lifecycle: the fold-view hide + validate scan.

Three tiers:

* ``TestHideSurface`` — the ``surface.hide_inactive`` transform in isolation
  (whitelist semantics, fail-open, hidden count, limited_by, depth/level scope,
  byte-identity when nothing hides).
* ``TestDispatchGate`` + ``TestAcceptanceWalk`` — the hide reaching the read
  path through ``_project_surface``: a REAL end-to-end deprecation walked in a
  scratch vertex (the live corpus holds zero inactive entities), asserting all
  eight binding observations (omission, provenance, footer, ``--all``,
  ``status=`` auto-disable, salience/edge retention, ``--refs`` reachability,
  ``--review`` canonical fullness) plus the validate warn.
* ``TestValidateScan`` — the folded-state active-targets-inactive +
  missing-status scan bolted onto ``loops validate`` (arbiter S5-F2).

Arbiter rulings S5-F1..F5 are the spec these lock.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace

import pytest

from atoms import FoldItem, FoldSection, FoldState
from loops.main import cmd_emit, main
from loops.surface import hide_inactive, project, to_dict

# Active whitelist reused across the surface-level cases.
_LC = ("status", ("open", "in-progress"))


def _task_state() -> FoldState:
    """A single lifecycle-declaring kind with one active, one inactive, and one
    missing-status entity — the minimal shape that exercises all three F1 arms."""
    task = FoldSection(
        kind="task",
        items=(
            FoldItem(payload={"name": "alpha", "status": "open"}, ts=1.0),
            FoldItem(payload={"name": "beta", "status": "done"}, ts=2.0),
            FoldItem(payload={"name": "gamma"}, ts=3.0),  # no status field
        ),
        fold_type="by",
        key_field="name",
        lifecycle=_LC,
    )
    return FoldState(sections=(task,), vertex="t")


# --- Tier 1: the transform in isolation ------------------------------------


class TestHideSurface:
    def test_hides_only_inactive(self):
        out = hide_inactive(project(_task_state()))
        keys = {r.key for r in out.rows}
        assert keys == {"alpha", "gamma"}  # beta (status=done) hidden

    def test_fail_open_missing_status_shown(self):
        # gamma lacks the status field entirely → makes no lifecycle claim →
        # SHOWN (arbiter S5-F1: absence of evidence is not evidence of absence).
        out = hide_inactive(project(_task_state()))
        assert any(r.key == "gamma" for r in out.rows)

    def test_window_records_hidden_and_limited_by(self):
        out = hide_inactive(project(_task_state()))
        assert out.window.hidden == 1
        assert out.window.shown == 2
        assert out.window.total == 3  # total is the pre-hide population
        assert out.window.limited_by == "status"

    def test_byte_identity_when_nothing_hidden(self):
        # No inactive entities → the transform returns the SAME surface object
        # (no Window churn), so a lifecycle-free read is untouched.
        active_only = FoldState(sections=(replace(
            _task_state().sections[0],
            items=(FoldItem(payload={"name": "alpha", "status": "open"}, ts=1.0),),
        ),), vertex="t")
        surf = project(active_only)
        assert hide_inactive(surf) is surf

    def test_non_lifecycle_kind_untouched(self):
        # A kind with no lifecycle declaration keeps every row regardless of a
        # status payload value.
        section = FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "x", "status": "done"}, ts=1.0),),
            fold_type="by", key_field="topic", lifecycle=None,
        )
        surf = project(FoldState(sections=(section,), vertex="t"))
        out = hide_inactive(surf)
        assert len(out.rows) == 1
        assert out.window.hidden == 0

    def test_skip_kinds_disables_per_kind(self):
        # The auto-disable hook: naming the kind keeps its inactive rows.
        out = hide_inactive(project(_task_state()), skip_kinds=frozenset({"task"}))
        assert {r.key for r in out.rows} == {"alpha", "beta", "gamma"}
        assert out.window.hidden == 0

    def test_walked_row_never_hidden(self):
        # depth>0 (a --refs walked row) is out of scope — an inactive node
        # explicitly walked-to stays reachable (edge-position invariant).
        surf = project(_task_state())
        rows = tuple(
            replace(r, depth=1) if r.key == "beta" else r for r in surf.rows
        )
        out = hide_inactive(replace(surf, rows=rows))
        assert any(r.key == "beta" for r in out.rows)
        assert out.window.hidden == 0

    def test_event_row_never_hidden(self):
        # level="fact" (an event/history row) makes no lifecycle claim.
        surf = project(_task_state())
        rows = tuple(
            replace(r, level="fact", axis="event") if r.key == "beta" else r
            for r in surf.rows
        )
        out = hide_inactive(replace(surf, rows=rows))
        assert any(r.key == "beta" for r in out.rows)

    def test_stronger_prior_cut_preserved(self):
        # If a limit already ran (limited_by set), the hide keeps that stronger
        # cut label but still records the hidden count.
        surf = project(_task_state())
        surf = replace(surf, window=replace(surf.window, limited_by="limit"))
        out = hide_inactive(surf)
        assert out.window.limited_by == "limit"
        assert out.window.hidden == 1

    def test_protect_spares_referenced_inactive(self):
        # The --refs edge-position hook: a protected address (ref-graph target)
        # keeps its inactive primary, while an unprotected inactive still hides.
        surf = project(_task_state())
        beta_addr = next(r.address for r in surf.rows if r.key == "beta")
        out = hide_inactive(surf, protect=frozenset({beta_addr}))
        assert {r.key for r in out.rows} == {"alpha", "beta", "gamma"}
        assert out.window.hidden == 0

    def test_json_window_and_schema_carry_lifecycle(self):
        d = to_dict(hide_inactive(project(_task_state())))
        assert d["window"]["hidden"] == 1
        assert d["window"]["limited_by"] == "status"
        assert d["schema"]["task"]["lifecycle"] == {
            "field": "status", "active": ["open", "in-progress"],
        }


# --- Acceptance vertex helpers ---------------------------------------------


def _write_accept_vertex(tmp_path):
    """A scratch vertex declaring lifecycle on `task`, plus a `decision` kind
    that references tasks — the substrate for a real deprecation walk."""
    vpath = tmp_path / "accept.vertex"
    vpath.write_text(
        'name "accept"\n'
        'store "./accept.db"\n'
        "\n"
        "loops {\n"
        "  task {\n"
        '    fold { items "by" "name" }\n'
        '    lifecycle "status" active="open,in-progress"\n'
        "  }\n"
        "  decision {\n"
        '    fold { items "by" "topic" }\n'
        "  }\n"
        "}\n"
    )
    return vpath


def _emit(vpath, kind, *, observer="kyle", **payload):
    parts = [f"{k}={v}" for k, v in payload.items()]
    ns = argparse.Namespace(
        vertex=None, kind=kind, parts=parts, observer=observer, dry_run=False,
    )
    return cmd_emit(ns, vertex_path=vpath)


def _seed_and_deprecate(vpath):
    """Emit the corpus, then walk `beta` terminal via ordinary re-emission.

    * task alpha (active)
    * task beta  (active), points at alpha → alpha's inbound depends on beta
    * decision plan, points at beta → a live reference to what we deprecate
    * task beta re-emitted status=done → beta is now INACTIVE (the transition)
    """
    assert _emit(vpath, "task", name="alpha", status="open") == 0
    assert _emit(vpath, "task", name="beta", status="open", ref="task:alpha") == 0
    assert _emit(vpath, "decision", topic="plan", message="uses beta",
                 ref="task:beta") == 0
    # The deprecation — an ORDINARY re-emission, not a retract tombstone.
    assert _emit(vpath, "task", name="beta", status="done") == 0


def _json_read(capsys, *argv):
    capsys.readouterr()
    rc = main(["read", *argv, "--json"])
    out = capsys.readouterr().out
    return rc, json.loads(out)


def _task_rows(surface):
    return {r["key"]: r for r in surface["rows"] if r["kind"] == "task"}


# --- Tier 2: the real deprecation walked end-to-end ------------------------


class TestAcceptanceWalk:
    """Each observation is an assertion, not a narration (brief acceptance 6)."""

    def test_1_default_view_omits_inactive(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath))
        tasks = _task_rows(s)
        assert "alpha" in tasks and "beta" not in tasks

    def test_2_window_discloses_the_cut(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath))
        assert s["window"]["hidden"] == 1
        assert s["window"]["limited_by"] == "status"
        assert s["window"]["shown"] == 2  # alpha + decision
        assert s["window"]["total"] == 3

    def test_3_footer_names_hidden_and_defeat(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        capsys.readouterr()
        rc = main(["read", str(vpath)])  # human TTY-ish text render
        out = capsys.readouterr().out
        assert rc == 0
        assert "1 inactive hidden" in out
        assert "--all" in out

    def test_4_all_defeats_the_hide(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath), "--all")
        tasks = _task_rows(s)
        assert "beta" in tasks
        assert s["window"]["hidden"] == 0
        assert s["window"]["limited_by"] is None

    def test_5_explicit_status_predicate_auto_disables(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        # Asking for status=done must SHOW the done task (per-kind auto-disable).
        _, s = _json_read(capsys, str(vpath), "status=done")
        tasks = _task_rows(s)
        assert "beta" in tasks
        assert s["window"]["hidden"] == 0

    def test_6_salience_and_inbound_retained_under_hide(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        # alpha's inbound edge comes FROM beta (inactive). Hiding beta must NOT
        # drop that contribution — salience is materialized pre-hide.
        _, hidden = _json_read(capsys, str(vpath))
        _, shown = _json_read(capsys, str(vpath), "--all")
        a_hidden = _task_rows(hidden)["alpha"]
        a_shown = _task_rows(shown)["alpha"]
        assert a_hidden["inbound"] == 1  # beta→alpha still counts
        assert a_hidden["inbound"] == a_shown["inbound"]
        assert a_hidden["salience"] == a_shown["salience"]
        assert a_hidden["tier"] == a_shown["tier"]

    def test_7_inactive_stays_reachable_under_refs(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        # The decision points at beta; under --refs the ref-graph target is
        # spared so the inactive node stays reachable (the walk dedups its
        # walked twin against the primary, so protecting the primary is what
        # keeps beta present). Default view still hides it (test_1).
        _, s = _json_read(capsys, str(vpath), "--refs", "1")
        beta = [
            r for r in s["rows"]
            if r["kind"] == "task" and r["key"] == "beta"
        ]
        assert beta, "inactive beta must remain reachable under --refs"
        # And an active read WITHOUT --refs hides it — the reachability is the
        # ref-graph mode's doing, not a blanket un-hide.
        _, plain = _json_read(capsys, str(vpath))
        assert not [
            r for r in plain["rows"]
            if r["kind"] == "task" and r["key"] == "beta"
        ]

    def test_event_axis_unchanged(self, tmp_path, capsys):
        # The raw event axis is never hidden. `--match` switches to level="fact"
        # rows, and the inactive entity's facts are fully searchable (the hide is
        # fold-view only). The store itself is never rewritten.
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath), "--match", "beta")
        found = {(r["kind"], r["key"]) for r in s["rows"] if r["level"] == "fact"}
        assert ("task", "beta") in found  # deprecated beta still searchable
        assert s["window"]["hidden"] == 0  # event axis carries no hide

    def test_facts_route_bypasses_hide(self, tmp_path, capsys):
        # ARBITER: `--facts` (event/lifecycle history) is a DIFFERENT read axis
        # than the current-state fold view, so it bypasses the hide entirely —
        # like --review. A corpus audit of terminal entities' transitions must
        # see them WITHOUT --all, or it silently under-counts. The PAIRING with
        # the default read below is the proof of the axis split.
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)

        # --facts (with --kind narrowing): terminal beta present + its FULL
        # transition history (open → done), and no hide applied.
        _, facts = _json_read(capsys, str(vpath), "--kind", "task", "--facts")
        assert facts["window"]["hidden"] == 0
        assert facts["window"]["limited_by"] is None
        task_keys = {r["key"] for r in facts["rows"] if r["level"] == "key"}
        assert "beta" in task_keys  # deprecated entity NOT hidden on facts route
        history = [f["status"] for f in facts["source_facts"]["task/beta"]]
        assert history == ["open", "done"]  # the full lifecycle transition

        # PAIRING: the default current-state fold view still hides beta.
        _, default = _json_read(capsys, str(vpath), "--kind", "task")
        assert "beta" not in {r["key"] for r in default["rows"] if r["level"] == "key"}
        assert default["window"]["hidden"] == 1

    def test_facts_route_json_and_text_both_unhidden(self, tmp_path, capsys):
        # Both encoders bypass identically on the facts route (no text/json skew).
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        capsys.readouterr()
        rc = main(["read", str(vpath), "--facts", "--plain"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "beta" in out                     # terminal entity present in text
        assert "inactive hidden" not in out       # no hide footer on facts route

    def test_key_filter_preserves_lifecycle_and_edges(self, tmp_path, capsys):
        # sol P2-b: fetch's --key branch rebuilt FoldSection field by field, so
        # every field added to the dataclass after that code was written got
        # dropped — first edge_fields, then lifecycle. Narrowing to the inactive
        # entity therefore UN-HID it: `--kind task --key beta` returned beta as
        # if it were active. The scoping flag must not change what the fold
        # claims about an entity's status.
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath), "--kind", "task", "--key", "beta")
        assert "beta" not in _task_rows(s)
        assert s["window"]["hidden"] == 1
        assert s["window"]["limited_by"] == "status"
        # The declaration survives the filter too — a blanked schema is the
        # same bug one field over.
        assert s["schema"]["task"]["lifecycle"] == {
            "field": "status", "active": ["open", "in-progress"],
        }

    def test_key_filter_still_narrows(self, tmp_path, capsys):
        # The filter itself is unaffected: --key alpha keeps alpha, drops the
        # sibling task, and --all still defeats the hide under a key filter.
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        _, s = _json_read(capsys, str(vpath), "--kind", "task", "--key", "alpha")
        assert set(_task_rows(s)) == {"alpha"}
        _, shown = _json_read(
            capsys, str(vpath), "--kind", "task", "--key", "beta", "--all",
        )
        assert "beta" in _task_rows(shown)

    def test_8_review_is_canonical_full_projection(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        capsys.readouterr()
        rc = main(["read", str(vpath), "--review"])
        out = capsys.readouterr().out
        assert rc == 0
        review = json.loads(out)["review"]
        facts = {(f["kind"], f["key"]) for f in review["facts"]}
        # The hide NEVER reaches --review: beta is present in the canonical cut.
        assert ("task", "beta") in facts
        assert ("task", "alpha") in facts


# --- Tier 3: the validate folded-state scan --------------------------------


class TestValidateScan:
    def _run_validate(self, capsys, *argv):
        from loops.commands.devtools import _run_validate
        capsys.readouterr()
        rc = _run_validate(list(argv))
        out = capsys.readouterr().out
        return rc, out

    def test_warns_active_targets_inactive(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        # The decision (visible, no lifecycle) points at beta (inactive task).
        rc, out = self._run_validate(capsys, "-vv", str(vpath))
        assert rc == 0  # WARN is non-fatal
        assert "active-targets-inactive" in out
        assert "decision:plan" in out
        assert "task:beta" in out

    def test_no_warn_when_source_itself_inactive(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        _seed_and_deprecate(vpath)
        # beta (inactive) points at alpha — beta is the SOURCE, so no warn for
        # that edge (a deprecated thing pointing outward is not the concern).
        rc, out = self._run_validate(capsys, "-vv", str(vpath))
        assert "task:beta → task:alpha" not in out

    def test_warns_missing_status(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        assert _emit(vpath, "task", name="alpha", status="open") == 0
        assert _emit(vpath, "task", name="ghost") == 0  # no status field
        rc, out = self._run_validate(capsys, "-vv", str(vpath))
        assert rc == 0
        assert "missing-status" in out
        assert "task:ghost" in out

    def test_clean_store_no_warns(self, tmp_path, capsys):
        vpath = _write_accept_vertex(tmp_path)
        assert _emit(vpath, "task", name="alpha", status="open") == 0
        assert _emit(vpath, "task", name="beta", status="in-progress") == 0
        rc, out = self._run_validate(capsys, "-vv", str(vpath))
        assert rc == 0
        assert "active-targets-inactive" not in out
        assert "missing-status" not in out

    def test_scan_skipped_for_non_lifecycle_vertex(self, tmp_path, capsys):
        # A vertex with no lifecycle declaration folds no store during validate.
        vpath = tmp_path / "plain.vertex"
        vpath.write_text(
            'name "plain"\nstore "./plain.db"\n'
            'loops {\n  note {\n    fold { items "by" "topic" }\n  }\n}\n'
        )
        rc, out = self._run_validate(capsys, str(vpath))
        assert rc == 0
        assert "⚠" not in out
