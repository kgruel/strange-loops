"""Tests for AppRunner: app-level command routing through painted."""

import json

import pytest

from painted.app_runner import AppCommand, AppRunner, run_app
from painted.fidelity import HelpData, Zoom


class TestAppCommand:
    """AppCommand is a frozen dataclass."""

    def test_frozen(self):
        cmd = AppCommand("test", "A test", lambda argv: 0)
        with pytest.raises(AttributeError):
            cmd.name = "other"  # type: ignore[misc]

    def test_fields(self):
        handler = lambda argv: 42
        cmd = AppCommand("status", "Show status", handler)
        assert cmd.name == "status"
        assert cmd.description == "Show status"
        assert cmd.handler is handler


class TestAppRunner:
    """AppRunner dispatches commands and renders help."""

    def _make_runner(self, **kwargs):
        commands = kwargs.pop(
            "commands",
            [
                AppCommand("status", "Show status", lambda argv: 0),
                AppCommand("log", "Show log", lambda argv: 0),
            ],
        )
        return AppRunner(
            commands=tuple(commands),
            prog=kwargs.get("prog", "test"),
            description=kwargs.get("description", "A test app"),
        )

    def test_dispatch_to_command(self):
        called_with = []

        def handler(argv):
            called_with.append(argv)
            return 0

        runner = AppRunner(
            commands=(AppCommand("go", "Do it", handler),),
            prog="test",
        )
        rc = runner.run(["go", "arg1", "arg2"])
        assert rc == 0
        assert called_with == [["arg1", "arg2"]]

    def test_exit_code_propagation(self):
        runner = AppRunner(
            commands=(AppCommand("fail", "Fail", lambda argv: 42),),
        )
        assert runner.run(["fail"]) == 42

    def test_no_args_shows_help(self, capsys):
        runner = self._make_runner()
        rc = runner.run([])
        assert rc == 0
        captured = capsys.readouterr()
        assert "status" in captured.out
        assert "log" in captured.out

    def test_help_flag(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["--help"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "status" in captured.out

    def test_help_short_flag(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["-h"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "status" in captured.out

    def test_unknown_command(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["bogus"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "Unknown command: bogus" in captured.err

    def test_help_json(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["--help", "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["prog"] == "test"

    def test_help_plain(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["--help", "--plain"])
        assert rc == 0
        captured = capsys.readouterr()
        # Plain output should not have ANSI codes
        assert "\033[" not in captured.out

    def test_help_verbose(self, capsys):
        runner = self._make_runner()
        rc = runner.run(["--help", "-v"])
        assert rc == 0
        captured = capsys.readouterr()
        # Verbose (DETAILED) should show group detail text
        assert "Controls how much detail" in captured.out
        assert "Add -v for more detail" in captured.out

    def test_help_shows_description(self, capsys):
        runner = self._make_runner(description="My great app")
        rc = runner.run(["--help", "--plain"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "My great app" in captured.out

    def test_help_shows_prog(self, capsys):
        runner = self._make_runner(prog="myapp")
        rc = runner.run(["--help", "--plain"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "myapp" in captured.out


class TestBuildHelpData:
    """_build_help_data produces correct HelpData."""

    def test_commands_group_primary(self):
        runner = AppRunner(
            commands=(
                AppCommand("a", "Do A", lambda argv: 0),
                AppCommand("b", "Do B", lambda argv: 0),
            ),
        )
        data = runner._build_help_data()
        assert isinstance(data, HelpData)
        # Commands (primary) + Zoom + Format + Help (secondary)
        assert len(data.groups) == 4
        commands_group = data.groups[0]
        assert commands_group.name == "Commands"
        assert not commands_group.secondary
        assert len(commands_group.flags) == 2
        assert commands_group.flags[0].long == "a"
        assert commands_group.flags[1].long == "b"

    def test_secondary_groups(self):
        runner = AppRunner(
            commands=(AppCommand("a", "Do A", lambda argv: 0),),
        )
        data = runner._build_help_data()
        secondary = [g for g in data.groups if g.secondary]
        names = [g.name for g in secondary]
        assert "Zoom" in names
        assert "Format" in names
        assert "Help" in names
        assert all(g.secondary for g in secondary)

    def test_no_interaction_rules(self, capsys):
        """AppRunner help should not show interaction rules even at DETAILED."""
        runner = AppRunner(
            commands=(AppCommand("a", "Do A", lambda argv: 0),),
            prog="test",
        )
        rc = runner.run(["--help", "-v", "--plain"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Interaction rules" not in captured.out


class TestRunApp:
    """Convenience function run_app."""

    def test_basic(self):
        called = []
        commands = [AppCommand("go", "Go", lambda argv: (called.append(1), 0)[1])]
        rc = run_app(["go"], commands, prog="test")
        assert rc == 0
        assert called == [1]

    def test_help(self, capsys):
        commands = [AppCommand("go", "Go", lambda argv: 0)]
        rc = run_app(["--help", "--plain"], commands, prog="test")
        assert rc == 0
        captured = capsys.readouterr()
        assert "go" in captured.out

    def test_accepts_list_or_tuple(self):
        commands = [AppCommand("go", "Go", lambda argv: 0)]
        assert run_app(["go"], commands) == 0
        assert run_app(["go"], tuple(commands)) == 0


class TestNesting:
    """Composed AppRunners for nested dispatch."""

    def test_nested_dispatch(self):
        inner_called = []

        inner = AppRunner(
            commands=(
                AppCommand(
                    "start", "Start session", lambda argv: (inner_called.append(argv), 0)[1]
                ),
                AppCommand("stop", "Stop session", lambda argv: 1),
            ),
            prog="myapp session",
        )

        outer = AppRunner(
            commands=(
                AppCommand("status", "Show status", lambda argv: 0),
                AppCommand("session", "Session commands", inner.run),
            ),
            prog="myapp",
        )

        rc = outer.run(["session", "start", "foo"])
        assert rc == 0
        assert inner_called == [["foo"]]

    def test_nested_help(self, capsys):
        inner = AppRunner(
            commands=(AppCommand("start", "Start session", lambda argv: 0),),
            prog="myapp session",
            description="Session management",
        )
        outer = AppRunner(
            commands=(AppCommand("session", "Session commands", inner.run),),
            prog="myapp",
        )

        # Outer help
        rc = outer.run(["--help", "--plain"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "session" in captured.out

        # Inner help
        rc = outer.run(["session"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "start" in captured.out

    def test_nested_unknown(self, capsys):
        inner = AppRunner(
            commands=(AppCommand("start", "Start", lambda argv: 0),),
            prog="myapp session",
        )
        outer = AppRunner(
            commands=(AppCommand("session", "Session", inner.run),),
            prog="myapp",
        )
        rc = outer.run(["session", "bogus"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "Unknown command: bogus" in captured.err
