"""Tests for DSL mapper."""

from pathlib import Path

import pytest
from data import Avg, Boundary, Collect, Count, Field, Latest, Max, Min, Source, Spec, Sum, Upsert, Window
from data import Coerce as RuntimeCoerce
from data import Pick as RuntimePick
from data import Rename as RuntimeRename
from data import Skip as RuntimeSkip
from data import Split as RuntimeSplit
from data import Transform as RuntimeTransform

from dsl import parse_loop, parse_vertex
from dsl.mapper import (
    CircularVertexError,
    CompiledVertex,
    compile_loop,
    compile_vertex,
    compile_vertex_recursive,
    map_fold_op,
    map_parse_steps,
    map_pick,
    map_skip,
    map_split,
    map_transform,
)
from dsl.ast import (
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
source: whoami
kind: identity
observer: shell
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
source: date
kind: heartbeat
observer: timer
every: 5s
""")
        source = compile_loop(loop)
        assert source.every == 5.0

    def test_loop_with_parse(self):
        """Loop with parse pipeline compiles to Source with parse ops."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  skip ^Filesystem
  split
  pick 0, 4 -> fs, pct
  pct: strip "%" | int
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
        from dsl import parse_loop_file

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
name: simple
loops:
  counter:
    fold:
      count: +1
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
name: test
loops:
  events:
    fold:
      count: +1
    boundary: when batch.complete
""")
        specs = compile_vertex(vertex)
        spec = specs["events"]
        assert spec.boundary is not None
        assert isinstance(spec.boundary, Boundary)
        assert spec.boundary.kind == "batch.complete"

    def test_vertex_state_fields(self):
        """Vertex compiles with inferred state fields."""
        vertex = parse_vertex("""\
name: test
loops:
  metrics:
    fold:
      mounts: by mount
      count: +1
      total: + amount
      updated: latest
      history: collect 100
      peak: max memory
      coldest: min temp
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
        from dsl import parse_vertex_file

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
        from data import run_parse

        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  skip ^Filesystem
  split
  pick 0, 1 -> fs, pct
  pct: strip "%" | int
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
name: test
loops:
  counter:
    fold:
      count: +1
      total: + value
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
source: process-batch
kind: processed
observer: worker
on: batch.ready
""")
        source = compile_loop(loop)
        assert isinstance(source, Source)
        assert source.command == "process-batch"
        assert source.trigger == ("batch.ready",)
        assert source.every is None

    def test_multiple_triggers(self):
        """Loop with multiple on: triggers compiles to Source with trigger tuple."""
        loop = parse_loop("""\
source: aggregate
kind: aggregated
observer: collector
on: [minute, hour, day]
""")
        source = compile_loop(loop)
        assert source.trigger == ("minute", "hour", "day")
        assert source.every is None

    def test_polling_source_no_trigger(self):
        """Loop with every: but no on: has no trigger."""
        loop = parse_loop("""\
source: check-health
kind: health
observer: monitor
every: 30s
""")
        source = compile_loop(loop)
        assert source.trigger is None
        assert source.every == 30.0


class TestPureTimerSource:
    """Pure timer source compilation (every: without source:)."""

    def test_pure_timer(self):
        """Loop with every: but no source: compiles to pure timer Source."""
        loop = parse_loop("""\
kind: tick
observer: timer
every: 1m
""")
        source = compile_loop(loop)
        assert isinstance(source, Source)
        assert source.command is None
        assert source.every == 60.0
        assert source.kind == "tick"

    def test_pure_timer_with_trigger(self):
        """Loop with every: and on: compiles to triggered timer."""
        # Note: on: requires every: in pure timer case to define cadence
        loop = parse_loop("""\
kind: batch.tick
observer: scheduler
every: 1m
on: minute
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
name: simple
loops:
  counter:
    fold:
      count: +1
""")
        compiled = compile_vertex_recursive(vertex)
        assert isinstance(compiled, CompiledVertex)
        assert compiled.name == "simple"
        assert "counter" in compiled.specs
        assert compiled.children == {}

    def test_vertex_with_children(self, tmp_path):
        """Vertex with vertices: compiles children recursively."""
        # Create child vertex file
        child_content = """\
name: child
loops:
  events:
    fold:
      count: +1
"""
        child_path = tmp_path / "child.vertex"
        child_path.write_text(child_content)

        # Create parent vertex file
        parent_content = f"""\
name: parent
vertices:
  - {child_path}
loops:
  aggregate:
    fold:
      total: +1
"""
        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(parent_content)

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert compiled.name == "parent"
        assert "aggregate" in compiled.specs
        assert "child" in compiled.children
        assert compiled.children["child"].name == "child"
        assert "events" in compiled.children["child"].specs

    def test_circular_vertex_detection(self, tmp_path):
        """Circular vertex references raise CircularVertexError."""
        # Create two vertices that reference each other
        a_path = tmp_path / "a.vertex"
        b_path = tmp_path / "b.vertex"

        a_content = f"""\
name: a
vertices:
  - {b_path}
loops:
  x:
    fold:
      count: +1
"""
        b_content = f"""\
name: b
vertices:
  - {a_path}
loops:
  y:
    fold:
      count: +1
"""
        a_path.write_text(a_content)
        b_path.write_text(b_content)

        from dsl import parse_vertex_file

        a_ast = parse_vertex_file(a_path)
        with pytest.raises(CircularVertexError):
            compile_vertex_recursive(a_ast)

    def test_relative_path_resolution(self, tmp_path):
        """Child paths are resolved relative to parent vertex file."""
        # Create subdir with child
        subdir = tmp_path / "sub"
        subdir.mkdir()
        child_path = subdir / "child.vertex"
        child_path.write_text(
            "name: child\n"
            "loops:\n"
            "  events:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        # Parent references child with relative path (must start with ./)
        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(
            "name: parent\n"
            "vertices:\n"
            "  - ./sub/child.vertex\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "child" in compiled.children


class TestDiscoverVertices:
    """Vertex discovery via glob patterns."""

    def test_discover_vertices_simple(self, tmp_path):
        """discover: pattern finds .vertex files."""
        # Create child vertices
        infra = tmp_path / "infra"
        infra.mkdir()
        (infra / "disk.vertex").write_text(
            "name: disk\n"
            "loops:\n"
            "  usage:\n"
            "    fold:\n"
            "      count: +1\n"
        )
        (infra / "proc.vertex").write_text(
            "name: proc\n"
            "loops:\n"
            "  count:\n"
            "    fold:\n"
            "      total: +1\n"
        )

        # Parent with discover pattern
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./infra/*.vertex\n"
            "loops:\n"
            "  system:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert compiled.name == "root"
        assert "disk" in compiled.children
        assert "proc" in compiled.children

    def test_discover_vertices_recursive(self, tmp_path):
        """Recursive glob **/*.vertex finds nested vertices."""
        # Create nested structure
        level1 = tmp_path / "level1"
        level1.mkdir()
        level2 = level1 / "level2"
        level2.mkdir()

        (level1 / "a.vertex").write_text(
            "name: a\n"
            "loops:\n"
            "  x:\n"
            "    fold:\n"
            "      count: +1\n"
        )
        (level2 / "b.vertex").write_text(
            "name: b\n"
            "loops:\n"
            "  y:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        # Parent with recursive discover
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./**/*.vertex\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "a" in compiled.children
        assert "b" in compiled.children

    def test_discover_skips_self(self, tmp_path):
        """discover: pattern does not include the vertex file itself."""
        # Root vertex with pattern that would match itself
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./*.vertex\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        # Should not include itself as a child
        assert "root" not in compiled.children
        assert compiled.children == {}

    def test_discover_combined_with_vertices(self, tmp_path):
        """discover: and vertices: can be used together."""
        # Create discovered vertex
        infra = tmp_path / "infra"
        infra.mkdir()
        (infra / "disk.vertex").write_text(
            "name: disk\n"
            "loops:\n"
            "  usage:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        # Create explicit vertex
        explicit = tmp_path / "explicit.vertex"
        explicit.write_text(
            "name: explicit\n"
            "loops:\n"
            "  events:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        # Parent with both
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./infra/*.vertex\n"
            "vertices:\n"
            "  - ./explicit.vertex\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        assert "disk" in compiled.children  # discovered
        assert "explicit" in compiled.children  # explicit

    def test_discover_avoids_duplicates(self, tmp_path):
        """If same vertex is in vertices: and discover:, only included once."""
        # Create vertex that will be both explicit and discovered
        (tmp_path / "child.vertex").write_text(
            "name: child\n"
            "loops:\n"
            "  events:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        # Parent lists child explicitly and via discover
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./*.vertex\n"
            "vertices:\n"
            "  - ./child.vertex\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        # Should have exactly one child
        assert len(compiled.children) == 1
        assert "child" in compiled.children

    def test_discover_circular_detection(self, tmp_path):
        """Circular references via discover: still detected."""
        # Create two vertices that would discover each other
        a_dir = tmp_path / "a_dir"
        b_dir = tmp_path / "b_dir"
        a_dir.mkdir()
        b_dir.mkdir()

        a_path = a_dir / "a.vertex"
        b_path = b_dir / "b.vertex"

        # a discovers from b's directory, b from a's directory
        a_path.write_text(
            f"name: a\n"
            f"discover: {b_dir}/*.vertex\n"
            "loops:\n"
            "  x:\n"
            "    fold:\n"
            "      count: +1\n"
        )
        b_path.write_text(
            f"name: b\n"
            f"discover: {a_dir}/*.vertex\n"
            "loops:\n"
            "  y:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        a_ast = parse_vertex_file(a_path)
        with pytest.raises(CircularVertexError):
            compile_vertex_recursive(a_ast)

    def test_discover_only_vertex_files(self, tmp_path):
        """discover: pattern only includes .vertex files, not .loop files."""
        # Create both .vertex and .loop files
        (tmp_path / "child.vertex").write_text(
            "name: child\n"
            "loops:\n"
            "  events:\n"
            "    fold:\n"
            "      count: +1\n"
        )
        (tmp_path / "source.loop").write_text(
            "source: echo test\n"
            "kind: test\n"
            "observer: shell\n"
        )

        # Parent with pattern that would match both
        parent_path = tmp_path / "root.vertex"
        parent_path.write_text(
            "name: root\n"
            "discover: ./*\n"
            "loops:\n"
            "  main:\n"
            "    fold:\n"
            "      count: +1\n"
        )

        from dsl import parse_vertex_file

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        # Should only include .vertex, not .loop
        assert "child" in compiled.children
        assert len(compiled.children) == 1


class TestMaterializeVertex:
    """Vertex tree materialization."""

    def test_materialize_simple(self):
        """Simple vertex materializes to runtime Vertex."""
        from dsl.mapper import materialize_vertex

        vertex = parse_vertex("""\
name: counter
loops:
  events:
    fold:
      count: +1
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        assert runtime.name == "counter"
        assert "events" in runtime.kinds
        assert runtime.state("events") == {"count": 0}

        # Fold a fact
        from data import Fact

        fact = Fact.of("events", "test", value=1)
        runtime.receive(fact)
        assert runtime.state("events") == {"count": 1}

    def test_materialize_with_boundary(self):
        """Vertex with boundary emits tick on boundary fact."""
        from dsl.mapper import materialize_vertex

        vertex = parse_vertex("""\
name: batcher
loops:
  batch:
    fold:
      count: +1
    boundary: when batch.done
""")
        compiled = compile_vertex_recursive(vertex)
        runtime = materialize_vertex(compiled)

        from data import Fact

        # Regular facts fold
        runtime.receive(Fact.of("batch", "test", value=1))
        runtime.receive(Fact.of("batch", "test", value=2))
        assert runtime.state("batch") == {"count": 2}

        # Boundary fact triggers tick
        tick = runtime.receive(Fact.of("batch.done", "test"))
        assert tick is not None
        assert tick.name == "batch"
        assert tick.payload == {"count": 2}

        # State was reset
        assert runtime.state("batch") == {"count": 0}

    def test_materialize_with_fold_override(self):
        """Custom fold functions override Spec.apply."""
        from dsl.mapper import materialize_vertex

        vertex = parse_vertex("""\
name: custom
loops:
  counter:
    fold:
      count: +1
""")
        compiled = compile_vertex_recursive(vertex)

        # Custom fold that doubles instead of counting
        def custom_fold(state, payload):
            return {"count": state["count"] + payload.get("value", 1) * 2}

        runtime = materialize_vertex(compiled, fold_overrides={
            "counter": ({"count": 0}, custom_fold),
        })

        from data import Fact

        runtime.receive(Fact.of("counter", "test", value=5))
        assert runtime.state("counter") == {"count": 10}

        runtime.receive(Fact.of("counter", "test", value=3))
        assert runtime.state("counter") == {"count": 16}

    def test_materialize_nested(self, tmp_path):
        """Nested vertices materialize with add_child."""
        from dsl.mapper import materialize_vertex
        from dsl import parse_vertex_file

        # Create child vertex
        child_content = """\
name: child
loops:
  events:
    fold:
      count: +1
    boundary: when events.done
emit: child.tick
"""
        child_path = tmp_path / "child.vertex"
        child_path.write_text(child_content)

        # Create parent vertex
        parent_content = f"""\
name: parent
vertices:
  - {child_path}
loops:
  aggregate:
    fold:
      total: +1
"""
        parent_path = tmp_path / "parent.vertex"
        parent_path.write_text(parent_content)

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)
        runtime = materialize_vertex(compiled)

        assert runtime.name == "parent"
        assert len(runtime.children) == 1
        assert runtime.children[0].name == "child"

    def test_materialize_nested_tick_flow(self, tmp_path):
        """Child ticks become facts to parent via automatic wiring."""
        from dsl.mapper import materialize_vertex
        from dsl import parse_vertex_file

        # Create child vertex that emits tick
        child_content = """\
name: pulse
loops:
  pulse:
    fold:
      count: +1
    boundary: when pulse.done
"""
        child_path = tmp_path / "pulse.vertex"
        child_path.write_text(child_content)

        # Parent aggregates child ticks
        parent_content = f"""\
name: breath
vertices:
  - {child_path}
loops:
  breath:
    fold:
      pulses: +1
"""
        parent_path = tmp_path / "breath.vertex"
        parent_path.write_text(parent_content)

        parent_ast = parse_vertex_file(parent_path)
        compiled = compile_vertex_recursive(parent_ast)

        # Custom fold for child since emit name needs to match
        def pulse_fold(state, payload):
            return {"count": state["count"] + 1}

        runtime = materialize_vertex(compiled, fold_overrides={
            "pulse": ({"count": 0}, pulse_fold),
        })

        from data import Fact

        # Send pulse facts through parent
        runtime.receive(Fact.of("pulse", "test"))
        runtime.receive(Fact.of("pulse", "test"))
        runtime.receive(Fact.of("pulse", "test"))

        # Child state accumulated
        child = runtime.children[0]
        assert child.state("pulse") == {"count": 3}
