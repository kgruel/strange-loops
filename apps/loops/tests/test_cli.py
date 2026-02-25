"""Tests for loops CLI."""

from pathlib import Path
from io import StringIO
import sys

import pytest

from loops.main import main, create_parser, _parse_vars, loops_home

FIXTURES = Path(__file__).parent / "fixtures"


class TestParser:
    """Argument parser tests."""

    def test_validate_command(self):
        parser = create_parser()
        args = parser.parse_args(["validate", "test.loop"])
        assert args.command == "validate"
        assert args.files == ["test.loop"]

    def test_validate_multiple_files(self):
        parser = create_parser()
        args = parser.parse_args(["validate", "a.loop", "b.vertex", "c.loop"])
        assert args.files == ["a.loop", "b.vertex", "c.loop"]

    def test_test_command(self):
        parser = create_parser()
        args = parser.parse_args(["test", "test.loop", "--input", "sample.txt"])
        assert args.command == "test"
        assert args.file == "test.loop"
        assert args.input == "sample.txt"

    def test_test_command_json(self):
        parser = create_parser()
        args = parser.parse_args(["test", "test.loop", "-j"])
        assert args.json is True

    def test_run_command(self):
        parser = create_parser()
        args = parser.parse_args(["run", "test.loop", "--limit", "10"])
        assert args.command == "run"
        assert args.limit == 10

    def test_compile_command(self):
        parser = create_parser()
        args = parser.parse_args(["compile", "test.vertex"])
        assert args.command == "compile"
        assert args.file == "test.vertex"

    def test_start_command(self):
        parser = create_parser()
        args = parser.parse_args(["start", "system.vertex"])
        assert args.command == "start"
        assert args.file == "system.vertex"


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

    def test_run_parser_accepts_var(self):
        parser = create_parser()
        args = parser.parse_args(["run", "test.vertex", "--var", "a=1", "--var", "b=2"])
        assert args.var == ["a=1", "b=2"]

    def test_start_parser_accepts_var(self):
        parser = create_parser()
        args = parser.parse_args(["start", "test.vertex", "--var", "x=y"])
        assert args.var == ["x=y"]

    def test_run_parser_default_empty(self):
        parser = create_parser()
        args = parser.parse_args(["run", "test.vertex"])
        assert args.var == []


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
        assert "2 parsed, 1 skipped" in captured.err

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
        assert "no parse pipeline" in captured.err


class TestHelp:
    """Help output tests."""

    def test_main_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Runtime for .loop and .vertex files" in captured.out

    def test_validate_help(self, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["validate", "--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "Files to validate" in captured.out or "files" in captured.out


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
        captured = capsys.readouterr()
        assert "loops init" in captured.err

    def test_start_parser_file_optional(self):
        parser = create_parser()
        args = parser.parse_args(["start"])
        assert args.file is None

    def test_run_parser_file_optional(self):
        parser = create_parser()
        args = parser.parse_args(["run"])
        assert args.file is None

    def test_store_parser_file_optional(self):
        parser = create_parser()
        args = parser.parse_args(["store"])
        assert args.file is None

    def test_start_explicit_file_still_works(self):
        parser = create_parser()
        args = parser.parse_args(["start", "my.vertex"])
        assert args.file == "my.vertex"
