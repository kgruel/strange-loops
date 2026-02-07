"""Tests for loops CLI."""

from pathlib import Path
from io import StringIO
import sys

import pytest

from loops.main import main, create_parser

FIXTURES = Path(__file__).parent / "fixtures"


class TestParser:
    """Argument parser tests."""

    def test_validate_command(self):
        parser = create_parser()
        args = parser.parse_args(["validate", "test.loop"])
        assert args.command == "validate"
        assert args.file == "test.loop"

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
        assert "File to validate" in captured.out
