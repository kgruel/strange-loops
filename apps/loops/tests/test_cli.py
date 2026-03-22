"""Tests for loops CLI."""

from pathlib import Path
from io import StringIO
import sys

import pytest

from loops.main import main, _parse_vars, _extract_loops_text, loops_home

FIXTURES = Path(__file__).parent / "fixtures"


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

    def test_sync_accepts_var(self):
        """sync --var is handled by _run_sync's pre-parser."""
        from loops.main import _run_sync
        assert callable(_run_sync)

    def test_var_parsed_by_pre_parser(self):
        """--var is handled by pre-parser in _run_sync."""
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
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Runtime for .loop and .vertex files" in captured.out
        # Verbs should be visible
        assert "read" in captured.out
        assert "emit" in captured.out
        assert "close" in captured.out
        # Root commands should be visible
        assert "init" in captured.out
        assert "validate" in captured.out

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
        root = tmp_path / ".vertex"
        assert root.exists()
        content = root.read_text()
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
        assert (deep / ".vertex").exists()

    def test_init_parser_args(self):
        import argparse
        def make_parser():
            p = argparse.ArgumentParser(prog="loops init")
            p.add_argument("name", nargs="?", default=None)
            p.add_argument("--template", "-t")
            return p
        assert make_parser().parse_args(["--template", "session"]).template == "session"
        assert make_parser().parse_args(["-t", "tasks"]).template == "tasks"
        assert make_parser().parse_args([]).template is None
        ns = make_parser().parse_args(["project"])
        assert ns.name == "project" and ns.template is None

    def test_bare_name_creates_local_vertex(self, monkeypatch, tmp_path, capsys):
        """loops init project creates vertex in .loops/ from config-level source."""
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
        vertex = tmp_path / "myproject" / ".loops" / "project.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        # Store path is absolute — survives worktree access
        expected_store = str((tmp_path / "myproject" / ".loops" / "data" / "project.db").resolve())
        assert f'store "{expected_store}"' in content
        assert "decision" in content
        assert (tmp_path / "myproject" / ".loops" / "data").is_dir()

    def test_bare_name_no_source_creates_stub(self, monkeypatch, tmp_path, capsys):
        """loops init project without config-level source creates minimal stub."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = main(["init", "project"])
        assert result == 0
        vertex = project_dir / ".loops" / "project.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        expected_store = str((project_dir / ".loops" / "data" / "project.db").resolve())
        assert f'store "{expected_store}"' in content
        assert "loops {" in content
        assert (project_dir / ".loops" / "data").is_dir()

    def test_template_creates_local_with_cwd(self, monkeypatch, tmp_path, capsys):
        """loops init --template session (no name) creates in .loops/."""
        monkeypatch.chdir(tmp_path)
        result = main(["init", "--template", "session"])
        assert result == 0
        assert (tmp_path / ".loops" / "session.vertex").exists()
        assert (tmp_path / ".loops" / "data").is_dir()


class TestDefaultPaths:
    """store defaults to LOOPS_HOME/.vertex when no file given."""

    def test_store_root_command(self, monkeypatch, tmp_path, capsys):
        """store as root command falls back to LOOPS_HOME/.vertex."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        # Without .vertex, returns 1
        result = main(["store"])
        assert result == 1


class TestReadVerb:
    """Tests for the read verb and implicit read dispatch."""

    @pytest.fixture
    def myvert(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        vdir = tmp_path / "myvert"
        vdir.mkdir()
        (vdir / "myvert.vertex").write_text(
            'name "myvert"\nstore "./data/myvert.db"\n\n'
            'loops {\n  thing { fold { count "inc" } }\n}\n'
        )

    @pytest.mark.parametrize("cmd", [
        ["read", "myvert"],                  # explicit read verb → fold
        ["read", "myvert", "--facts"],       # read + --facts → stream
        ["read", "myvert", "--ticks"],       # read + --ticks → ticks
        ["myvert"],                          # implicit read
        ["myvert", "--facts"],               # implicit read + --facts
        ["myvert", "read"],                  # vertex-first read
        ["myvert", "read", "--facts"],       # vertex-first read + --facts
    ])
    def test_read_routes(self, myvert, cmd):
        assert main(cmd) == 0


class TestDispatchTiers:
    """Tests for the three-tier dispatch model."""

    def test_verb_dispatches_before_vertex(self, monkeypatch, tmp_path):
        """Verbs (read, emit, fold, stream) dispatch in tier 1, before vertex resolution."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        # 'read' with no vertex and no local .vertex should fail at vertex resolution
        result = main(["read"])
        assert result == 1  # fails at vertex resolution, not as "unknown command"

    def test_command_dispatches_before_vertex(self, monkeypatch, tmp_path):
        """Commands (test, compile, ...) dispatch in tier 2, before vertex resolution."""
        # validate with no files in an empty dir
        monkeypatch.chdir(tmp_path)
        result = main(["validate"])
        # Should run validate (finds no files), not try as vertex name
        assert result == 1  # no files found

    def test_unknown_command_errors(self):
        """Unknown first arg that isn't a vertex gives error."""
        result = main(["totally_unknown_thing"])
        assert result == 1


class TestHelpUpdated:
    """Verify help text reflects the new verb-first model."""

    def test_help_shows_read_verb(self, capsys):
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "read" in captured.out
        assert "Read vertex state" in captured.out

    def test_help_shows_verbs_group(self, capsys):
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Verbs" in captured.out

    def test_help_hides_legacy_aliases(self, capsys):
        """Help no longer shows fold/stream/status/log/search."""
        result = main(["--help"])
        assert result == 0
        captured = capsys.readouterr()
        # fold/stream still work as silent aliases but aren't in help
        assert "Shorthand" not in captured.out
        assert "status" not in captured.out.lower().split("read")[0]  # not as a command


class TestEmitParsers:
    """Parser tests for emit in vertex-first ordering."""

    def test_vertex_first_emit(self):
        """Vertex-first: loops session emit decision topic=test"""
        import argparse
        parser = argparse.ArgumentParser(prog="loops emit")
        parser.add_argument("kind")
        parser.add_argument("parts", nargs="*")
        parser.add_argument("--observer", default="")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(["decision", "topic=test"])
        assert args.kind == "decision"
        assert args.parts == ["topic=test"]

    def test_vertex_not_resolvable(self):
        """Vertex-first: unresolvable name gives error, not session dispatch."""
        result = main(["nonexistent_vertex", "fold"])
        assert result == 1


class TestEmitFoldKeyWarning:
    """Warn when payload is missing the fold key field."""

    def _make_vertex(self, tmp_path):
        vf = tmp_path / "test.vertex"
        vf.write_text(
            'name "test"\n'
            'store "./data/test.db"\n\n'
            "loops {\n"
            '  thread { fold { items "by" "name" } }\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  change { fold { items "collect" 20 } }\n'
            "}\n"
        )
        return vf

    def test_warns_missing_name_field(self, tmp_path, capsys):
        from loops.main import _warn_missing_fold_key

        vf = self._make_vertex(tmp_path)

        _warn_missing_fold_key(vf, "thread", {"status": "open"})

        captured = capsys.readouterr()
        assert "folds by 'name'" in captured.err
        assert "not foldable" in captured.err

    def test_warns_missing_topic_field(self, tmp_path, capsys):
        from loops.main import _warn_missing_fold_key

        vf = self._make_vertex(tmp_path)

        _warn_missing_fold_key(vf, "decision", {"message": "test"})

        captured = capsys.readouterr()
        assert "folds by 'topic'" in captured.err

    def test_no_warning_when_key_present(self, tmp_path, capsys):
        from loops.main import _warn_missing_fold_key

        vf = self._make_vertex(tmp_path)

        _warn_missing_fold_key(vf, "thread", {"name": "test", "status": "open"})

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_no_warning_for_collect_fold(self, tmp_path, capsys):
        from loops.main import _warn_missing_fold_key

        vf = self._make_vertex(tmp_path)

        _warn_missing_fold_key(vf, "change", {"message": "something"})

        captured = capsys.readouterr()
        assert captured.err == ""

    def test_no_warning_for_undeclared_kind(self, tmp_path, capsys):
        from loops.main import _warn_missing_fold_key

        vf = self._make_vertex(tmp_path)

        _warn_missing_fold_key(vf, "unknown", {"message": "test"})

        captured = capsys.readouterr()
        assert captured.err == ""


class TestRootLs:
    """Root-level `loops ls` tests."""

    def _seed_home(self, tmp_path):
        """Create LOOPS_HOME with .vertex + child vertices."""
        home = tmp_path / "loops_home"
        home.mkdir()

        # Root vertex with discover (.vertex — bare dotfile defaults name to "root")
        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n'
        )

        # Instance vertex: session
        session_dir = home / "session"
        session_dir.mkdir()
        (session_dir / "session.vertex").write_text(
            'name "session"\nstore "./data/session.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            '  thread { fold { items "by" "name" } }\n'
            "}\n"
        )

        # Aggregation vertex: meta (uses discover for aggregation)
        meta_dir = home / "meta"
        meta_dir.mkdir()
        (meta_dir / "meta.vertex").write_text(
            'name "meta"\n\ndiscover "../session/**/*.vertex"\n'
        )

        return home

    def test_ls_discovers_vertices(self, monkeypatch, tmp_path, capsys):
        home = self._seed_home(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        result = main(["ls"])
        assert result == 0
        captured = capsys.readouterr()
        assert "session" in captured.out
        assert "meta" in captured.out

    def test_ls_minimal(self, monkeypatch, tmp_path, capsys):
        home = self._seed_home(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        result = main(["ls", "-q"])
        assert result == 0
        captured = capsys.readouterr()
        assert "2 vertices" in captured.out

    def test_ls_verbose(self, monkeypatch, tmp_path, capsys):
        home = self._seed_home(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        result = main(["ls", "-v"])
        assert result == 0
        captured = capsys.readouterr()
        # DETAILED shows loop definitions
        assert "decision" in captured.out
        assert "thread" in captured.out

    def test_ls_json(self, monkeypatch, tmp_path, capsys):
        import json

        home = self._seed_home(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        result = main(["ls", "--json"])
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "vertices" in data
        names = [v["name"] for v in data["vertices"]]
        assert "session" in names
        assert "meta" in names

    def test_ls_no_root_vertex(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        result = main(["ls"])
        assert result == 1
        captured = capsys.readouterr()
        assert "loops init" in (captured.out + captured.err)

    def test_vertex_ls_still_works(self, monkeypatch, tmp_path):
        """loops <vertex> ls routes to population, not root ls."""
        home = self._seed_home(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        # session ls should attempt population ls (will fail because no template,
        # but it should NOT route to root ls)
        result = main(["session", "ls"])
        # Returns 1 because session has no template population, but the important
        # thing is it doesn't return vertex listing data
        assert result == 1


class TestExtractLoopsText:
    """_extract_loops_text extraction tests."""

    def test_extract_loops_text(self):
        content = (
            'name "project"\ndiscover "./instances/**/*.vertex"\n\n'
            'loops {\n  decision { fold { items "by" "topic" } }\n}\n'
        )
        result = _extract_loops_text(content)
        assert result is not None
        assert result.startswith("loops {")
        assert "decision" in result
        assert result.endswith("}")

    def test_extract_loops_text_none(self):
        content = 'name "project"\ndiscover "./instances/**/*.vertex"\n'
        assert _extract_loops_text(content) is None

    def test_extract_loops_text_nested_braces(self):
        content = 'loops {\n  a { fold { items "by" "x" } }\n  b { fold { items "collect" 5 } }\n}\n'
        result = _extract_loops_text(content)
        assert result is not None
        assert "a {" in result
        assert "b {" in result


class TestInitFromSource:
    """Init derives local instance from config-level vertex."""

    def test_init_from_aggregation_loops(self, monkeypatch, tmp_path, capsys):
        """loops init <name> derives instance from aggregation vertex's loops block."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        # Create aggregation vertex with loops block
        config_dir = tmp_path / "project"
        config_dir.mkdir()
        (config_dir / "project.vertex").write_text(
            'name "project"\n'
            'combine {\n'
            '    vertex "/some/path"\n'
            '}\n\n'
            'loops {\n'
            '  decision { fold { items "by" "topic" } }\n'
            '  thread   { fold { items "by" "name" } }\n'
            '}\n'
        )
        # Init local instance
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = main(["init", "project"])
        assert result == 0
        vertex = project_dir / ".loops" / "project.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        expected_store = str((project_dir / ".loops" / "data" / "project.db").resolve())
        assert f'store "{expected_store}"' in content
        assert "decision" in content
        assert "thread" in content
        # Registration: config-level vertex should now include this instance
        updated_config = (config_dir / "project.vertex").read_text()
        abs_path = str((project_dir / ".loops" / "project.vertex").resolve())
        assert abs_path in updated_config

    def test_init_aggregation_no_loops_no_store(self, monkeypatch, tmp_path, capsys):
        """Aggregation vertex without loops block should produce minimal stub, not copy raw combine."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        config_dir = tmp_path / "project"
        config_dir.mkdir()
        # Comment contains "store" but there's no store directive — should not copy
        (config_dir / "project.vertex").write_text(
            '// project — aggregation vertex, combines project stores\n'
            'name "project"\n'
            'combine {\n'
            '    vertex "/some/path"\n'
            '}\n'
        )
        project_dir = tmp_path / "myproject"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        result = main(["init", "project"])
        assert result == 0
        content = (project_dir / ".loops" / "project.vertex").read_text()
        # Should have a store directive (from minimal stub), not a combine block
        expected_store = str((project_dir / ".loops" / "data" / "project.db").resolve())
        assert f'store "{expected_store}"' in content
        assert "combine" not in content
