"""Tests for vertex compiler (DSL → runtime)."""

from pathlib import Path

import pytest
from atoms import Avg, Boundary, Collect, Count, Field, Latest, Max, Min, Source, Spec, Sum, Upsert, Window
from atoms import Coerce as RuntimeCoerce
from atoms import Pick as RuntimePick
from atoms import Rename as RuntimeRename
from atoms import Skip as RuntimeSkip
from atoms import Split as RuntimeSplit
from atoms import Transform as RuntimeTransform

from lang import parse_loop, parse_vertex
from vertex.compiler import (
    CircularVertexError,
    CompiledVertex,
    compile_loop,
    compile_sources,
    compile_vertex,
    compile_vertex_recursive,
    instantiate_template,
    map_fold_op,
    map_parse_steps,
    map_pick,
    map_skip,
    map_split,
    map_transform,
    substitute_vars,
)
from lang.ast import (
    Coerce,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
    Pick,
    Skip,
    Split,
    Strip,
    Transform,
    Trigger,
)
from lang.ast import Explode as DslExplode
from lang.ast import Project as DslProject
from lang.ast import Where as DslWhere

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseStepMapping:
    """Parse step to runtime ParseOp mapping."""

    def test_skip_startswith(self):
        """Skip with ^ maps to startswith."""
        step = Skip(pattern="^Filesystem")
        result = map_skip(step)
        assert isinstance(result, RuntimeSkip)
        assert result.startswith == "Filesystem"
        assert result.contains is None

    def test_skip_contains(self):
        """Skip without ^ maps to contains."""
        step = Skip(pattern="/System/Volumes")
        result = map_skip(step)
        assert isinstance(result, RuntimeSkip)
        assert result.contains == "/System/Volumes"
        assert result.startswith is None

    def test_split_whitespace(self):
        """Split without delimiter maps to whitespace split."""
        step = Split(delimiter=None)
        result = map_split(step)
        assert isinstance(result, RuntimeSplit)
        assert result.delim is None

    def test_split_delimiter(self):
        """Split with delimiter maps correctly."""
        step = Split(delimiter=":")
        result = map_split(step)
        assert isinstance(result, RuntimeSplit)
        assert result.delim == ":"

    def test_pick_indices_only(self):
        """Pick without names maps to Pick only."""
        step = Pick(indices=(0, 4, 8), names=None)
        pick, rename = map_pick(step)
        assert isinstance(pick, RuntimePick)
        assert pick.indices == (0, 4, 8)
        assert rename is None

    def test_pick_with_names(self):
        """Pick with names maps to Pick + Rename."""
        step = Pick(indices=(0, 4, 5), names=("fs", "pct", "mount"))
        pick, rename = map_pick(step)
        assert isinstance(pick, RuntimePick)
        assert pick.indices == (0, 4, 5)
        assert isinstance(rename, RuntimeRename)
        assert dict(rename.mapping) == {0: "fs", 1: "pct", 2: "mount"}

    def test_transform_strip(self):
        """Transform with strip maps to RuntimeTransform."""
        step = Transform(field="pct", operations=(Strip(chars="%"),))
        result = map_transform(step)
        assert len(result) == 1
        assert isinstance(result[0], RuntimeTransform)
        assert result[0].field == "pct"
        assert result[0].strip == "%"

    def test_transform_coerce(self):
        """Transform with coerce maps to RuntimeCoerce."""
        step = Transform(field="pct", operations=(Coerce(type="int"),))
        result = map_transform(step)
        assert len(result) == 1
        assert isinstance(result[0], RuntimeCoerce)
        assert result[0].types["pct"] is int

    def test_transform_chain(self):
        """Transform chain maps to Transform + Coerce."""
        step = Transform(field="pct", operations=(Strip(chars="%"), Coerce(type="int")))
        result = map_transform(step)
        assert len(result) == 2
        assert isinstance(result[0], RuntimeTransform)
        assert result[0].strip == "%"
        assert isinstance(result[1], RuntimeCoerce)
        assert result[1].types["pct"] is int


class TestFoldOpMapping:
    """Fold op to runtime FoldOp mapping."""

    def test_fold_by(self):
        """FoldBy maps to Upsert."""
        result = map_fold_op("mounts", FoldBy(key_field="mount"))
        assert isinstance(result, Upsert)
        assert result.target == "mounts"
        assert result.key == "mount"

    def test_fold_count(self):
        """FoldCount maps to Count."""
        result = map_fold_op("events", FoldCount())
        assert isinstance(result, Count)
        assert result.target == "events"

    def test_fold_sum(self):
        """FoldSum maps to Sum."""
        result = map_fold_op("total", FoldSum(field="amount"))
        assert isinstance(result, Sum)
        assert result.target == "total"
        assert result.field == "amount"

    def test_fold_latest(self):
        """FoldLatest maps to Latest."""
        result = map_fold_op("updated", FoldLatest())
        assert isinstance(result, Latest)
        assert result.target == "updated"

    def test_fold_collect(self):
        """FoldCollect maps to Collect."""
        result = map_fold_op("history", FoldCollect(max_items=100))
        assert isinstance(result, Collect)
        assert result.target == "history"
        assert result.max == 100

    def test_fold_max(self):
        """FoldMax maps to Max."""
        result = map_fold_op("peak", FoldMax(field="memory"))
        assert isinstance(result, Max)
        assert result.target == "peak"
        assert result.field == "memory"

    def test_fold_min(self):
        """FoldMin maps to Min."""
        result = map_fold_op("coldest", FoldMin(field="temp"))
        assert isinstance(result, Min)
        assert result.target == "coldest"
        assert result.field == "temp"

    def test_fold_avg(self):
        """FoldAvg maps to Avg."""
        result = map_fold_op("rate", FoldAvg(field="latency"))
        assert isinstance(result, Avg)
        assert result.target == "rate"
        assert result.field == "latency"

    def test_fold_window(self):
        """FoldWindow maps to Window."""
        result = map_fold_op("intervals", FoldWindow(field="interval", size=10))
        assert isinstance(result, Window)
        assert result.target == "intervals"
        assert result.field == "interval"
        assert result.size == 10


class TestCompileLoop:
    """LoopFile to Source compilation."""

    def test_minimal_loop(self):
        """Minimal loop compiles to Source."""
        loop = parse_loop("""\
source "whoami"
kind "identity"
observer "shell"
""")
        source = compile_loop(loop)
        assert isinstance(source, Source)
        assert source.command == "whoami"
        assert source.kind == "identity"
        assert source.observer == "shell"
        assert source.every is None
        assert source.format == "lines"
        assert source.parse is None

    def test_loop_with_every(self):
        """Loop with every compiles to Source with interval."""
        loop = parse_loop("""\
source "date"
kind "heartbeat"
observer "timer"
every "5s"
""")
        source = compile_loop(loop)
        assert source.every == 5.0

    def test_loop_with_parse(self):
        """Loop with parse pipeline compiles to Source with parse ops."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  skip "^Filesystem"
  split
  pick 0 4 {
    names "fs" "pct"
  }
  transform "pct" {
    strip "%"
    coerce "int"
  }
}
""")
        source = compile_loop(loop)
        assert source.parse is not None
        assert len(source.parse) == 6  # skip, split, pick, rename, transform, coerce
        # Verify types
        assert isinstance(source.parse[0], RuntimeSkip)
        assert isinstance(source.parse[1], RuntimeSplit)
        assert isinstance(source.parse[2], RuntimePick)
        assert isinstance(source.parse[3], RuntimeRename)
        assert isinstance(source.parse[4], RuntimeTransform)
        assert isinstance(source.parse[5], RuntimeCoerce)

    def test_loop_from_fixture(self):
        """Full fixture loop compiles correctly."""
        from lang import parse_loop_file

        loop = parse_loop_file(FIXTURES / "disk.loop")
        source = compile_loop(loop)
        assert source.command == "df -h"
        assert source.every == 5.0
        assert source.parse is not None


class TestCompileVertex:
    """VertexFile to Spec compilation."""

    def test_minimal_vertex(self):
        """Minimal vertex compiles to Spec dict."""
        vertex = parse_vertex("""\
name "simple"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        specs = compile_vertex(vertex)
        assert "counter" in specs
        spec = specs["counter"]
        assert isinstance(spec, Spec)
        assert spec.name == "counter"
        assert len(spec.folds) == 1
        assert isinstance(spec.folds[0], Count)

    def test_vertex_with_boundary(self):
        """Vertex with boundary compiles to Spec with Boundary."""
        vertex = parse_vertex("""\
name "test"
loops {
  events {
    fold {
      count "inc"
    }
    boundary when="batch.complete"
  }
}
""")
        specs = compile_vertex(vertex)
        spec = specs["events"]
        assert spec.boundary is not None
        assert isinstance(spec.boundary, Boundary)
        assert spec.boundary.kind == "batch.complete"
        assert spec.boundary.mode == "when"

    def test_vertex_with_boundary_after(self):
        """Vertex with count-based boundary (after N)."""
        vertex = parse_vertex("""\
name "test"
loops {
  batch {
    fold {
      count "inc"
    }
    boundary after=10
  }
}
""")
        specs = compile_vertex(vertex)
        spec = specs["batch"]
        assert spec.boundary is not None
        assert spec.boundary.count == 10
        assert spec.boundary.mode == "after"

    def test_vertex_with_boundary_every(self):
        """Vertex with count-based boundary (every N)."""
        vertex = parse_vertex("""\
name "test"
loops {
  windowed {
    fold {
      total "sum" "amount"
    }
    boundary every=100
  }
}
""")
        specs = compile_vertex(vertex)
        spec = specs["windowed"]
        assert spec.boundary is not None
        assert spec.boundary.count == 100
        assert spec.boundary.mode == "every"

    def test_vertex_state_fields(self):
        """Vertex compiles with inferred state fields."""
        vertex = parse_vertex("""\
name "test"
loops {
  metrics {
    fold {
      mounts "by" "mount"
      count "inc"
      total "sum" "amount"
      updated "latest"
      history "collect" 100
      peak "max" "memory"
      coldest "min" "temp"
    }
  }
}
""")
        specs = compile_vertex(vertex)
        spec = specs["metrics"]

        # Check state fields were created with correct types
        field_types = {f.name: f.kind for f in spec.state_fields}
        assert field_types["mounts"] == "dict"
        assert field_types["count"] == "int"
        assert field_types["total"] == "float"
        assert field_types["updated"] == "datetime"
        assert field_types["history"] == "list"
        assert field_types["peak"] == "float"
        assert field_types["coldest"] == "float"

    def test_vertex_from_fixture(self):
        """Full fixture vertex compiles correctly."""
        from lang import parse_vertex_file

        vertex = parse_vertex_file(FIXTURES / "system.vertex")
        specs = compile_vertex(vertex)
        assert "disk" in specs
        assert "memory" in specs

        disk = specs["disk"]
        assert len(disk.folds) == 2
        assert isinstance(disk.folds[0], Upsert)  # mounts: by mount
        assert isinstance(disk.folds[1], Latest)  # updated: latest


class TestIntegration:
    """End-to-end integration tests."""

    def test_parse_pipeline_execution(self):
        """Compiled parse pipeline executes correctly."""
        from atoms import run_parse

        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  skip "^Filesystem"
  split
  pick 0 1 {
    names "fs" "pct"
  }
  transform "pct" {
    strip "%"
    coerce "int"
  }
}
""")
        source = compile_loop(loop)

        # Test the parse pipeline
        result = run_parse("Filesystem  Use%  Mount", source.parse)
        assert result is None  # Skipped by ^Filesystem

        result = run_parse("/dev/disk1  27%  /", source.parse)
        assert result is not None
        assert result["fs"] == "/dev/disk1"
        assert result["pct"] == 27
        assert isinstance(result["pct"], int)

    def test_spec_apply(self):
        """Compiled Spec.apply executes correctly."""
        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
      total "sum" "value"
    }
  }
}
""")
        specs = compile_vertex(vertex)
        spec = specs["counter"]

        # Initialize state
        state = spec.initial_state()
        assert state["count"] == 0
        assert state["total"] == 0

        # Apply some payloads
        state = spec.apply(state, {"value": 10, "_ts": 1234567890})
        assert state["count"] == 1
        assert state["total"] == 10

        state = spec.apply(state, {"value": 20, "_ts": 1234567891})
        assert state["count"] == 2
        assert state["total"] == 30


class TestTriggeredSource:
    """Triggered source compilation (on: syntax)."""

    def test_single_trigger(self):
        """Loop with single on: trigger compiles to Source with trigger."""
        loop = parse_loop("""\
source "process-batch"
kind "processed"
observer "worker"
on "batch.ready"
""")
        source = compile_loop(loop)
        assert isinstance(source, Source)
        assert source.command == "process-batch"
        assert source.trigger == ("batch.ready",)
        assert source.every is None

    def test_multiple_triggers(self):
        """Loop with multiple on: triggers compiles to Source with trigger tuple."""
        loop = parse_loop("""\
source "aggregate"
kind "aggregated"
observer "collector"
on "minute" "hour" "day"
""")
        source = compile_loop(loop)
        assert source.trigger == ("minute", "hour", "day")
        assert source.every is None

    def test_polling_source_no_trigger(self):
        """Loop with every: but no on: has no trigger."""
        loop = parse_loop("""\
source "check-health"
kind "health"
observer "monitor"
every "30s"
""")
        source = compile_loop(loop)
        assert source.trigger is None
        assert source.every == 30.0


class TestPureTimerSource:
    """Pure timer source compilation (every: without source:)."""

    def test_pure_timer(self):
        """Loop with every: but no source: compiles to pure timer Source."""
        loop = parse_loop("""\
kind "tick"
observer "timer"
every "1m"
""")
        source = compile_loop(loop)
        assert isinstance(source, Source)
        assert source.command is None
        assert source.every == 60.0
        assert source.kind == "tick"

    def test_pure_timer_with_trigger(self):
        """Loop with every: and on: compiles to triggered timer."""
        loop = parse_loop("""\
kind "batch.tick"
observer "scheduler"
every "1m"
on "minute"
""")
        source = compile_loop(loop)
        assert source.command is None
        assert source.trigger == ("minute",)
        assert source.every == 60.0


class TestNestedVertexCompilation:
    """Recursive vertex compilation."""

    def test_simple_vertex_recursive(self):
        """Simple vertex without children compiles recursively."""
        vertex = parse_vertex("""\
name "simple"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        assert isinstance(compiled, CompiledVertex)
        assert compiled.name == "simple"
        assert "counter" in compiled.specs
        assert compiled.children == {}

    def test_vertex_with_children(self, tmp_path):
        """Vertex with vertices: compiles children recursively."""
        # Create child vertex file
        child_path = tmp_path / "child.vertex"
        child_path.write_text("""\
name "child"
loops {
  events {
    fold {
      count "inc"
    }
  }
}
""")

        # Create parent vertex file
        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(f"""\
name "parent"
vertices "{child_path}"
loops {{
  aggregate {{
    fold {{
      total "inc"
    }}
  }}
}}
""")

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert compiled.name == "parent"
        assert "aggregate" in compiled.specs
        assert "child" in compiled.children
        assert compiled.children["child"].name == "child"
        assert "events" in compiled.children["child"].specs

    def test_circular_vertex_detection(self, tmp_path):
        """Circular vertex references raise CircularVertexError."""
        a_path = tmp_path / "a.vertex"
        b_path = tmp_path / "b.vertex"

        a_path.write_text(f"""\
name "a"
vertices "{b_path}"
loops {{
  x {{
    fold {{
      count "inc"
    }}
  }}
}}
""")
        b_path.write_text(f"""\
name "b"
vertices "{a_path}"
loops {{
  y {{
    fold {{
      count "inc"
    }}
  }}
}}
""")

        from lang import parse_vertex_file

        a_ast = parse_vertex_file(a_path)
        with pytest.raises(CircularVertexError):
            compile_vertex_recursive(a_ast)

    def test_relative_path_resolution(self, tmp_path):
        """Child paths are resolved relative to parent vertex file."""
        subdir = tmp_path / "sub"
        subdir.mkdir()
        child_path = subdir / "child.vertex"
        child_path.write_text(
            'name "child"\n'
            "loops {\n"
            "  events {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(
            'name "parent"\n'
            'vertices "./sub/child.vertex"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "child" in compiled.children


class TestDiscoverVertices:
    """Vertex discovery via glob patterns."""

    def test_discover_vertices_simple(self, tmp_path):
        """discover: pattern finds .vertex files."""
        infra = tmp_path / "infra"
        infra.mkdir()
        (infra / "disk.vertex").write_text(
            'name "disk"\n'
            "loops {\n"
            "  usage {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        (infra / "proc.vertex").write_text(
            'name "proc"\n'
            "loops {\n"
            "  count {\n"
            "    fold {\n"
            '      total "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./infra/*.vertex"\n'
            "loops {\n"
            "  system {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert compiled.name == "root"
        assert "disk" in compiled.children
        assert "proc" in compiled.children

    def test_discover_vertices_recursive(self, tmp_path):
        """Recursive glob **/*.vertex finds nested vertices."""
        level1 = tmp_path / "level1"
        level1.mkdir()
        level2 = level1 / "level2"
        level2.mkdir()

        (level1 / "a.vertex").write_text(
            'name "a"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        (level2 / "b.vertex").write_text(
            'name "b"\n'
            "loops {\n"
            "  y {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./**/*.vertex"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "a" in compiled.children
        assert "b" in compiled.children

    def test_discover_skips_self(self, tmp_path):
        """discover: pattern does not include the vertex file itself."""
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./*.vertex"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "root" not in compiled.children
        assert compiled.children == {}

    def test_discover_combined_with_vertices(self, tmp_path):
        """discover: and vertices: can be used together."""
        infra = tmp_path / "infra"
        infra.mkdir()
        (infra / "disk.vertex").write_text(
            'name "disk"\n'
            "loops {\n"
            "  usage {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        explicit = tmp_path / "explicit.vertex"
        explicit.write_text(
            'name "explicit"\n'
            "loops {\n"
            "  events {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./infra/*.vertex"\n'
            f'vertices "{explicit}"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "disk" in compiled.children  # discovered
        assert "explicit" in compiled.children  # explicit

    def test_discover_avoids_duplicates(self, tmp_path):
        """If same vertex is in vertices: and discover:, only included once."""
        (tmp_path / "child.vertex").write_text(
            'name "child"\n'
            "loops {\n"
            "  events {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./*.vertex"\n'
            f'vertices "{tmp_path / "child.vertex"}"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert len(compiled.children) == 1
        assert "child" in compiled.children

    def test_discover_circular_detection(self, tmp_path):
        """Circular references via discover: still detected."""
        a_dir = tmp_path / "a_dir"
        b_dir = tmp_path / "b_dir"
        a_dir.mkdir()
        b_dir.mkdir()

        a_path = a_dir / "a.vertex"
        b_path = b_dir / "b.vertex"

        a_path.write_text(
            'name "a"\n'
            f'discover "{b_dir}/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        b_path.write_text(
            'name "b"\n'
            f'discover "{a_dir}/*.vertex"\n'
            "loops {\n"
            "  y {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        a_ast = parse_vertex_file(a_path)
        with pytest.raises(CircularVertexError):
            compile_vertex_recursive(a_ast)

    def test_discover_only_vertex_files(self, tmp_path):
        """discover: pattern only includes .vertex files, not .loop files."""
        (tmp_path / "child.vertex").write_text(
            'name "child"\n'
            "loops {\n"
            "  events {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )
        (tmp_path / "source.loop").write_text(
            'source "echo test"\n'
            'kind "test"\n'
            'observer "shell"\n'
        )

        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            'name "root"\n'
            'discover "./*"\n'
            "loops {\n"
            "  main {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        from lang import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "child" in compiled.children
        assert len(compiled.children) == 1


class TestMaterializeVertex:
    """Vertex tree materialization."""

    def test_materialize_simple(self):
        """Simple vertex materializes to runtime Vertex."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "counter"
loops {
  events {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        assert runtime.name == "counter"
        assert "events" in runtime.kinds
        assert runtime.state("events") == {"count": 0}

        # Fold a fact
        from atoms import Fact

        fact = Fact.of("events", "test", value=1)
        runtime.receive(fact)
        assert runtime.state("events") == {"count": 1}

    def test_materialize_with_boundary(self):
        """Vertex with boundary emits tick on boundary fact."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "batcher"
loops {
  batch {
    fold {
      count "inc"
    }
    boundary when="batch.done"
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        from atoms import Fact

        # Regular facts fold
        runtime.receive(Fact.of("batch", "test", value=1))
        runtime.receive(Fact.of("batch", "test", value=2))
        assert runtime.state("batch") == {"count": 2}

        # Boundary fact triggers tick (payload threads through as _boundary)
        tick = runtime.receive(Fact.of("batch.done", "test"))
        assert tick is not None
        assert tick.name == "batch"
        assert tick.payload["count"] == 2
        assert "_boundary" in tick.payload

        # State was reset
        assert runtime.state("batch") == {"count": 0}

    def test_materialize_with_fold_override(self):
        """Custom fold functions override Spec.apply."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "custom"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)

        def custom_fold(state, payload):
            return {"count": state["count"] + payload.get("value", 1) * 2}

        runtime = materialize_vertex(compiled, fold_overrides={
            "counter": ({"count": 0}, custom_fold),
        })

        from atoms import Fact

        runtime.receive(Fact.of("counter", "test", value=5))
        assert runtime.state("counter") == {"count": 10}

        runtime.receive(Fact.of("counter", "test", value=3))
        assert runtime.state("counter") == {"count": 16}

    def test_materialize_nested(self, tmp_path):
        """Nested vertices materialize with add_child."""
        from vertex.compiler import materialize_vertex
        from lang import parse_vertex_file

        child_path = tmp_path / "child.vertex"
        child_path.write_text("""\
name "child"
loops {
  events {
    fold {
      count "inc"
    }
    boundary when="events.done"
  }
}
emit "child.tick"
""")

        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(f"""\
name "parent"
vertices "{child_path}"
loops {{
  aggregate {{
    fold {{
      total "inc"
    }}
  }}
}}
""")

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)
        runtime = materialize_vertex(compiled)

        assert runtime.name == "parent"
        assert len(runtime.children) == 1
        assert runtime.children[0].name == "child"

    def test_materialize_nested_tick_flow(self, tmp_path):
        """Child ticks become facts to parent via automatic wiring."""
        from vertex.compiler import materialize_vertex
        from lang import parse_vertex_file

        child_path = tmp_path / "pulse.vertex"
        child_path.write_text("""\
name "pulse"
loops {
  pulse {
    fold {
      count "inc"
    }
    boundary when="pulse.done"
  }
}
""")

        parent_path = tmp_path / "breath.vertex"
        parent_path.write_text(f"""\
name "breath"
vertices "{child_path}"
loops {{
  breath {{
    fold {{
      pulses "inc"
    }}
  }}
}}
""")

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        def pulse_fold(state, payload):
            return {"count": state["count"] + 1}

        runtime = materialize_vertex(compiled, fold_overrides={
            "pulse": ({"count": 0}, pulse_fold),
        })

        from atoms import Fact

        runtime.receive(Fact.of("pulse", "test"))
        runtime.receive(Fact.of("pulse", "test"))
        runtime.receive(Fact.of("pulse", "test"))

        child = runtime.children[0]
        assert child.state("pulse") == {"count": 3}


class TestNewParseStepMapping:
    """Mapping for Explode, Project, Where DSL steps to runtime ops."""

    def test_explode_mapping(self):
        from vertex.compiler import map_explode
        from atoms import Explode as RuntimeExplode

        step = DslExplode(path="data.alerts", carry={"name": "group_name"})
        result = map_explode(step)
        assert isinstance(result, RuntimeExplode)
        assert result.path == "data.alerts"
        assert result.carry == {"name": "group_name"}

    def test_project_mapping(self):
        from vertex.compiler import map_project
        from atoms import Project as RuntimeProject

        step = DslProject(fields={"alertname": "labels.alertname", "state": "state"})
        result = map_project(step)
        assert isinstance(result, RuntimeProject)
        assert result.fields == {"alertname": "labels.alertname", "state": "state"}

    def test_where_mapping(self):
        from vertex.compiler import map_where
        from atoms import Where as RuntimeWhere

        step = DslWhere(path="status", op="equals", value="success")
        result = map_where(step)
        assert isinstance(result, RuntimeWhere)
        assert result.path == "status"
        assert result.op == "equals"
        assert result.value == "success"

    def test_map_parse_steps_with_new_ops(self):
        """map_parse_steps handles mixed pipeline with new ops."""
        from atoms import Explode as RuntimeExplode
        from atoms import Project as RuntimeProject
        from atoms import Where as RuntimeWhere

        steps = (
            DslWhere(path="status", op="equals", value="success"),
            DslExplode(path="data.alerts"),
            DslProject(fields={"name": "labels.alertname"}),
        )
        result = map_parse_steps(steps)
        assert len(result) == 3
        assert isinstance(result[0], RuntimeWhere)
        assert isinstance(result[1], RuntimeExplode)
        assert isinstance(result[2], RuntimeProject)


class TestStoreWiring:
    """Store path flows through compilation to materialized Vertex."""

    def test_compiled_vertex_preserves_store(self):
        """CompiledVertex carries store path from AST."""
        vertex = parse_vertex("""\
name "test"
store "./data/test.jsonl"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        assert compiled.store == Path("./data/test.jsonl")

    def test_compiled_vertex_no_store(self):
        """CompiledVertex store is None when not specified."""
        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        assert compiled.store is None

    def test_materialize_with_store(self, tmp_path):
        """materialize_vertex creates Vertex with EventStore when store is set."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        compiled.store = tmp_path / "test.jsonl"

        runtime = materialize_vertex(compiled)
        assert runtime._store is not None

        # Verify store works by receiving a fact
        from atoms import Fact

        runtime.receive(Fact.of("counter", "test", value=1))
        assert runtime.state("counter") == {"count": 1}

        # Verify JSONL file was written
        assert compiled.store.exists()
        lines = compiled.store.read_text().strip().split("\n")
        assert len(lines) == 1


class TestTemplateInstantiation:
    """Template variable substitution and instantiation."""

    def test_substitute_vars_basic(self):
        """Basic variable substitution."""
        result = substitute_vars("Hello ${name}!", {"name": "World"})
        assert result == "Hello World!"

    def test_substitute_vars_multiple(self):
        """Multiple variables in same string."""
        result = substitute_vars(
            "ssh deploy@${host} 'cd /opt/${kind} && docker compose ps'",
            {"host": "192.168.1.30", "kind": "infra"},
        )
        assert result == "ssh deploy@192.168.1.30 'cd /opt/infra && docker compose ps'"

    def test_substitute_vars_unmatched(self):
        """Unmatched variables are preserved."""
        result = substitute_vars("${foo} and ${bar}", {"foo": "replaced"})
        assert result == "replaced and ${bar}"

    def test_substitute_vars_no_vars(self):
        """String without variables passes through."""
        result = substitute_vars("no variables here", {"foo": "bar"})
        assert result == "no variables here"

    def test_instantiate_template(self):
        """Instantiate a LoopFile with variable substitution."""
        from lang.ast import LoopFile

        template = LoopFile(
            kind="${kind}",
            observer="hlab",
            source='ssh deploy@${host} "cd /opt/${kind} && docker compose ps"',
            format="ndjson",
        )
        params = {"kind": "infra", "host": "192.168.1.30"}

        result = instantiate_template(template, params)

        assert result.kind == "infra"
        assert result.observer == "hlab"  # unchanged
        assert result.source == 'ssh deploy@192.168.1.30 "cd /opt/infra && docker compose ps"'
        assert result.format == "ndjson"  # unchanged

    def test_compile_sources_simple_paths(self, tmp_path):
        """compile_sources handles simple path entries."""
        loop_path = tmp_path / "test.loop"
        loop_path.write_text("""\
source "echo hello"
kind "test"
observer "shell"
""")
        from lang import parse_vertex

        vertex = parse_vertex(f"""\
name "test"
sources {{
  path "{loop_path}"
}}
loops {{
  test {{
    fold {{
      count "inc"
    }}
  }}
}}
""")
        sources, specs = compile_sources(vertex, tmp_path)

        assert len(sources) == 1
        assert sources[0].command == "echo hello"
        assert sources[0].kind == "test"
        assert specs == {}

    def test_compile_sources_template(self, tmp_path):
        """compile_sources handles template entries."""
        template_path = tmp_path / "status.loop"
        template_path.write_text("""\
source #"ssh deploy@${host} "cd /opt/${kind} && docker compose ps""#
kind "${kind}"
observer "hlab"
format "ndjson"
""")
        from lang import parse_vertex

        vertex = parse_vertex(f"""\
name "status"
sources {{
  template "{template_path}" {{
    with kind="infra" host="192.168.1.30"
    with kind="media" host="192.168.1.40"
  }}
}}
loops {{
  infra {{
    fold {{
      count "inc"
    }}
  }}
  media {{
    fold {{
      count "inc"
    }}
  }}
}}
""")
        sources, specs = compile_sources(vertex, tmp_path)

        assert len(sources) == 2
        assert sources[0].kind == "infra"
        assert sources[0].command == 'ssh deploy@192.168.1.30 "cd /opt/infra && docker compose ps"'
        assert sources[1].kind == "media"
        assert sources[1].command == 'ssh deploy@192.168.1.40 "cd /opt/media && docker compose ps"'
        assert specs == {}

    def test_compile_sources_template_with_loop_spec(self, tmp_path):
        """compile_sources generates specs from template loop: block."""
        template_path = tmp_path / "status.loop"
        template_path.write_text("""\
source #"ssh deploy@${host} "cd /opt/${kind} && docker compose ps""#
kind "${kind}"
observer "hlab"
format "ndjson"
""")
        from lang import parse_vertex

        vertex = parse_vertex(f"""\
name "status"
sources {{
  template "{template_path}" {{
    with kind="infra" host="192.168.1.30"
    with kind="media" host="192.168.1.40"
    loop {{
      fold {{
        containers "collect" 50
      }}
      boundary when="${{kind}}.complete"
    }}
  }}
}}
loops {{
  test {{
    fold {{
      count "inc"
    }}
  }}
}}
""")
        sources, specs = compile_sources(vertex, tmp_path)

        assert len(sources) == 2
        assert "infra" in specs
        assert "media" in specs

        infra_spec = specs["infra"]
        assert infra_spec.name == "infra"
        assert len(infra_spec.folds) == 1
        assert infra_spec.boundary is not None
        assert infra_spec.boundary.kind == "infra.complete"

        media_spec = specs["media"]
        assert media_spec.name == "media"
        assert media_spec.boundary.kind == "media.complete"


class TestRouteWiring:
    """Pattern-based route wiring from DSL to runtime Vertex."""

    def test_routes_in_compiled_vertex(self):
        """Routes are preserved in CompiledVertex."""
        vertex = parse_vertex("""\
name "system"
routes {
  disk "disk"
  proc "proc"
}
loops {
  disk {
    fold {
      count "inc"
    }
  }
  proc {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        assert compiled.routes is not None
        assert compiled.routes["disk"] == "disk"
        assert compiled.routes["proc"] == "proc"

    def test_routes_wired_to_runtime(self):
        """Routes are set on materialized Vertex."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "system"
routes {
  disk "disk"
  proc "proc"
}
loops {
  disk {
    fold {
      count "inc"
    }
  }
  proc {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        assert runtime._routes == {"disk": "disk", "proc": "proc"}

    def test_exact_match_routes(self):
        """Exact match routes work (backwards compatible)."""
        from vertex.compiler import materialize_vertex
        from atoms import Fact

        vertex = parse_vertex("""\
name "test"
routes {
  events "counter"
}
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        runtime.receive(Fact.of("events", "test"))
        assert runtime.state("counter") == {"count": 1}

        runtime.receive(Fact.of("events", "test"))
        assert runtime.state("counter") == {"count": 2}

    def test_pattern_routes_glob(self):
        """Glob pattern routes (* wildcard) work."""
        from vertex.compiler import materialize_vertex
        from atoms import Fact

        vertex = parse_vertex("""\
name "test"
routes {
  disk "storage"
}
loops {
  storage {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        # Manually set glob pattern routes (parser uses exact match syntax)
        compiled.routes = {"disk.*": "storage"}
        runtime = materialize_vertex(compiled)

        runtime.receive(Fact.of("disk.usage", "test"))
        assert runtime.state("storage") == {"count": 1}

        runtime.receive(Fact.of("disk.io", "test"))
        assert runtime.state("storage") == {"count": 2}

        runtime.receive(Fact.of("disk", "test"))
        assert runtime.state("storage") == {"count": 2}  # unchanged

    def test_direct_kind_match_takes_priority(self):
        """Direct kind registration takes priority over routes."""
        from vertex.compiler import materialize_vertex
        from atoms import Fact

        vertex = parse_vertex("""\
name "test"
routes {
  counter "other"
}
loops {
  counter {
    fold {
      count "inc"
    }
  }
  other {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        runtime.receive(Fact.of("counter", "test"))
        assert runtime.state("counter") == {"count": 1}
        assert runtime.state("other") == {"count": 0}

    def test_accepts_with_routes(self):
        """Vertex.accepts() checks pattern routes."""
        from vertex.compiler import materialize_vertex

        vertex = parse_vertex("""\
name "test"
routes {
  events "counter"
}
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        # Set glob pattern
        compiled.routes = {"event.*": "counter"}
        runtime = materialize_vertex(compiled)

        assert runtime.accepts("counter")
        assert runtime.accepts("event.click")
        assert runtime.accepts("event.scroll")
        assert not runtime.accepts("other.thing")

    def test_no_routes_null(self):
        """Vertex without routes: has routes=None in compiled."""
        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
""")
        compiled = compile_vertex_recursive(vertex)
        assert compiled.routes is None
