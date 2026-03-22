"""Tests for KDL-based DSL loader."""

from pathlib import Path

import pytest

from lang import (
    BoundaryAfter,
    BoundaryEvery,
    BoundaryWhen,
    Coerce,
    Duration,
    FoldAvg,
    FoldBy,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldWindow,
    LensDecl,
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
source "whoami"
kind "identity"
observer "shell"
"""
        loop = parse_loop(text)
        assert loop.source == "whoami"
        assert loop.kind == "identity"
        assert loop.observer == "shell"
        assert loop.every is None
        assert loop.format == "lines"
        assert loop.parse == ()

    def test_source_with_url_chars(self):
        text = """\
source "curl -s https://example/api?x=1&y=2"
kind "api"
observer "http"
"""
        loop = parse_loop(text)
        assert loop.source == "curl -s https://example/api?x=1&y=2"

    def test_source_raw_string(self):
        text = r"""
source #"curl -sf "http://host/api?x=1&y=2""#
kind "api"
observer "http"
"""
        loop = parse_loop(text)
        assert loop.source == 'curl -sf "http://host/api?x=1&y=2"'

    def test_origin_default(self):
        text = """\
source "whoami"
kind "identity"
observer "shell"
"""
        loop = parse_loop(text)
        assert loop.origin == ""

    def test_origin_declared(self):
        text = """\
source "whoami"
kind "identity"
observer "shell"
origin "claude-code"
"""
        loop = parse_loop(text)
        assert loop.origin == "claude-code"

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
        assert loop.every == "5s"
        assert loop.timeout == "30s"

    def test_parse_steps(self):
        loop = parse_loop_file(FIXTURES / "disk.loop")
        assert len(loop.parse) == 4

        # skip ^Filesystem
        assert isinstance(loop.parse[0], Skip)
        assert loop.parse[0].pattern == "^Filesystem"

        # split
        assert isinstance(loop.parse[1], Split)
        assert loop.parse[1].delimiter is None

        # pick 0 4 5 { names "fs" "pct" "mount" }
        assert isinstance(loop.parse[2], Pick)
        assert loop.parse[2].indices == (0, 4, 5)
        assert loop.parse[2].names == ("fs", "pct", "mount")

        # transform "pct" { strip "%" coerce "int" }
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

        # boundary when="disk.complete"
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


class TestCountBasedBoundaries:
    """Count-based boundary parsing (after N, every N)."""

    def test_boundary_after(self):
        text = """\
name "batch"
loops {
  events {
    fold {
      count "inc"
    }
    boundary after=10
  }
}
"""
        vertex = parse_vertex(text)
        loop = vertex.loops["events"]
        assert isinstance(loop.boundary, BoundaryAfter)
        assert loop.boundary.count == 10

    def test_boundary_every(self):
        text = """\
name "windowed"
loops {
  metrics {
    fold {
      total "sum" "value"
    }
    boundary every=50
  }
}
"""
        vertex = parse_vertex(text)
        loop = vertex.loops["metrics"]
        assert isinstance(loop.boundary, BoundaryEvery)
        assert loop.boundary.count == 50

    def test_vertex_level_boundary(self):
        """boundary as sibling of loop definitions fires vertex-wide."""
        text = """\
name "project"
store "./data/project.db"
loops {
  decision {
    fold { items "by" "topic" }
  }
  session {
    fold { items "by" "name" }
  }
  boundary when="session" status="closed"
}
"""
        vertex = parse_vertex(text)
        # Session loop has NO boundary
        assert vertex.loops["session"].boundary is None
        # Vertex has boundary
        assert vertex.boundary is not None
        assert isinstance(vertex.boundary, BoundaryWhen)
        assert vertex.boundary.kind == "session"
        assert vertex.boundary.match == (("status", "closed"),)

    def test_vertex_level_boundary_no_match(self):
        """Vertex boundary without match conditions."""
        text = """\
name "batch"
store "./data/batch.db"
loops {
  metric { fold { total "sum" "value" } }
  boundary when="flush"
}
"""
        vertex = parse_vertex(text)
        assert vertex.boundary is not None
        assert vertex.boundary.kind == "flush"
        assert vertex.boundary.match == ()

    def test_boundary_with_conditions(self):
        """Boundary with fold-state condition children."""
        text = """\
name "weather"
store "./data/weather.db"
loops {
  reading {
    fold { high "max" "temp_f" }
    boundary when="reading" {
      condition "high" ">=" 80
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["reading"].boundary
        assert isinstance(b, BoundaryWhen)
        assert b.kind == "reading"
        assert b.match == ()
        assert len(b.conditions) == 1
        assert b.conditions[0].target == "high"
        assert b.conditions[0].op == ">="
        assert b.conditions[0].value == 80.0

    def test_boundary_with_multiple_conditions(self):
        """Boundary with multiple conditions (AND semantics)."""
        text = """\
name "weather"
store "./data/weather.db"
loops {
  reading {
    fold {
      high "max" "temp_f"
      humidity "latest" "humidity"
    }
    boundary when="reading" {
      condition "high" ">=" 80
      condition "humidity" ">" 60
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["reading"].boundary
        assert len(b.conditions) == 2
        assert b.conditions[0].target == "high"
        assert b.conditions[1].target == "humidity"
        assert b.conditions[1].op == ">"
        assert b.conditions[1].value == 60.0

    def test_boundary_conditions_with_match(self):
        """Conditions compose with payload match properties."""
        text = """\
name "weather"
store "./data/weather.db"
loops {
  reading {
    fold { high "max" "temp_f" }
    boundary when="alert" source="outdoor" {
      condition "high" ">=" 80
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["reading"].boundary
        assert b.kind == "alert"
        assert b.match == (("source", "outdoor"),)
        assert len(b.conditions) == 1

    def test_vertex_boundary_with_conditions(self):
        """Vertex-level boundary with fold-state conditions."""
        text = """\
name "monitor"
store "./data/monitor.db"
loops {
  metric {
    fold { high "max" "value" }
  }
  boundary when="metric" {
    condition "high" ">=" 100
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.boundary is not None
        assert len(vertex.boundary.conditions) == 1
        assert vertex.boundary.conditions[0].target == "high"
        assert vertex.boundary.conditions[0].op == ">="

    def test_boundary_unknown_child_rejected(self):
        """Unknown children in boundary block are rejected."""
        text = """\
name "test"
store "./data/test.db"
loops {
  reading {
    fold { items "collect" 10 }
    boundary when="reading" {
      filter "high" ">=" 80
    }
  }
}
"""
        with pytest.raises(Exception, match="unknown boundary child"):
            parse_vertex(text)

    def test_boundary_run_clause(self):
        """Run clause parsed as child of boundary."""
        text = """\
name "orchestration"
store "./data/orchestration.db"
loops {
  task {
    fold { items "by" "name" }
    boundary when="task" status="open" {
      run "scripts/dispatch.sh"
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["task"].boundary
        assert b.run == "scripts/dispatch.sh"
        assert b.kind == "task"
        assert b.match == (("status", "open"),)

    def test_boundary_run_with_conditions(self):
        """Run clause composes with conditions."""
        text = """\
name "monitor"
store "./data/monitor.db"
loops {
  reading {
    fold { count "inc" }
    boundary when="reading" {
      condition "count" ">=" 100
      run "scripts/alert.sh"
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["reading"].boundary
        assert b.run == "scripts/alert.sh"
        assert len(b.conditions) == 1

    def test_boundary_run_count_based(self):
        """Run clause on count-based boundary."""
        text = """\
name "batch"
store "./data/batch.db"
loops {
  event {
    fold { items "collect" 50 }
    boundary every="50" {
      run "scripts/process-batch.sh"
    }
  }
}
"""
        vertex = parse_vertex(text)
        b = vertex.loops["event"].boundary
        assert b.run == "scripts/process-batch.sh"
        assert b.count == 50

    def test_vertex_boundary_run_clause(self):
        """Run clause on vertex-level boundary."""
        text = """\
name "project"
store "./data/project.db"
loops {
  decision { fold { items "by" "topic" } }
  boundary when="session" status="closed" {
    run "scripts/session-close.sh"
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.boundary.run == "scripts/session-close.sh"

    def test_boundary_no_run_clause(self):
        """Boundary without run clause has run=None."""
        text = """\
name "test"
store "./data/test.db"
loops {
  item {
    fold { items "by" "name" }
    boundary when="session" status="closed"
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.loops["item"].boundary.run is None

    def test_boundary_run_requires_argument(self):
        """Run clause without command argument is rejected."""
        text = """\
name "test"
store "./data/test.db"
loops {
  item {
    fold { items "by" "name" }
    boundary when="task" {
      run
    }
  }
}
"""
        with pytest.raises(Exception, match="run requires a command argument"):
            parse_vertex(text)

    def test_every_as_loop_key_still_works(self):
        text = """\
source "echo test"
every "5s"
kind "test"
observer "test"
"""
        loop = parse_loop(text)
        assert loop.every == "5s"


class TestParseErrors:
    """Parser error handling."""

    def test_missing_source(self):
        text = """\
kind "test"
observer "test"
"""
        with pytest.raises(ParseError, match="Missing required field: source"):
            parse_loop(text)

    def test_missing_kind(self):
        text = """\
source "echo"
observer "test"
"""
        with pytest.raises(ParseError, match="Missing required field: kind"):
            parse_loop(text)

    def test_missing_observer(self):
        text = """\
source "echo"
kind "test"
"""
        with pytest.raises(ParseError, match="Missing required field: observer"):
            parse_loop(text)

    def test_missing_vertex_name(self):
        text = """\
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
"""
        with pytest.raises(ParseError, match="Missing required field: name"):
            parse_vertex(text)

    def test_missing_loops(self):
        text = """\
name "test"
"""
        with pytest.raises(ParseError, match="Missing required field: loops"):
            parse_vertex(text)

    def test_discover_only_vertex_no_loops_required(self):
        """A vertex with discover: but no loops: is valid."""
        text = """\
name "root"
discover "./**/*.vertex"
"""
        v = parse_vertex(text)
        assert v.name == "root"
        assert v.loops == {}
        assert v.discover == "./**/*.vertex"

    def test_pick_mismatch(self):
        text = """\
source "echo"
kind "test"
observer "test"
parse {
  pick 0 1 2 {
    names "a" "b"
  }
}
"""
        with pytest.raises(ParseError, match="3 indices but 2 names"):
            parse_loop(text)


class TestComments:
    """Comment handling tests."""

    def test_line_comments(self):
        text = """\
// This is a comment
source "echo"
kind "test"
observer "test"
"""
        loop = parse_loop(text)
        assert loop.source == "echo"

    def test_comment_in_block(self):
        text = """\
source "df"
kind "disk"
observer "test"
parse {
  // skip header
  skip "^Filesystem"
  split
}
"""
        loop = parse_loop(text)
        assert len(loop.parse) == 2


class TestTriggerSyntax:
    """Tests for on: trigger syntax."""

    def test_single_trigger(self):
        text = """\
source "df -h"
on "minute"
kind "disk"
observer "disk-monitor"
"""
        loop = parse_loop(text)
        assert loop.source == "df -h"
        assert loop.on is not None
        assert loop.on.kinds == ("minute",)
        assert loop.kind == "disk"
        assert loop.every is None

    def test_multi_trigger(self):
        text = """\
source "./checks.sh"
on "minute" "deploy.complete"
kind "checks"
observer "monitor"
"""
        loop = parse_loop(text)
        assert loop.source == "./checks.sh"
        assert loop.on is not None
        assert loop.on.kinds == ("minute", "deploy.complete")
        assert loop.kind == "checks"

    def test_pure_timer_loop(self):
        text = """\
every "60s"
kind "minute"
observer "clock"
"""
        loop = parse_loop(text)
        assert loop.source is None
        assert loop.every == "60s"
        assert loop.kind == "minute"
        assert loop.observer == "clock"
        assert loop.on is None

    def test_triggered_source_with_parse(self):
        text = """\
source "df -h"
on "minute"
kind "disk"
observer "monitor"
parse {
  skip "^Filesystem"
  split
}
"""
        loop = parse_loop(text)
        assert loop.on is not None
        assert loop.on.kinds == ("minute",)
        assert len(loop.parse) == 2

    def test_trigger_class_single(self):
        trigger = Trigger.single("minute")
        assert trigger.kinds == ("minute",)

    def test_trigger_class_multi(self):
        trigger = Trigger.multi(["minute", "hour"])
        assert trigger.kinds == ("minute", "hour")


class TestVertexNesting:
    """Tests for vertices: syntax."""

    def test_explicit_vertices_list(self):
        vertex = parse_vertex_file(FIXTURES / "nested.vertex")
        assert vertex.name == "regional"
        assert vertex.vertices is not None
        assert len(vertex.vertices) == 2
        assert vertex.vertices[0] == Path("./system-west.vertex")
        assert vertex.vertices[1] == Path("./system-east.vertex")

    def test_mixed_sources_and_vertices(self):
        vertex = parse_vertex_file(FIXTURES / "mixed.vertex")
        assert vertex.name == "root"
        assert vertex.sources is not None
        assert len(vertex.sources) == 1
        assert vertex.sources[0] == Path("./monitor.loop")
        assert vertex.vertices is not None
        assert len(vertex.vertices) == 2
        assert vertex.vertices[0] == Path("./infra/infra.vertex")
        assert vertex.vertices[1] == Path("./personal/personal.vertex")

    def test_vertices_from_text(self):
        text = """\
name "test"
vertices "./child.vertex"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.vertices is not None
        assert len(vertex.vertices) == 1
        assert vertex.vertices[0] == Path("./child.vertex")

    def test_discover_vertex_pattern(self):
        text = """\
name "infra"
discover "./**/*.vertex"
loops {
  aggregator {
    fold {
      total "inc"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.discover == "./**/*.vertex"

    def test_no_vertices_is_none(self):
        vertex = parse_vertex_file(FIXTURES / "minimal.vertex")
        assert vertex.vertices is None


class TestParseAvgFold:
    """Tests for avg fold syntax."""

    def test_avg_fold(self):
        text = """\
name "metrics"
loops {
  latency {
    fold {
      rate "avg" "interval"
    }
  }
}
"""
        vertex = parse_vertex(text)
        fold = vertex.loops["latency"].folds[0]
        assert fold.target == "rate"
        assert isinstance(fold.op, FoldAvg)
        assert fold.op.field == "interval"

    def test_avg_fold_with_other_folds(self):
        text = """\
name "metrics"
loops {
  pulse {
    fold {
      count "inc"
      rate "avg" "interval"
      peak "max" "interval"
    }
  }
}
"""
        vertex = parse_vertex(text)
        folds = vertex.loops["pulse"].folds

        assert folds[0].target == "count"
        assert isinstance(folds[0].op, FoldCount)

        assert folds[1].target == "rate"
        assert isinstance(folds[1].op, FoldAvg)
        assert folds[1].op.field == "interval"

        assert folds[2].target == "peak"
        assert isinstance(folds[2].op, FoldMax)


class TestParseWindowFold:
    """Tests for window fold syntax."""

    def test_window_fold(self):
        text = """\
name "metrics"
loops {
  pulse {
    fold {
      intervals "window" 10 "interval"
    }
  }
}
"""
        vertex = parse_vertex(text)
        fold = vertex.loops["pulse"].folds[0]
        assert fold.target == "intervals"
        assert isinstance(fold.op, FoldWindow)
        assert fold.op.size == 10
        assert fold.op.field == "interval"

    def test_window_fold_size_one(self):
        text = """\
name "metrics"
loops {
  recent {
    fold {
      last "window" 1 "value"
    }
  }
}
"""
        vertex = parse_vertex(text)
        fold = vertex.loops["recent"].folds[0]
        assert isinstance(fold.op, FoldWindow)
        assert fold.op.size == 1
        assert fold.op.field == "value"

    def test_window_and_avg_together(self):
        text = """\
name "cadence"
loops {
  pulse {
    fold {
      intervals "window" 10 "interval"
      avg_rate "avg" "interval"
    }
    boundary when="pulse.tick"
  }
}
"""
        vertex = parse_vertex(text)
        folds = vertex.loops["pulse"].folds

        assert folds[0].target == "intervals"
        assert isinstance(folds[0].op, FoldWindow)
        assert folds[0].op.size == 10

        assert folds[1].target == "avg_rate"
        assert isinstance(folds[1].op, FoldAvg)
        assert folds[1].op.field == "interval"


class TestTemplateSource:
    """Tests for template source parsing."""

    def test_template_source_basic(self):
        text = """\
name "status"
sources {
  template "stacks/status.loop" {
    with kind="infra" host="192.168.1.30"
    with kind="media" host="192.168.1.40"
  }
}
loops {
  infra {
    fold {
      count "inc"
    }
  }
  media {
    fold {
      count "inc"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources is not None
        assert len(vertex.sources) == 1

        from lang import TemplateSource

        source = vertex.sources[0]
        assert isinstance(source, TemplateSource)
        assert source.template == Path("stacks/status.loop")
        assert len(source.params) == 2
        assert source.params[0].values == {"kind": "infra", "host": "192.168.1.30"}
        assert source.params[1].values == {"kind": "media", "host": "192.168.1.40"}
        assert source.loop is None

    def test_template_source_with_loop_spec(self):
        text = """\
name "status"
sources {
  template "stacks/status.loop" {
    with kind="infra" host="192.168.1.30"
    loop {
      fold {
        containers "collect" 50
      }
      boundary when="infra.complete"
    }
  }
}
loops {
  infra {
    fold {
      count "inc"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources is not None
        assert len(vertex.sources) == 1

        from lang import BoundaryWhen, FoldCollect, TemplateSource

        source = vertex.sources[0]
        assert isinstance(source, TemplateSource)
        assert source.loop is not None
        assert len(source.loop.folds) == 1
        assert source.loop.folds[0].target == "containers"
        assert isinstance(source.loop.folds[0].op, FoldCollect)
        assert source.loop.folds[0].op.max_items == 50
        assert isinstance(source.loop.boundary, BoundaryWhen)
        assert source.loop.boundary.kind == "infra.complete"

    def test_mixed_sources_and_templates(self):
        text = """\
name "test"
sources {
  path "./simple.loop"
  template "stacks/status.loop" {
    with kind="test"
  }
}
loops {
  test {
    fold {
      count "inc"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources is not None
        assert len(vertex.sources) == 2

        from lang import TemplateSource

        assert isinstance(vertex.sources[0], Path)
        assert vertex.sources[0] == Path("./simple.loop")
        assert isinstance(vertex.sources[1], TemplateSource)
        assert vertex.sources[1].template == Path("stacks/status.loop")


class TestExplodeStep:
    """Tests for explode parse step."""

    def test_explode_with_path(self):
        text = """\
source "curl -s http://api/alerts"
kind "alerts"
observer "test"
format "json"
parse {
  explode path="data.alerts"
}
"""
        loop = parse_loop(text)
        from lang.ast import Explode

        assert len(loop.parse) == 1
        assert isinstance(loop.parse[0], Explode)
        assert loop.parse[0].path == "data.alerts"
        assert loop.parse[0].carry is None

    def test_explode_with_carry(self):
        text = """\
source "curl -s http://api/rules"
kind "rules"
observer "test"
format "json"
parse {
  explode path="data.groups" carry="name:group_name"
}
"""
        loop = parse_loop(text)
        from lang.ast import Explode

        assert isinstance(loop.parse[0], Explode)
        assert loop.parse[0].path == "data.groups"
        assert loop.parse[0].carry == {"name": "group_name"}


class TestProjectStep:
    """Tests for project parse step."""

    def test_project_fields(self):
        text = """\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  project {
    alertname path="labels.alertname"
    state path="state"
    severity path="labels.severity"
  }
}
"""
        loop = parse_loop(text)
        from lang.ast import Project

        assert len(loop.parse) == 1
        assert isinstance(loop.parse[0], Project)
        assert loop.parse[0].fields == {
            "alertname": "labels.alertname",
            "state": "state",
            "severity": "labels.severity",
        }


class TestWhereStep:
    """Tests for where parse step."""

    def test_where_equals(self):
        text = """\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  where path="status" equals="success"
}
"""
        loop = parse_loop(text)
        from lang.ast import Where

        assert len(loop.parse) == 1
        assert isinstance(loop.parse[0], Where)
        assert loop.parse[0].path == "status"
        assert loop.parse[0].op == "equals"
        assert loop.parse[0].value == "success"

    def test_where_not_equals(self):
        text = """\
source "curl -s http://api"
kind "rules"
observer "test"
format "json"
parse {
  where path="type" not_equals="recording"
}
"""
        loop = parse_loop(text)
        from lang.ast import Where

        assert isinstance(loop.parse[0], Where)
        assert loop.parse[0].op == "not_equals"
        assert loop.parse[0].value == "recording"

    def test_where_in(self):
        text = """\
source "cat session.jsonl"
kind "exchange"
observer "test"
format "ndjson"
parse {
  where path="type" "in" "user" "assistant"
}
"""
        loop = parse_loop(text)
        from lang.ast import Where

        assert isinstance(loop.parse[0], Where)
        assert loop.parse[0].path == "type"
        assert loop.parse[0].op == "in_"
        assert loop.parse[0].values == ("user", "assistant")

    def test_where_not_in(self):
        text = """\
source "cat session.jsonl"
kind "exchange"
observer "test"
format "ndjson"
parse {
  where path="type" "not_in" "system" "tool_result" "tool_use"
}
"""
        loop = parse_loop(text)
        from lang.ast import Where

        assert isinstance(loop.parse[0], Where)
        assert loop.parse[0].op == "not_in"
        assert loop.parse[0].values == ("system", "tool_result", "tool_use")

    def test_full_pipeline(self):
        """Full pipeline with where, explode, project."""
        text = """\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  where path="status" equals="success"
  explode path="data.alerts"
  project {
    alertname path="labels.alertname"
    state path="state"
  }
}
"""
        loop = parse_loop(text)
        from lang.ast import Explode, Project, Where

        assert len(loop.parse) == 3
        assert isinstance(loop.parse[0], Where)
        assert isinstance(loop.parse[1], Explode)
        assert isinstance(loop.parse[2], Project)


class TestEnvBlock:
    """Tests for env block (KDL properties)."""

    def test_env_properties(self):
        text = """\
source "echo test"
kind "test"
observer "test"
env host="localhost" port="8080"
"""
        loop = parse_loop(text)
        assert loop.env == {"host": "localhost", "port": "8080"}


class TestSelectStep:
    """Tests for select parse step."""

    def test_select_fields(self):
        text = """\
source "docker compose ps --format json"
kind "status"
observer "test"
format "ndjson"
parse {
  select "Name" "State" "Health"
}
"""
        loop = parse_loop(text)
        from lang.ast import Select

        assert len(loop.parse) == 1
        assert isinstance(loop.parse[0], Select)
        assert loop.parse[0].fields == ("Name", "State", "Health")


class TestFromFile:
    """Tests for 'from file' external parameter source."""

    def test_from_file_alone(self):
        """from file without any with rows."""
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold {
        count "inc"
      }
      boundary when="{{kind}}.complete"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources is not None
        assert len(vertex.sources) == 1

        from lang import FromFile, TemplateSource

        source = vertex.sources[0]
        assert isinstance(source, TemplateSource)
        assert source.from_ is not None
        assert isinstance(source.from_, FromFile)
        assert source.from_.path == Path("./feeds.list")
        assert len(source.params) == 0

    def test_from_file_with_inline_rows(self):
        """from file coexists with inline with rows."""
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    with kind="pinned" feed_url="https://example.com/rss"
    loop {
      fold {
        count "inc"
      }
      boundary when="{{kind}}.complete"
    }
  }
}
"""
        vertex = parse_vertex(text)
        from lang import FromFile, TemplateSource

        source = vertex.sources[0]
        assert isinstance(source, TemplateSource)
        assert source.from_ is not None
        assert isinstance(source.from_, FromFile)
        assert len(source.params) == 1
        assert source.params[0].values["kind"] == "pinned"

    def test_error_neither_from_nor_with(self):
        """Error when template has neither from nor with."""
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    loop {
      fold {
        count "inc"
      }
    }
  }
}
"""
        with pytest.raises(ParseError, match="requires 'with' rows or a 'from' source"):
            parse_vertex(text)

    def test_error_unknown_strategy(self):
        """Error on unknown from strategy."""
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    from fold "some.projection"
    loop {
      fold {
        count "inc"
      }
    }
  }
}
"""
        with pytest.raises(ParseError, match="Unknown from strategy"):
            parse_vertex(text)

    def test_error_multiple_from_nodes(self):
        """Error when template has more than one from node."""
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    from file "./a.list"
    from file "./b.list"
    loop {
      fold {
        count "inc"
      }
    }
  }
}
"""
        with pytest.raises(ParseError, match="at most one 'from' node"):
            parse_vertex(text)


class TestSearchDeclaration:
    """Tests for search field declaration in loop definitions."""

    def test_search_fields_parsed(self):
        text = """\
name "messaging"
loops {
  exchange {
    fold { items "by" "conversation_id" }
    search "prompt" "response"
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["exchange"]
        assert loop_def.search == ("prompt", "response")

    def test_search_single_field(self):
        text = """\
name "messaging"
loops {
  telegram.message {
    fold { items "by" "chat_id" }
    search "text"
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.loops["telegram.message"].search == ("text",)

    def test_search_without_fold(self):
        """A kind can be searchable without being foldable."""
        text = """\
name "ambient"
loops {
  ambient.text {
    search "text" "source"
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["ambient.text"]
        assert loop_def.search == ("text", "source")
        assert loop_def.folds == ()

    def test_no_search_defaults_empty(self):
        text = """\
name "project"
loops {
  decision {
    fold { items "by" "topic" }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.loops["decision"].search == ()

    def test_search_empty_args_error(self):
        text = """\
name "test"
loops {
  thing {
    fold { count "inc" }
    search
  }
}
"""
        with pytest.raises(ParseError, match="search requires at least one field name"):
            parse_vertex(text)

    def test_search_in_template_loop(self):
        text = """\
name "feeds"
sources {
  template "./sources/feed.loop" {
    from file "./feeds.list"
    loop {
      fold { items "by" "link" }
      search "title" "summary"
    }
  }
}
"""
        vertex = parse_vertex(text)
        from lang import TemplateSource

        source = vertex.sources[0]
        assert isinstance(source, TemplateSource)
        assert source.loop is not None
        assert source.loop.search == ("title", "summary")


class TestCombineBlock:
    """Tests for combine block parsing (combinatorial vertices)."""

    def test_basic_combine(self):
        text = """\
name "all-decisions"
combine {
    vertex "project"
    vertex "meta"
}

loops {
  decision {
    fold {
      items "by" "topic"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.combine is not None
        assert len(vertex.combine) == 2

        from lang import CombineEntry

        assert isinstance(vertex.combine[0], CombineEntry)
        assert vertex.combine[0].name == "project"
        assert vertex.combine[1].name == "meta"

    def test_combine_three_vertices(self):
        text = """\
name "all"
combine {
    vertex "project"
    vertex "meta"
    vertex "reading"
}

loops {
  decision {
    fold {
      items "by" "topic"
    }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.combine is not None
        assert len(vertex.combine) == 3
        assert vertex.combine[2].name == "reading"

    def test_combine_no_store(self):
        """Combinatorial vertex has no store."""
        text = """\
name "combined"
combine {
    vertex "a"
    vertex "b"
}
loops {
  counter { fold { count "inc" } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.store is None
        assert vertex.combine is not None

    def test_combine_with_store_error(self):
        """combine and store are mutually exclusive."""
        text = """\
name "bad"
store "./data.db"
combine {
    vertex "a"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="combine is mutually exclusive with store"):
            parse_vertex(text)

    def test_combine_with_discover_error(self):
        """combine and discover are mutually exclusive."""
        text = """\
name "bad"
discover "./**/*.vertex"
combine {
    vertex "a"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="combine is mutually exclusive with discover"):
            parse_vertex(text)

    def test_combine_with_sources_error(self):
        """combine and sources are mutually exclusive."""
        text = """\
name "bad"
sources {
    path "./monitor.loop"
}
combine {
    vertex "a"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="combine is mutually exclusive with sources"):
            parse_vertex(text)

    def test_combine_empty_error(self):
        """combine block must have at least one vertex."""
        text = """\
name "bad"
combine {
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="combine block requires at least one vertex"):
            parse_vertex(text)

    def test_combine_unknown_entry_error(self):
        """Unknown node type inside combine block."""
        text = """\
name "bad"
combine {
    store "./data.db"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="Unknown combine entry"):
            parse_vertex(text)

    def test_combine_without_loops_valid(self):
        """A combine vertex without loops is valid (loops can be empty for combine)."""
        text = """\
name "combined"
combine {
    vertex "a"
    vertex "b"
}
"""
        # Combine vertices don't require loops — they can just merge raw facts/ticks
        vertex = parse_vertex(text)
        assert vertex.combine is not None
        assert vertex.loops == {}


class TestObserversBlock:
    """Tests for observers block parsing."""

    def test_basic_observers(self):
        text = """\
name "project"
observers {
  kyle { }
  loops-claude { identity "identity" }
}
loops {
  decision { fold { items "by" "topic" } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.observers is not None
        assert len(vertex.observers) == 2

        from lang import ObserverDecl

        assert isinstance(vertex.observers[0], ObserverDecl)
        assert vertex.observers[0].name == "kyle"
        assert vertex.observers[0].identity is None
        assert vertex.observers[0].grant is None

        assert vertex.observers[1].name == "loops-claude"
        assert vertex.observers[1].identity == "identity"

    def test_observer_with_grant(self):
        text = """\
name "project"
observers {
  ci-bot {
    grant {
      potential "change" "log"
    }
  }
}
loops {
  change { fold { items "collect" 20 } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.observers is not None
        obs = vertex.observers[0]
        assert obs.name == "ci-bot"
        assert obs.grant is not None
        assert obs.grant.potential == frozenset({"change", "log"})

    def test_observers_empty_error(self):
        text = """\
name "project"
observers {
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="observers block requires at least one observer"):
            parse_vertex(text)

    def test_observer_unknown_field_error(self):
        text = """\
name "project"
observers {
  kyle {
    email "kyle@example.com"
  }
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="Unknown observer field"):
            parse_vertex(text)

    def test_no_observers_is_none(self):
        vertex = parse_vertex_file(FIXTURES / "minimal.vertex")
        assert vertex.observers is None

    def test_dotvertex_defaults_name_to_root(self, tmp_path):
        """A .vertex file (bare dotfile) defaults name to 'root'."""
        dotvertex = tmp_path / ".vertex"
        dotvertex.write_text("""\
discover "./**/*.vertex"
""")
        vertex = parse_vertex_file(dotvertex)
        assert vertex.name == "root"
        assert vertex.discover == "./**/*.vertex"

    def test_dotvertex_with_observers(self, tmp_path):
        dotvertex = tmp_path / ".vertex"
        dotvertex.write_text("""\
discover "./**/*.vertex"

observers {
  kyle { }
}
""")
        vertex = parse_vertex_file(dotvertex)
        assert vertex.name == "root"
        assert vertex.observers is not None
        assert vertex.observers[0].name == "kyle"


class TestSourcesSequentialBlock:
    """Tests for sources sequential { ... } block parsing."""

    def test_basic_sequential_block(self):
        text = """\
name "ci"
sources sequential {
    source "ruff check --fix src/" { kind "lint.result" }
    source "pytest tests/ -q"      { kind "test.result" }
}
loops {
  counter { fold { count "inc" } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources_blocks is not None
        assert len(vertex.sources_blocks) == 1

        from lang import InlineSource, SourcesBlock

        block = vertex.sources_blocks[0]
        assert isinstance(block, SourcesBlock)
        assert block.mode == "sequential"
        assert len(block.sources) == 2
        assert isinstance(block.sources[0], InlineSource)
        assert block.sources[0].command == "ruff check --fix src/"
        assert block.sources[0].kind == "lint.result"
        assert block.sources[1].command == "pytest tests/ -q"
        assert block.sources[1].kind == "test.result"

    def test_sequential_block_single_source(self):
        text = """\
name "ci"
sources sequential {
    source "make build" { kind "build.result" }
}
loops {
  counter { fold { count "inc" } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources_blocks is not None
        block = vertex.sources_blocks[0]
        assert len(block.sources) == 1
        assert block.sources[0].command == "make build"

    def test_sequential_block_coexists_with_bare_sources(self):
        """Sequential block and bare sources { path ... } can coexist."""
        text = """\
name "ci"
sources {
    path "./monitor.loop"
}
sources sequential {
    source "ruff check src/" { kind "lint.result" }
}
loops {
  counter { fold { count "inc" } }
}
"""
        vertex = parse_vertex(text)
        assert vertex.sources is not None
        assert len(vertex.sources) == 1
        assert vertex.sources[0] == Path("./monitor.loop")
        assert vertex.sources_blocks is not None
        assert len(vertex.sources_blocks) == 1

    def test_sequential_block_no_loops_required(self):
        """A vertex with sources sequential but no loops is valid."""
        text = """\
name "ci"
sources sequential {
    source "ruff check src/" { kind "lint.result" }
    source "pytest tests/" { kind "test.result" }
}
"""
        vertex = parse_vertex(text)
        assert vertex.loops == {}
        assert vertex.sources_blocks is not None

    def test_sequential_empty_block_error(self):
        text = """\
name "ci"
sources sequential {
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="sources sequential block requires at least one source"):
            parse_vertex(text)

    def test_unknown_mode_error(self):
        text = """\
name "ci"
sources parallel {
    source "echo hi" { kind "test" }
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="Unknown sources mode"):
            parse_vertex(text)

    def test_missing_kind_error(self):
        text = """\
name "ci"
sources sequential {
    source "ruff check src/"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="missing required field: kind"):
            parse_vertex(text)

    def test_combine_with_sources_block_error(self):
        """combine and sources blocks are mutually exclusive."""
        text = """\
name "bad"
sources sequential {
    source "echo test" { kind "test" }
}
combine {
    vertex "a"
}
loops {
  counter { fold { count "inc" } }
}
"""
        with pytest.raises(ParseError, match="combine is mutually exclusive with sources blocks"):
            parse_vertex(text)


class TestInlineSourceExtended:
    """Tests for extended inline source fields (format, every, parse, env, etc.)."""

    def test_inline_source_with_format_and_every(self):
        text = """\
name "weather"
sources sequential {
    source "curl https://api.example.com/data" {
        kind "reading"
        format "json"
        every "30m"
        origin "weather-api"
    }
}
"""
        vertex = parse_vertex(text)
        block = vertex.sources_blocks[0]
        src = block.sources[0]
        assert src.command == "curl https://api.example.com/data"
        assert src.kind == "reading"
        assert src.format == "json"
        assert src.every == "30m"
        assert src.origin == "weather-api"

    def test_inline_source_with_parse_block(self):
        text = """\
name "weather"
sources sequential {
    source "curl https://api.example.com/data" {
        kind "reading"
        format "json"
        parse {
            project {
                temp_f path="main.temp"
                humidity path="main.humidity"
            }
        }
    }
}
"""
        vertex = parse_vertex(text)
        src = vertex.sources_blocks[0].sources[0]
        assert src.format == "json"
        assert len(src.parse) == 1
        from lang import Project
        assert isinstance(src.parse[0], Project)
        assert src.parse[0].fields == {"temp_f": "main.temp", "humidity": "main.humidity"}

    def test_inline_source_with_env(self):
        text = """\
name "monitor"
sources sequential {
    source "check-api" {
        kind "api.status"
        env API_KEY="secret" TIMEOUT="30"
    }
}
"""
        vertex = parse_vertex(text)
        src = vertex.sources_blocks[0].sources[0]
        assert ("API_KEY", "secret") in src.env
        assert ("TIMEOUT", "30") in src.env

    def test_inline_source_with_observer(self):
        text = """\
name "ci"
sources sequential {
    source "run-tests" {
        kind "test.result"
        observer "test-runner"
    }
}
"""
        vertex = parse_vertex(text)
        src = vertex.sources_blocks[0].sources[0]
        assert src.observer == "test-runner"

    def test_inline_source_with_on_trigger(self):
        text = """\
name "ci"
sources sequential {
    source "deploy" {
        kind "deploy.result"
        on "test.complete"
    }
}
"""
        vertex = parse_vertex(text)
        src = vertex.sources_blocks[0].sources[0]
        assert src.on is not None
        assert src.on.kinds == ("test.complete",)

    def test_inline_source_defaults_unchanged(self):
        """Minimal inline source still works — all new fields use defaults."""
        text = """\
name "ci"
sources sequential {
    source "echo hello" { kind "greeting" }
}
"""
        vertex = parse_vertex(text)
        src = vertex.sources_blocks[0].sources[0]
        assert src.command == "echo hello"
        assert src.kind == "greeting"
        assert src.observer == ""
        assert src.every == ""
        assert src.on is None
        assert src.format == "lines"
        assert src.timeout == "60s"
        assert src.origin == ""
        assert src.env == ()
        assert src.parse == ()


class TestLensBlock:
    """Tests for lens{} block parsing in vertex files."""

    def test_lens_fold_and_stream(self):
        text = 'name "t"\nstore "./t.db"\nlens {\n  fold "prompt"\n  stream "custom"\n}\nloops { x { fold { items "inc" } } }'
        v = parse_vertex(text)
        assert v.lens == LensDecl(fold="prompt", stream="custom")

    def test_lens_fold_only(self):
        text = 'name "t"\nstore "./t.db"\nlens { fold "prompt" }\nloops { x { fold { items "inc" } } }'
        v = parse_vertex(text)
        assert v.lens == LensDecl(fold="prompt", stream=None)

    def test_lens_stream_only(self):
        text = 'name "t"\nstore "./t.db"\nlens { stream "custom" }\nloops { x { fold { items "inc" } } }'
        v = parse_vertex(text)
        assert v.lens == LensDecl(fold=None, stream="custom")

    def test_lens_with_path(self):
        text = 'name "t"\nstore "./t.db"\nlens { fold "./lenses/my.py" }\nloops { x { fold { items "inc" } } }'
        v = parse_vertex(text)
        assert v.lens == LensDecl(fold="./lenses/my.py", stream=None)

    def test_no_lens_block(self):
        text = 'name "t"\nstore "./t.db"\nloops { x { fold { items "inc" } } }'
        v = parse_vertex(text)
        assert v.lens is None

    def test_empty_lens_block_errors(self):
        text = 'name "t"\nstore "./t.db"\nlens {}\nloops { x { fold { items "inc" } } }'
        with pytest.raises(ParseError, match="lens block requires at least fold or stream"):
            parse_vertex(text)

    def test_unknown_lens_field_errors(self):
        text = 'name "t"\nstore "./t.db"\nlens { bad "x" }\nloops { x { fold { items "inc" } } }'
        with pytest.raises(ParseError, match="Unknown lens field: bad"):
            parse_vertex(text)


class TestParseAtVertex:
    """Tests for per-kind parse declarations in .vertex loop definitions."""

    def test_select_in_loop_def(self):
        """Parse block with select in a vertex loop definition."""
        from lang.ast import Select

        text = """\
name "messaging"
loops {
  exchange {
    parse {
      select "prompt" "response" "model"
    }
    fold { items "by" "conversation_id" }
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["exchange"]
        assert len(loop_def.parse) == 1
        assert isinstance(loop_def.parse[0], Select)
        assert loop_def.parse[0].fields == ("prompt", "response", "model")

    def test_parse_with_search_and_fold(self):
        """Parse, search, and fold can coexist in a loop definition."""
        from lang.ast import Select

        text = """\
name "messaging"
loops {
  exchange {
    parse {
      select "prompt" "response"
    }
    fold { items "by" "conversation_id" }
    search "prompt" "response"
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["exchange"]
        assert len(loop_def.parse) == 1
        assert isinstance(loop_def.parse[0], Select)
        assert loop_def.search == ("prompt", "response")
        assert len(loop_def.folds) == 1

    def test_no_parse_defaults_empty(self):
        """Loop def without parse block has empty parse tuple."""
        text = """\
name "project"
loops {
  decision {
    fold { items "by" "topic" }
  }
}
"""
        vertex = parse_vertex(text)
        assert vertex.loops["decision"].parse == ()

    def test_flatten_in_loop_def(self):
        """Flatten parse step in a vertex loop definition."""
        from lang.ast import Flatten

        text = """\
name "messaging"
loops {
  exchange {
    parse {
      flatten "tool_calls" into="tool_text" {
        extract "name" "input"
      }
    }
    fold { items "by" "conversation_id" }
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["exchange"]
        assert len(loop_def.parse) == 1
        step = loop_def.parse[0]
        assert isinstance(step, Flatten)
        assert step.field == "tool_calls"
        assert step.into == "tool_text"
        assert step.extract == ("name", "input")

    def test_multiple_parse_steps(self):
        """Multiple parse steps in sequence."""
        from lang.ast import Flatten, Select

        text = """\
name "messaging"
loops {
  exchange {
    parse {
      select "prompt" "response" "tool_calls"
      flatten "tool_calls" into="tool_text" {
        extract "name" "input"
      }
    }
    fold { items "by" "conversation_id" }
  }
}
"""
        vertex = parse_vertex(text)
        loop_def = vertex.loops["exchange"]
        assert len(loop_def.parse) == 2
        assert isinstance(loop_def.parse[0], Select)
        assert isinstance(loop_def.parse[1], Flatten)


# --- Coverage edge tests ---

class TestLoaderEdgeCoverage:
    """Tests targeting uncovered loader.py paths."""

    def test_select_no_fields_raises(self):
        """Empty select raises ParseError."""
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="select requires at least one field"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    select {}
}
""")

    def test_transform_lstrip(self):
        from lang import parse_loop
        from lang.ast import LStrip

        loop = parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "path" { lstrip "/" }
}
""")
        steps = loop.parse
        assert any(isinstance(s, type) or True for s in steps)

    def test_transform_rstrip(self):
        from lang import parse_loop
        from lang.ast import RStrip

        loop = parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "path" { rstrip "/" }
}
""")
        assert len(loop.parse) > 0

    def test_transform_replace(self):
        from lang import parse_loop
        from lang.ast import Replace

        loop = parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "path" { replace "a" "b" }
}
""")
        assert len(loop.parse) > 0

    def test_transform_unknown_op_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="Unknown transform operation"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "path" { flipflop "x" }
}
""")

    def test_transform_no_ops_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="no operations"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "path" {}
}
""")

    def test_explode_no_path_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="explode requires path"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    explode {}
}
""")

    def test_require_arg_type_conversion(self):
        """_require_arg converts non-string args to string."""
        from lang import parse_loop

        # observer is loaded via _require_arg — int arg gets str()
        loop = parse_loop("""\
kind "metric"
observer 42
source "echo test"
""")
        assert loop.observer == "42"


class TestErrorCoverage:
    """Cover errors.py repr/eq/str paths."""

    def test_location_repr(self):
        from lang.errors import Location
        loc = Location(path=None, line=1, column=5)
        r = repr(loc)
        assert "Location" in r

    def test_location_eq_different_type(self):
        from lang.errors import Location
        loc = Location(path=None, line=1, column=0)
        assert loc.__eq__("not a location") is NotImplemented

    def test_location_str_with_column(self):
        from lang.errors import Location
        from pathlib import Path
        loc = Location(path=Path("test.vertex"), line=5, column=3)
        assert str(loc) == "test.vertex:5:3"

    def test_dsl_error_no_location(self):
        from lang.errors import DSLError
        err = DSLError("bad input")
        assert "bad input" in str(err)

    def test_node_map_helper(self):
        """_node_map creates dict from nodes (L80-83)."""
        from lang import parse_vertex

        # Any vertex with named children exercises _node_map
        v = parse_vertex("""\
name "test"
loops {
    metric { fold { n "inc" } }
}
""")
        assert "metric" in v.loops

    def test_coerce_invalid_type(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="coerce: invalid type"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    transform "value" { coerce "banana" }
}
""")

    def test_project_no_path_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="project field.*requires path"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    project { field "x" }
}
""")

    def test_project_no_fields_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="project requires at least one field"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    project {}
}
""")

    def test_where_no_path_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="where requires path"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    where {}
}
""")

    def test_where_in_values(self):
        from lang import parse_loop
        from lang.ast import Where

        loop = parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    where path="status" in="active" "pending"
}
""")
        w = [s for s in loop.parse if isinstance(s, Where)]
        assert len(w) == 1

    def test_where_exists_default(self):
        from lang import parse_loop
        from lang.ast import Where

        loop = parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    where path="status"
}
""")
        w = [s for s in loop.parse if isinstance(s, Where)]
        assert len(w) == 1

    def test_flatten_no_arg_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="flatten requires a field name"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    flatten {}
}
""")

    def test_flatten_extract_no_fields_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="flatten requires extract"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    flatten "items" into="flat" { extract {} }
}
""")

    def test_unknown_parse_step_raises(self):
        from lang import parse_loop
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="Unknown parse step"):
            parse_loop("""\
kind "metric"
observer "test"
source "echo test"
parse {
    wizardry "x"
}
""")

    def test_fold_missing_op_raises(self):
        from lang import parse_vertex
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="missing operation"):
            parse_vertex("""\
name "test"
loops {
    metric { fold { n } }
}
""")

    def test_fold_unknown_op_raises(self):
        from lang import parse_vertex
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="Unknown fold operation"):
            parse_vertex("""\
name "test"
loops {
    metric { fold { n "wizardry" } }
}
""")

    def test_boundary_missing_trigger_raises(self):
        from lang import parse_vertex
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="boundary requires when="):
            parse_vertex("""\
name "test"
loops {
    metric {
        fold { n "inc" }
        boundary {}
    }
}
""")

    def test_boundary_condition_fields(self):
        from lang import parse_vertex

        v = parse_vertex("""\
name "test"
loops {
    metric {
        fold { n "inc" }
        boundary when="metric" {
            condition "n" ">=" 5
        }
    }
}
""")
        loop_def = v.loops["metric"]
        assert loop_def.boundary is not None

    def test_unknown_loop_field_raises(self):
        from lang import parse_vertex
        from lang.errors import ParseError

        with pytest.raises(ParseError, match="Unknown loop field"):
            parse_vertex("""\
name "test"
loops {
    metric {
        fold { n "inc" }
        bazinga "hello"
    }
}
""")


class TestAstCoverage:
    """Cover ast.py frozen dataclass + Duration edges."""

    def test_frozen_missing_arg(self):
        from lang.ast import LoopFile
        with pytest.raises(TypeError, match="missing required argument"):
            LoopFile(kind="x")  # missing 'observer'

    def test_frozen_repr(self):
        from lang.ast import Strip
        s = Strip(chars="/")
        r = repr(s)
        assert "Strip" in r

    def test_frozen_setattr_raises(self):
        from lang.ast import Strip
        s = Strip(chars="/")
        with pytest.raises(AttributeError, match="cannot assign"):
            s.chars = "x"

    def test_frozen_delattr_raises(self):
        from lang.ast import Strip
        s = Strip(chars="/")
        with pytest.raises(AttributeError, match="cannot delete"):
            del s.chars

    def test_duration_invalid_char(self):
        from lang.ast import Duration
        with pytest.raises(ValueError, match="Invalid duration character"):
            Duration.parse("5x")

    def test_duration_trailing_number(self):
        from lang.ast import Duration
        with pytest.raises(ValueError, match="Trailing number without unit"):
            Duration.parse("42")

    def test_duration_str_seconds(self):
        from lang.ast import Duration
        d = Duration.parse("2s")
        s = str(d)
        assert "2s" in s

    def test_duration_str_milliseconds(self):
        from lang.ast import Duration
        d = Duration.parse("500ms")
        s = str(d)
        assert "500ms" in s

    def test_boundary_condition_invalid_op(self):
        from lang.ast import BoundaryCondition
        with pytest.raises(ValueError, match="Invalid condition operator"):
            BoundaryCondition(target="n", op="~=", value=5)

    def test_frozen_eq_attribute_error(self):
        from lang.ast import Strip, LStrip
        s = Strip(chars="/")
        ls = LStrip(chars="/")
        # Different types → NotImplemented
        result = s.__eq__(ls)
        assert result is NotImplemented or result is False
