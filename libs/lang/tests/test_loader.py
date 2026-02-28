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
