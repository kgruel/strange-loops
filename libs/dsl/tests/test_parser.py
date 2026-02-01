"""Tests for DSL parser."""

from pathlib import Path

import pytest

from dsl import (
    BoundaryWhen,
    Coerce,
    Duration,
    FoldBy,
    FoldCount,
    FoldLatest,
    FoldMax,
    ParseError,
    Pick,
    Skip,
    Split,
    Strip,
    Transform,
    Trigger,
    parse_loop,
    parse_loop_file,
    parse_vertex,
    parse_vertex_file,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestDuration:
    """Duration parsing tests."""

    def test_seconds(self):
        d = Duration.parse("5s")
        assert d.milliseconds == 5000
        assert d.seconds() == 5.0

    def test_minutes(self):
        d = Duration.parse("2m")
        assert d.milliseconds == 120000

    def test_hours(self):
        d = Duration.parse("1h")
        assert d.milliseconds == 3600000

    def test_milliseconds(self):
        d = Duration.parse("500ms")
        assert d.milliseconds == 500

    def test_compound(self):
        d = Duration.parse("1h30m")
        assert d.milliseconds == 5400000

    def test_str(self):
        d = Duration(5400000)
        assert str(d) == "1h30m"


class TestParseLoopMinimal:
    """Minimal .loop file parsing."""

    def test_from_text(self):
        text = """\
source: whoami
kind: identity
observer: shell
"""
        loop = parse_loop(text)
        assert loop.source == "whoami"
        assert loop.kind == "identity"
        assert loop.observer == "shell"
        assert loop.every is None
        assert loop.format == "lines"
        assert loop.parse == ()

    def test_from_file(self):
        loop = parse_loop_file(FIXTURES / "minimal.loop")
        assert loop.source == "whoami"
        assert loop.kind == "identity"
        assert loop.observer == "shell"


class TestParseLoopFull:
    """Full .loop file parsing with parse pipeline."""

    def test_from_file(self):
        loop = parse_loop_file(FIXTURES / "disk.loop")
        assert loop.source == "df -h"
        assert loop.kind == "disk"
        assert loop.observer == "disk-monitor"
        assert loop.every == Duration(5000)
        assert loop.timeout == Duration(30000)

    def test_parse_steps(self):
        loop = parse_loop_file(FIXTURES / "disk.loop")
        assert len(loop.parse) == 4

        # skip ^Filesystem
        assert isinstance(loop.parse[0], Skip)
        assert loop.parse[0].pattern == "^Filesystem"

        # split
        assert isinstance(loop.parse[1], Split)
        assert loop.parse[1].delimiter is None

        # pick 0, 4, 5 -> fs, pct, mount
        assert isinstance(loop.parse[2], Pick)
        assert loop.parse[2].indices == (0, 4, 5)
        assert loop.parse[2].names == ("fs", "pct", "mount")

        # pct: strip "%" | int
        assert isinstance(loop.parse[3], Transform)
        assert loop.parse[3].field == "pct"
        assert len(loop.parse[3].operations) == 2
        assert isinstance(loop.parse[3].operations[0], Strip)
        assert loop.parse[3].operations[0].chars == "%"
        assert isinstance(loop.parse[3].operations[1], Coerce)
        assert loop.parse[3].operations[1].type == "int"


class TestParseVertexMinimal:
    """Minimal .vertex file parsing."""

    def test_from_file(self):
        vertex = parse_vertex_file(FIXTURES / "minimal.vertex")
        assert vertex.name == "simple"
        assert "counter" in vertex.loops

        counter = vertex.loops["counter"]
        assert len(counter.folds) == 1
        assert counter.folds[0].target == "count"
        assert isinstance(counter.folds[0].op, FoldCount)


class TestParseVertexFull:
    """Full .vertex file parsing."""

    def test_from_file(self):
        vertex = parse_vertex_file(FIXTURES / "system.vertex")
        assert vertex.name == "system-monitor"
        assert vertex.store == Path("./data/system.jsonl")
        assert vertex.discover == "./**/*.loop"
        assert vertex.emit == "system.health"

    def test_loops(self):
        vertex = parse_vertex_file(FIXTURES / "system.vertex")
        assert "disk" in vertex.loops
        assert "memory" in vertex.loops

        disk = vertex.loops["disk"]
        assert len(disk.folds) == 2

        # mounts: by mount
        assert disk.folds[0].target == "mounts"
        assert isinstance(disk.folds[0].op, FoldBy)
        assert disk.folds[0].op.key_field == "mount"

        # updated: latest
        assert disk.folds[1].target == "updated"
        assert isinstance(disk.folds[1].op, FoldLatest)

        # boundary: when disk.complete
        assert isinstance(disk.boundary, BoundaryWhen)
        assert disk.boundary.kind == "disk.complete"

    def test_memory_loop(self):
        vertex = parse_vertex_file(FIXTURES / "system.vertex")
        memory = vertex.loops["memory"]

        # peak: max used
        peak_fold = next(f for f in memory.folds if f.target == "peak")
        assert isinstance(peak_fold.op, FoldMax)
        assert peak_fold.op.field == "used"

    def test_routes(self):
        vertex = parse_vertex_file(FIXTURES / "system.vertex")
        assert vertex.routes == {"disk": "disk", "memory": "memory"}


class TestParseErrors:
    """Parser error handling."""

    def test_missing_source(self):
        text = """\
kind: test
observer: test
"""
        with pytest.raises(ParseError, match="Missing required field: source"):
            parse_loop(text)

    def test_missing_kind(self):
        text = """\
source: echo
observer: test
"""
        with pytest.raises(ParseError, match="Missing required field: kind"):
            parse_loop(text)

    def test_missing_observer(self):
        text = """\
source: echo
kind: test
"""
        with pytest.raises(ParseError, match="Missing required field: observer"):
            parse_loop(text)

    def test_missing_vertex_name(self):
        text = """\
loops:
  counter:
    fold:
      count: +1
"""
        with pytest.raises(ParseError, match="Missing required field: name"):
            parse_vertex(text)

    def test_missing_loops(self):
        text = """\
name: test
"""
        with pytest.raises(ParseError, match="Missing required field: loops"):
            parse_vertex(text)

    def test_invalid_format(self):
        text = """\
source: echo
kind: test
observer: test
format: xml
"""
        with pytest.raises(ParseError, match="format must be"):
            parse_loop(text)

    def test_pick_mismatch(self):
        text = """\
source: echo
kind: test
observer: test
parse:
  pick 0, 1, 2 -> a, b
"""
        with pytest.raises(ParseError, match="3 indices but 2 names"):
            parse_loop(text)


class TestComments:
    """Comment handling tests."""

    def test_line_comments(self):
        text = """\
# This is a comment
source: echo  # inline comment
kind: test
observer: test
"""
        loop = parse_loop(text)
        assert loop.source == "echo"

    def test_comment_in_block(self):
        text = """\
source: df
kind: disk
observer: test
parse:
  # skip header
  skip ^Filesystem
  split
"""
        loop = parse_loop(text)
        assert len(loop.parse) == 2


class TestTriggerSyntax:
    """Tests for on: trigger syntax (Cadence/Source split)."""

    def test_single_trigger(self):
        """Parse on: with single kind."""
        text = """\
source: df -h
on: minute
kind: disk
observer: disk-monitor
"""
        loop = parse_loop(text)
        assert loop.source == "df -h"
        assert loop.on is not None
        assert loop.on.kinds == ("minute",)
        assert loop.kind == "disk"
        assert loop.every is None

    def test_multi_trigger(self):
        """Parse on: with multiple kinds (OR semantics)."""
        text = """\
source: ./checks.sh
on: [minute, deploy.complete]
kind: checks
observer: monitor
"""
        loop = parse_loop(text)
        assert loop.source == "./checks.sh"
        assert loop.on is not None
        assert loop.on.kinds == ("minute", "deploy.complete")
        assert loop.kind == "checks"

    def test_pure_timer_loop(self):
        """Parse pure timer loop (no source)."""
        text = """\
every: 60s
kind: minute
observer: clock
"""
        loop = parse_loop(text)
        assert loop.source is None
        assert loop.every == Duration(60000)
        assert loop.kind == "minute"
        assert loop.observer == "clock"
        assert loop.on is None

    def test_triggered_source_with_parse(self):
        """Triggered source can have parse pipeline."""
        text = """\
source: df -h
on: minute
kind: disk
observer: monitor
parse:
  skip ^Filesystem
  split
"""
        loop = parse_loop(text)
        assert loop.on is not None
        assert loop.on.kinds == ("minute",)
        assert len(loop.parse) == 2

    def test_trigger_class_single(self):
        """Trigger.single() creates single-kind trigger."""
        trigger = Trigger.single("minute")
        assert trigger.kinds == ("minute",)

    def test_trigger_class_multi(self):
        """Trigger.multi() creates multi-kind trigger."""
        trigger = Trigger.multi(["minute", "hour"])
        assert trigger.kinds == ("minute", "hour")
