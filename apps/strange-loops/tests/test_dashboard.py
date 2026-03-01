"""Tests for the dashboard command."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from strange_loops.cli import main
from strange_loops.commands.dashboard import (
    DashboardState,
    DashboardSurface,
    ProjectSummary,
    TaskRow,
    _changes_summary,
    _fetch,
    _fetch_with_detail,
    _project_header,
    _relative_time,
    _render,
    _render_detail_pane_block,
    _render_fact_row_block,
    _render_header_block,
    _render_status_block,
    _render_tasks_pane_block,
    _status_style,
    _task_activity,
)


class TestStatusStyle:
    @pytest.fixture
    def palette(self):
        from painted.palette import current_palette

        return current_palette()

    def test_completed(self, palette):
        assert _status_style("completed", palette) is palette.success

    def test_merged(self, palette):
        assert _status_style("merged", palette) is palette.success

    def test_working(self, palette):
        assert _status_style("working", palette) is palette.warning

    def test_assigned(self, palette):
        assert _status_style("assigned", palette) is palette.warning

    def test_errored(self, palette):
        assert _status_style("errored", palette) is palette.error

    def test_created(self, palette):
        assert _status_style("created", palette) is palette.muted

    def test_closed(self, palette):
        assert _status_style("closed", palette) is palette.muted

    def test_unknown(self, palette):
        assert _status_style("unknown", palette) is palette.muted


class TestRelativeTime:
    def test_none(self):
        assert _relative_time(None) == ""

    def test_seconds(self):
        dt = datetime.now(timezone.utc) - timedelta(seconds=45)
        result = _relative_time(dt)
        assert result.endswith("s ago")

    def test_minutes(self):
        dt = datetime.now(timezone.utc) - timedelta(minutes=5, seconds=30)
        result = _relative_time(dt)
        assert result.endswith("m ago")

    def test_hours(self):
        dt = datetime.now(timezone.utc) - timedelta(hours=2, minutes=30)
        result = _relative_time(dt)
        assert result.endswith("h ago")

    def test_days(self):
        dt = datetime.now(timezone.utc) - timedelta(days=3, hours=12)
        result = _relative_time(dt)
        assert result.endswith("d ago")

    def test_future_returns_empty(self):
        dt = datetime.now(timezone.utc) + timedelta(hours=1)
        assert _relative_time(dt) == ""

    def test_naive_datetime(self):
        # Naive datetimes get treated as UTC
        dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
        result = _relative_time(dt)
        assert "ago" in result


class TestChangesSummary:
    def test_none_path(self):
        assert _changes_summary(None) == ""

    def test_missing_path(self, tmp_path):
        assert _changes_summary(str(tmp_path / "nonexistent")) == ""

    def test_parses_shortstat(self, tmp_path, monkeypatch):
        shortstat = " 3 files changed, 10 insertions(+), 5 deletions(-)\n"
        monkeypatch.setattr(
            "strange_loops.commands.dashboard.subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=shortstat, stderr=""),
        )
        assert _changes_summary(str(tmp_path)) == "+10 -5"

    def test_insertions_only(self, tmp_path, monkeypatch):
        shortstat = " 1 file changed, 7 insertions(+)\n"
        monkeypatch.setattr(
            "strange_loops.commands.dashboard.subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=shortstat, stderr=""),
        )
        assert _changes_summary(str(tmp_path)) == "+7"

    def test_deletions_only(self, tmp_path, monkeypatch):
        shortstat = " 2 files changed, 4 deletions(-)\n"
        monkeypatch.setattr(
            "strange_loops.commands.dashboard.subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout=shortstat, stderr=""),
        )
        assert _changes_summary(str(tmp_path)) == "-4"

    def test_no_changes(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "strange_loops.commands.dashboard.subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="", stderr=""),
        )
        assert _changes_summary(str(tmp_path)) == ""

    def test_subprocess_error(self, tmp_path, monkeypatch):
        def raise_error(*a, **kw):
            raise subprocess.SubprocessError("fail")

        monkeypatch.setattr("strange_loops.commands.dashboard.subprocess.run", raise_error)
        assert _changes_summary(str(tmp_path)) == ""


class TestTaskActivity:
    def test_finds_latest(self):
        facts = [
            {"kind": "task.created", "ts": 100.0, "payload": {"name": "t1"}},
            {"kind": "task.assigned", "ts": 200.0, "payload": {"name": "t1"}},
            {"kind": "task.stage", "ts": 300.0, "payload": {"name": "t1", "status": "working"}},
        ]
        result = _task_activity(facts, "t1")
        assert result == datetime.fromtimestamp(300.0, tz=timezone.utc)

    def test_filters_by_name(self):
        facts = [
            {"kind": "task.created", "ts": 100.0, "payload": {"name": "t1"}},
            {"kind": "task.created", "ts": 500.0, "payload": {"name": "t2"}},
        ]
        result = _task_activity(facts, "t1")
        assert result == datetime.fromtimestamp(100.0, tz=timezone.utc)

    def test_no_matching_facts(self):
        facts = [
            {"kind": "task.created", "ts": 100.0, "payload": {"name": "t2"}},
        ]
        assert _task_activity(facts, "t1") is None

    def test_empty_facts(self):
        assert _task_activity([], "t1") is None

    def test_datetime_ts(self):
        dt = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        facts = [{"kind": "task.created", "ts": dt, "payload": {"name": "t1"}}]
        assert _task_activity(facts, "t1") == dt


class TestProjectHeader:
    def test_all_kinds(self):
        summary = ProjectSummary(total=19, decisions=8, threads=5, plans=3)
        result = _project_header(summary)
        assert "19 facts" in result
        assert "8 decisions" in result
        assert "5 threads" in result
        assert "3 plans" in result
        assert result.startswith("Project")

    def test_facts_only(self):
        summary = ProjectSummary(total=5, decisions=0, threads=0, plans=0)
        result = _project_header(summary)
        assert "5 facts" in result
        assert "decisions" not in result

    def test_partial_kinds(self):
        summary = ProjectSummary(total=10, decisions=4, threads=0, plans=2)
        result = _project_header(summary)
        assert "4 decisions" in result
        assert "threads" not in result
        assert "2 plans" in result


class TestFetch:
    def test_returns_state(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--title", "First", "--base", "main"])

        state = _fetch()
        assert isinstance(state, DashboardState)
        assert len(state.tasks) == 1
        assert state.tasks[0].name == "t1"
        assert state.tasks[0].title == "First"
        assert state.tasks[0].status == "created"
        assert state.fact_total >= 1

    def test_errors_without_store(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        with pytest.raises(FileNotFoundError):
            _fetch()


class TestRender:
    def _make_state(self, **overrides):
        defaults = {
            "tasks": (
                TaskRow(name="t1", title="First task", status="created"),
                TaskRow(name="t2", title="Second task", status="working"),
            ),
            "project": None,
            "fact_total": 2,
        }
        defaults.update(overrides)
        return DashboardState(**defaults)

    def test_summary_contains_task_names(self):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            format=Format.PLAIN,
            is_tty=False,
            width=80,
            height=24,
        )
        state = self._make_state()
        block = _render(ctx, state)
        # Extract text from block rows
        text = "\n".join("".join(c.char for c in block.row(y)) for y in range(block.height))
        assert "t1" in text
        assert "t2" in text
        assert "created" in text
        assert "working" in text

    def test_minimal_one_liner(self):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        ctx = CliContext(
            zoom=Zoom.MINIMAL,
            mode=OutputMode.STATIC,
            format=Format.PLAIN,
            is_tty=False,
            width=80,
            height=24,
        )
        state = self._make_state()
        block = _render(ctx, state)
        text = "".join(c.char for c in block.row(0))
        assert "2 tasks" in text

    def test_project_header_in_output(self):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        ctx = CliContext(
            zoom=Zoom.SUMMARY,
            mode=OutputMode.STATIC,
            format=Format.PLAIN,
            is_tty=False,
            width=80,
            height=24,
        )
        state = self._make_state(
            project=ProjectSummary(total=10, decisions=3, threads=2, plans=1),
        )
        block = _render(ctx, state)
        text = "\n".join("".join(c.char for c in block.row(y)) for y in range(block.height))
        assert "Project" in text
        assert "10 facts" in text


class TestDashboardCLI:
    def test_shows_tasks(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "build-api", "--title", "Build the API", "--base", "main"])
        main(["task", "create", "fix-bug", "--title", "Fix login bug", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "build-api" in out
        assert "fix-bug" in out

    def test_shows_status(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "created" in out

    def test_shows_title(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--title", "My Task Title", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "My Task Title" in out

    def test_json_output(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--title", "Test Task", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "tasks" in data
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["name"] == "t1"
        assert "activity" in data["tasks"][0]

    def test_json_with_project(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--base", "main"])
        capsys.readouterr()

        summary = ProjectSummary(total=5, decisions=2, threads=1, plans=1)
        monkeypatch.setattr("strange_loops.commands.dashboard._project_summary", lambda: summary)

        rc = main(["dashboard", "--json"])
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["project"]["total"] == 5
        assert data["project"]["decisions"] == 2

    def test_errors_without_store(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        rc = main(["dashboard"])
        assert rc == 1
        # run_cli renders errors to stdout
        out = capsys.readouterr().out
        assert "No session initialized" in out

    def test_no_tasks(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        # Create store via session start, but no tasks
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No tasks" in out

    def test_project_header_renders(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--base", "main"])
        capsys.readouterr()

        summary = ProjectSummary(total=12, decisions=3, threads=2, plans=1)
        monkeypatch.setattr("strange_loops.commands.dashboard._project_summary", lambda: summary)

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Project" in out
        assert "12 facts" in out

    def test_activity_column(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard"])
        assert rc == 0
        out = capsys.readouterr().out
        # Task was just created, activity should show seconds ago
        assert "ago" in out

    def test_minimal_zoom(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["task", "create", "t1", "--base", "main"])
        capsys.readouterr()

        rc = main(["dashboard", "-q"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "1 tasks" in out
        assert "created" in out


# -- Interactive TUI tests --


def _block_text(block) -> str:
    """Extract all text from a Block."""
    return "\n".join("".join(c.char for c in block.row(y)) for y in range(block.height))


def _make_interactive_state(**overrides) -> DashboardState:
    """Build a DashboardState with interactive fields populated."""
    defaults = {
        "tasks": (
            TaskRow(name="api-server", title="Build API", status="working"),
            TaskRow(name="auth-fix", title="Fix auth", status="created"),
            TaskRow(name="ci-cleanup", title="CI cleanup", status="completed"),
        ),
        "project": ProjectSummary(total=47, decisions=3, threads=2, plans=1),
        "fact_total": 47,
        "session_active": True,
        "session_fact_count": 47,
        "detail_facts": (
            {
                "kind": "task.created",
                "ts": 1700000000.0,
                "payload": {"name": "api-server", "title": "Build API"},
                "observer": "claude",
            },
            {
                "kind": "task.assigned",
                "ts": 1700000060.0,
                "payload": {"name": "api-server", "harness": "sonnet"},
                "observer": "claude",
            },
        ),
        "last_fetched": time.monotonic(),
    }
    defaults.update(overrides)
    return DashboardState(**defaults)


class TestDashboardStateNewFields:
    def test_session_active_default(self):
        state = DashboardState(tasks=())
        assert state.session_active is False
        assert state.session_fact_count == 0
        assert state.detail_facts == ()
        assert state.last_fetched == 0.0

    def test_session_active_set(self):
        state = DashboardState(tasks=(), session_active=True, session_fact_count=10)
        assert state.session_active is True
        assert state.session_fact_count == 10

    def test_detail_facts(self):
        facts = ({"kind": "task.created", "ts": 100.0, "payload": {"name": "t1"}},)
        state = DashboardState(tasks=(), detail_facts=facts)
        assert len(state.detail_facts) == 1

    def test_backward_compatible(self):
        """Old callers creating DashboardState without new fields still work."""
        state = DashboardState(tasks=(), project=None, fact_total=5)
        assert state.fact_total == 5
        assert state.session_active is False


class TestFetchWithDetail:
    def test_returns_extended_state(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["task", "create", "t1", "--title", "First", "--base", "main"])

        state = _fetch_with_detail("t1")
        assert isinstance(state, DashboardState)
        assert len(state.tasks) == 1
        assert state.session_active is True
        assert state.session_fact_count >= 2
        assert len(state.detail_facts) >= 1
        assert state.last_fetched > 0

    def test_no_selected_task(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["task", "create", "t1", "--base", "main"])

        state = _fetch_with_detail(None)
        assert state.detail_facts == ()

    def test_session_ended(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["session", "end"])

        state = _fetch_with_detail(None)
        assert state.session_active is False


class TestRenderHeader:
    def test_contains_session_label(self):
        state = _make_interactive_state(session_active=True)
        block = _render_header_block(state, 120)
        text = _block_text(block)
        assert "session: active" in text

    def test_session_ended(self):
        state = _make_interactive_state(session_active=False)
        block = _render_header_block(state, 120)
        text = _block_text(block)
        assert "session: ended" in text

    def test_fact_count(self):
        state = _make_interactive_state(session_fact_count=47)
        block = _render_header_block(state, 120)
        text = _block_text(block)
        assert "47 facts" in text

    def test_key_hints(self):
        state = _make_interactive_state()
        block = _render_header_block(state, 120)
        text = _block_text(block)
        assert "j/k select" in text
        assert "q quit" in text


class TestRenderTasksPane:
    def test_shows_task_names(self):
        state = _make_interactive_state()
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 64, 20)
        text = _block_text(block)
        assert "api-server" in text
        assert "auth-fix" in text

    def test_shows_statuses(self):
        state = _make_interactive_state()
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 64, 20)
        text = _block_text(block)
        assert "working" in text
        assert "created" in text

    def test_shows_titles(self):
        state = _make_interactive_state()
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 64, 20)
        text = _block_text(block)
        assert "Build API" in text
        assert "Fix auth" in text

    def test_task_count_in_header(self):
        state = _make_interactive_state()
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 64, 20)
        text = _block_text(block)
        assert "Tasks (3)" in text

    def test_empty_tasks(self):
        state = _make_interactive_state(tasks=())
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 64, 20)
        text = _block_text(block)
        assert "Tasks (0)" in text

    def test_narrow_drops_columns(self):
        state = _make_interactive_state()
        # At width 40, changes column should be dropped
        block = _render_tasks_pane_block(state, 0, 0, "tasks", 40, 20)
        text = _block_text(block)
        # Task names and statuses should still be present
        assert "api-server" in text


class TestRenderDetailPane:
    def test_shows_task_header(self):
        state = _make_interactive_state()
        block = _render_detail_pane_block(state, 0, 0, "detail", 60, 20)
        text = _block_text(block)
        assert "api-server" in text
        assert "working" in text

    def test_shows_facts(self):
        state = _make_interactive_state()
        block = _render_detail_pane_block(state, 0, 0, "detail", 60, 20)
        text = _block_text(block)
        assert "task.created" in text
        assert "task.assigned" in text

    def test_no_tasks(self):
        state = _make_interactive_state(tasks=())
        block = _render_detail_pane_block(state, 0, 0, "detail", 60, 20)
        text = _block_text(block)
        assert "No task selected" in text

    def test_scroll_clamp(self):
        state = _make_interactive_state()
        # Scroll beyond available facts — should not crash
        block = _render_detail_pane_block(state, 0, 999, "detail", 60, 20)
        text = _block_text(block)
        # Should still show something (clamped)
        assert "api-server" in text


class TestRenderFactRow:
    def test_format(self):
        fact = {
            "kind": "task.created",
            "ts": 1700000000.0,
            "payload": {"name": "t1", "title": "Test"},
        }
        block = _render_fact_row_block(fact, 80)
        text = _block_text(block)
        assert "[task.created]" in text
        assert "name=t1" in text

    def test_datetime_ts(self):
        dt = datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        fact = {"kind": "session.start", "ts": dt, "payload": {}}
        block = _render_fact_row_block(fact, 80)
        text = _block_text(block)
        assert "14:30" in text

    def test_truncation(self):
        fact = {
            "kind": "worker.output",
            "ts": 1700000000.0,
            "payload": {"output": "x" * 200},
        }
        block = _render_fact_row_block(fact, 40)
        text = _block_text(block)
        assert len(text.rstrip()) <= 40


class TestRenderStatusBar:
    def test_project_summary(self):
        state = _make_interactive_state()
        block = _render_status_block(state, 120)
        text = _block_text(block)
        assert "Project" in text
        assert "47 facts" in text

    def test_no_project(self):
        state = _make_interactive_state(project=None)
        block = _render_status_block(state, 120)
        text = _block_text(block)
        assert "No project store" in text

    def test_updated_ago(self):
        state = _make_interactive_state(last_fetched=time.monotonic())
        block = _render_status_block(state, 120)
        text = _block_text(block)
        assert "updated 0s ago" in text


class TestDashboardSurfaceState:
    def test_construction(self, workspace: Path, monkeypatch):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["task", "create", "t1", "--base", "main"])

        ctx = CliContext(
            zoom=Zoom.DETAILED,
            mode=OutputMode.INTERACTIVE,
            format=Format.ANSI,
            is_tty=True,
            width=120,
            height=30,
        )
        surface = DashboardSurface(ctx)
        assert surface._selected == 0
        assert surface._focus == "tasks"
        assert surface._task_scroll == 0
        assert surface._detail_scroll == 0
        assert len(surface._state.tasks) == 1

    def test_selected_name(self, workspace: Path, monkeypatch):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["task", "create", "t1", "--base", "main"])
        main(["task", "create", "t2", "--base", "main"])

        ctx = CliContext(
            zoom=Zoom.DETAILED,
            mode=OutputMode.INTERACTIVE,
            format=Format.ANSI,
            is_tty=True,
            width=120,
            height=30,
        )
        surface = DashboardSurface(ctx)
        assert surface._selected_name() == "t1"
        surface._selected = 1
        assert surface._selected_name() == "t2"

    def test_selected_name_empty(self, workspace: Path, monkeypatch):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        monkeypatch.chdir(workspace)
        main(["session", "start"])

        ctx = CliContext(
            zoom=Zoom.DETAILED,
            mode=OutputMode.INTERACTIVE,
            format=Format.ANSI,
            is_tty=True,
            width=120,
            height=30,
        )
        surface = DashboardSurface(ctx)
        assert surface._selected_name() is None

    def test_move_selection_clamps(self, workspace: Path, monkeypatch):
        from painted import CliContext, Zoom
        from painted.fidelity import Format, OutputMode

        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["task", "create", "t1", "--base", "main"])
        main(["task", "create", "t2", "--base", "main"])

        ctx = CliContext(
            zoom=Zoom.DETAILED,
            mode=OutputMode.INTERACTIVE,
            format=Format.ANSI,
            is_tty=True,
            width=120,
            height=30,
        )
        surface = DashboardSurface(ctx)
        surface._main_h = 20  # simulate layout
        surface._move_selection(-1)  # already at 0
        assert surface._selected == 0
        surface._move_selection(1)
        assert surface._selected == 1
        surface._move_selection(1)  # at end
        assert surface._selected == 1  # clamped
        surface._move_selection(1)  # still clamped
        assert surface._selected == 1
