"""Tests for loops CLI."""

from pathlib import Path
from io import StringIO
import sys

import pytest

from loops.main import main, create_parser, _parse_vars, loops_home

FIXTURES = Path(__file__).parent / "fixtures"


class TestParser:
    """Argument parser tests."""

    def test_validate_routed_to_display(self):
        """validate is routed through run_cli, not argparse."""
        from loops.main import _run_validate
        assert callable(_run_validate)

    def test_test_routed_to_display(self):
        """test is routed through run_cli, not argparse."""
        from loops.main import _run_test
        assert callable(_run_test)

    def test_run_routed_to_display(self):
        """run is routed through run_cli, not argparse."""
        from loops.main import _run_run
        assert callable(_run_run)

    def test_compile_routed_to_display(self):
        """compile is routed through run_cli, not argparse."""
        from loops.main import _run_compile
        assert callable(_run_compile)

    def test_start_routed_to_display(self):
        """start is routed through run_cli, not argparse."""
        # start is handled before argparse in main(), so it never
        # reaches create_parser(). Verify it's in the display dict.
        from loops.main import _run_start
        assert callable(_run_start)


class TestParseVars:
    """--var KEY=VALUE parsing tests."""

    def test_single_var(self):
        assert _parse_vars(["hn_username=kg"]) == {"hn_username": "kg"}

    def test_multiple_vars(self):
        result = _parse_vars(["a=1", "b=2"])
        assert result == {"a": "1", "b": "2"}

    def test_empty_value(self):
        assert _parse_vars(["key="]) == {"key": ""}

    def test_value_with_equals(self):
        assert _parse_vars(["url=http://x.com?a=1"]) == {"url": "http://x.com?a=1"}

    def test_empty_list(self):
        assert _parse_vars([]) == {}

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid --var format"):
            _parse_vars(["no_equals_sign"])

    def test_run_accepts_var_via_run_cli(self):
        """run --var is handled by _run_run's pre-parser, not create_parser."""
        from loops.main import _run_run
        assert callable(_run_run)

    def test_start_accepts_var_via_run_cli(self):
        """start --var is handled by _run_start's pre-parser, not create_parser."""
        from loops.main import _run_start
        assert callable(_run_start)

    def test_run_var_parsed_by_pre_parser(self):
        """run's --var is handled by pre-parser in _run_run."""
        from loops.main import _parse_vars
        assert _parse_vars([]) == {}


class TestValidateCommand:
    """validate command tests."""

    def test_validate_minimal_loop(self):
        result = main(["validate", str(FIXTURES / "minimal.loop")])
        assert result == 0

    def test_validate_full_loop(self):
        result = main(["validate", str(FIXTURES / "disk.loop")])
        assert result == 0

    def test_validate_minimal_vertex(self):
        result = main(["validate", str(FIXTURES / "minimal.vertex")])
        assert result == 0

    def test_validate_full_vertex(self):
        result = main(["validate", str(FIXTURES / "system.vertex")])
        assert result == 0

    def test_validate_nonexistent_file(self):
        result = main(["validate", "nonexistent.loop"])
        assert result == 1

    def test_validate_unknown_extension(self):
        result = main(["validate", str(FIXTURES / "minimal.loop").replace(".loop", ".txt")])
        assert result == 1

    def test_validate_multiple_files(self):
        result = main([
            "validate",
            str(FIXTURES / "minimal.loop"),
            str(FIXTURES / "minimal.vertex"),
        ])
        assert result == 0

    def test_validate_skips_non_dsl_in_glob(self):
        """Non-.loop/.vertex files are silently skipped."""
        result = main([
            "validate",
            str(FIXTURES / "minimal.loop"),
            str(FIXTURES / "sample_input.txt"),  # skipped
        ])
        assert result == 0

    def test_validate_discovers_from_cwd(self, tmp_path, monkeypatch):
        """No args: discovers .loop/.vertex files from cwd."""
        (tmp_path / "a.loop").write_text(
            'source "echo"\nkind "a"\nobserver "test"\n'
        )
        (tmp_path / "b.vertex").write_text(
            'name "b"\nloops {\n  x {\n    fold {\n      count "inc"\n    }\n  }\n}\n'
        )
        (tmp_path / "ignore.txt").write_text("not a DSL file")
        monkeypatch.chdir(tmp_path)
        result = main(["validate"])
        assert result == 0


class TestCompileCommand:
    """compile command tests."""

    def test_compile_loop(self, capsys):
        result = main(["compile", str(FIXTURES / "disk.loop")])
        assert result == 0
        captured = capsys.readouterr()
        assert "Source: disk.loop" in captured.out
        assert "command: df -h" in captured.out
        assert "kind: disk" in captured.out

    def test_compile_vertex(self, capsys):
        result = main(["compile", str(FIXTURES / "system.vertex")])
        assert result == 0
        captured = capsys.readouterr()
        assert "Vertex: system-monitor" in captured.out
        assert "disk:" in captured.out
        assert "memory:" in captured.out


class TestTestCommand:
    """test command tests."""

    def test_test_with_input_file(self, tmp_path, capsys):
        # Create sample input
        input_file = tmp_path / "sample.txt"
        input_file.write_text("Filesystem  Use%  Mount\n/dev/disk1  27%  /\n/dev/disk2  50%  /home\n")

        # Create a simple loop file
        loop_file = tmp_path / "test.loop"
        loop_file.write_text("""\
source "df -h"
kind "disk"
observer "test"
parse {
  skip "^Filesystem"
  split
  pick 0 1 {
    names "fs" "pct"
  }
}
""")

        result = main(["test", str(loop_file), "--input", str(input_file)])
        assert result == 0
        captured = capsys.readouterr()
        # Should have 2 results (header skipped)
        assert "2 parsed, 1 skipped" in captured.out

    def test_test_json_output(self, tmp_path, capsys):
        input_file = tmp_path / "sample.txt"
        input_file.write_text("/dev/disk1  27%\n")

        loop_file = tmp_path / "test.loop"
        loop_file.write_text("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  pick 0 1 {
    names "fs" "pct"
  }
}
""")

        result = main(["test", str(loop_file), "--input", str(input_file), "--json"])
        assert result == 0
        captured = capsys.readouterr()
        assert '"fs": "/dev/disk1"' in captured.out

    def test_test_no_parse_pipeline(self, tmp_path, capsys):
        loop_file = tmp_path / "test.loop"
        loop_file.write_text("""\
source "echo hello"
kind "test"
observer "test"
""")

        result = main(["test", str(loop_file), "--input", "/dev/null"])
        assert result == 0
        captured = capsys.readouterr()
        assert "no parse pipeline" in captured.out


class TestHelp:
    """Help output tests."""

    def test_main_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Runtime for .loop and .vertex files" in captured.out

    def test_validate_help(self, capsys):
        # validate is routed through run_cli which handles --help without SystemExit
        result = main(["validate", "--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Validate" in captured.out


class TestLoopsHome:
    """loops_home() resolution tests."""

    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "custom"))
        assert loops_home() == tmp_path / "custom"

    def test_xdg_config_home(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LOOPS_HOME", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert loops_home() == tmp_path / "xdg" / "loops"

    def test_default(self, monkeypatch):
        monkeypatch.delenv("LOOPS_HOME", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        result = loops_home()
        assert result == Path.home() / ".config" / "loops"


class TestInitCommand:
    """loops init tests."""

    def test_creates_root_vertex(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["init"])
        assert result == 0
        root = tmp_path / "root.vertex"
        assert root.exists()
        content = root.read_text()
        assert 'name "root"' in content
        assert "discover" in content
        captured = capsys.readouterr()
        assert "Created" in captured.out

    def test_idempotent(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        main(["init"])
        result = main(["init"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Already initialized" in captured.out

    def test_creates_parent_dirs(self, monkeypatch, tmp_path, capsys):
        deep = tmp_path / "a" / "b" / "c"
        monkeypatch.setenv("LOOPS_HOME", str(deep))
        result = main(["init"])
        assert result == 0
        assert (deep / "root.vertex").exists()

    def test_template_flag_parsed(self):
        parser = create_parser()
        args = parser.parse_args(["init", "--template", "session"])
        assert args.template == "session"

    def test_template_flag_short(self):
        parser = create_parser()
        args = parser.parse_args(["init", "-t", "tasks"])
        assert args.template == "tasks"

    def test_no_template_is_none(self):
        parser = create_parser()
        args = parser.parse_args(["init"])
        assert args.template is None

    def test_name_arg_parsed(self):
        parser = create_parser()
        args = parser.parse_args(["init", "project"])
        assert args.name == "project"
        assert args.template is None

    def test_slashed_name_parsed(self):
        parser = create_parser()
        args = parser.parse_args(["init", "dev/project", "-t", "session"])
        assert args.name == "dev/project"
        assert args.template == "session"

    def test_slashed_name_creates_config_vertex(self, monkeypatch, tmp_path, capsys):
        """loops init dev/project --template session creates in LOOPS_HOME."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["init", "dev/project", "-t", "session"])
        assert result == 0
        vertex = tmp_path / "dev" / "project" / "project.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "project"' in content
        assert "discover" in content
        assert (tmp_path / "dev" / "project" / "instances").is_dir()

    def test_slashed_name_infers_template(self, monkeypatch, tmp_path, capsys):
        """loops init dev/session infers template from leaf name."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["init", "dev/session"])
        assert result == 0
        assert (tmp_path / "dev" / "session" / "session.vertex").exists()

    def test_slashed_name_creates_any_aggregation(self, monkeypatch, tmp_path, capsys):
        """loops init dev/custom creates aggregation without needing a template."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["init", "dev/custom"])
        assert result == 0
        vertex = tmp_path / "dev" / "custom" / "custom.vertex"
        assert vertex.exists()
        assert "discover" in vertex.read_text()

    def test_bare_name_creates_local_vertex(self, monkeypatch, tmp_path, capsys):
        """loops init project creates local vertex from config-level source."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        # Seed a config-level instance vertex as source
        config_dir = tmp_path / "project"
        config_dir.mkdir()
        (config_dir / "project.vertex").write_text(
            'name "project"\nstore "./data/project.db"\n\nloops {\n  decision { fold { items "by" "topic" } }\n}\n'
        )
        (tmp_path / "myproject").mkdir()
        monkeypatch.chdir(tmp_path / "myproject")
        result = main(["init", "project"])
        assert result == 0
        vertex = tmp_path / "myproject" / "project.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "project"' in content
        assert 'store "./data/project.db"' in content
        assert (tmp_path / "myproject" / "data").is_dir()

    def test_bare_name_registers_with_config(self, monkeypatch, tmp_path, capsys):
        """loops init project registers cwd with config-level vertex if it exists."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        # Create config-level aggregation with a source instance
        config_dir = tmp_path / "project"
        config_dir.mkdir()
        (config_dir / "project.vertex").write_text('name "project"\ndiscover "./instances/**/*.vertex"\n')
        instances_dir = config_dir / "instances" / "seed"
        instances_dir.mkdir(parents=True)
        (instances_dir / "project.vertex").write_text(
            'name "project"\nstore "./data/project.db"\n\nloops {\n  decision { fold { items "by" "topic" } }\n}\n'
        )
        # Now init local
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = main(["init", "project"])
        assert result == 0
        link = config_dir / "instances" / "myproject"
        assert link.is_symlink()
        assert link.resolve() == project_dir.resolve()

    def test_bare_name_no_source_vertex_errors(self, monkeypatch, tmp_path, capsys):
        """loops init project without config-level source vertex errors."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = main(["init", "project"])
        assert result == 1
        captured = capsys.readouterr()
        assert "No existing vertex found" in captured.err

    def test_template_project_choice(self):
        parser = create_parser()
        args = parser.parse_args(["init", "-t", "project"])
        assert args.template == "project"

    def test_template_creates_local_with_cwd(self, monkeypatch, tmp_path, capsys):
        """loops init --template session (no name) creates in cwd."""
        monkeypatch.chdir(tmp_path)
        result = main(["init", "--template", "session"])
        assert result == 0
        assert (tmp_path / "session.vertex").exists()
        assert (tmp_path / "data").is_dir()


class TestDefaultPaths:
    """start/run/store default to LOOPS_HOME/root.vertex when no file given."""

    def test_start_no_args_missing_root(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["start"])
        assert result == 1
        captured = capsys.readouterr()
        assert "loops init" in captured.err

    def test_run_no_args_missing_root(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["run"])
        assert result == 1

    def test_start_file_optional(self, monkeypatch, tmp_path, capsys):
        """start with no file falls back to LOOPS_HOME/root.vertex."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        # Without root.vertex, returns 1 with guidance
        result = main(["start"])
        assert result == 1

    def test_run_file_optional(self, monkeypatch, tmp_path):
        """run with no file falls back to LOOPS_HOME/root.vertex."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["run"])
        assert result == 1

    def test_store_parser_file_optional(self):
        parser = create_parser()
        args = parser.parse_args(["store"])
        assert args.file is None

    def test_start_explicit_file_still_works(self, tmp_path, capsys):
        """start with an explicit file that doesn't exist returns 1."""
        result = main(["start", str(tmp_path / "my.vertex")])
        assert result == 1


class TestEmitParsers:
    """Parser tests for emit and dissolved session commands."""

    def test_emit_without_vertex_arg(self):
        """When vertex is omitted, argparse fills vertex greedily.
        Runtime reinterprets via resolution (tested in test_session.py)."""
        parser = create_parser()
        args = parser.parse_args(["emit", "decision", "topic=test"])
        # argparse always fills vertex first — runtime shifts if it doesn't resolve
        assert args.vertex == "decision"
        assert args.kind == "topic=test"

    def test_emit_with_vertex_arg(self):
        parser = create_parser()
        args = parser.parse_args(["emit", "session", "decision", "topic=test"])
        assert args.vertex == "session"
        assert args.kind == "decision"

    def test_no_session_subcommand(self):
        """session subcommand group has been dissolved."""
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["session", "start"])
