"""Tests for DSL mapper."""

from pathlib import Path

from data import Boundary, Collect, Count, Field, Latest, Max, Min, Source, Spec, Sum, Upsert
from data import Coerce as RuntimeCoerce
from data import Pick as RuntimePick
from data import Rename as RuntimeRename
from data import Skip as RuntimeSkip
from data import Split as RuntimeSplit
from data import Transform as RuntimeTransform

from dsl import parse_loop, parse_vertex
from dsl.mapper import (
    compile_loop,
    compile_vertex,
    map_fold_op,
    map_parse_steps,
    map_pick,
    map_skip,
    map_split,
    map_transform,
)
from dsl.ast import (
    Coerce,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    Pick,
    Skip,
    Split,
    Strip,
    Transform,
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
