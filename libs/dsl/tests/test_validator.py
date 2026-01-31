"""Tests for DSL validator."""

import pytest

from dsl import ValidationError, parse_loop, parse_vertex
from dsl.validator import Shape, ShapeKind, validate, validate_loop, validate_vertex


class TestShapeInference:
    """Shape inference through parse pipeline."""

    def test_no_parse_no_shape(self):
        """No parse section means no shape inference."""
        loop = parse_loop("""\
source: whoami
kind: identity
observer: shell
""")
        shape = validate_loop(loop)
        assert shape is None

    def test_skip_preserves_string(self):
        """Skip keeps string shape."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  skip ^Filesystem
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.STRING

    def test_split_produces_list(self):
        """Split produces list shape."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.LIST

    def test_pick_with_names_produces_dict(self):
        """Pick with names produces dict shape."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  pick 0, 4 -> fs, pct
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert shape.fields == ("fs", "pct")
        assert shape.field_types == {"fs": "str", "pct": "str"}

    def test_transform_updates_field_type(self):
        """Transform with coerce updates field type."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  pick 0, 4 -> fs, pct
  pct: int
""")
        shape = validate_loop(loop)
        assert shape.field_types["pct"] == "int"
        assert shape.field_types["fs"] == "str"

    def test_transform_chain_uses_last_coerce(self):
        """Transform chain uses the last coerce type."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  pick 0, 1 -> name, value
  value: strip "%" | float
""")
        shape = validate_loop(loop)
        assert shape.field_types["value"] == "float"


class TestFlowValidation:
    """Parse step ordering validation."""

    def test_pick_before_split_fails(self):
        """Pick requires split first."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  pick 0, 4 -> fs, pct
""")
        with pytest.raises(ValidationError, match="pick.*requires list input"):
            validate_loop(loop)

    def test_transform_before_pick_fails(self):
        """Transform requires dict (pick with names)."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  pct: int
""")
        with pytest.raises(ValidationError, match="transform.*requires dict input"):
            validate_loop(loop)

    def test_transform_unknown_field_fails(self):
        """Transform must reference known field."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  pick 0, 4 -> fs, pct
  unknown: int
""")
        with pytest.raises(ValidationError, match="unknown field 'unknown'"):
            validate_loop(loop)

    def test_skip_after_split_fails(self):
        """Skip requires string input."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  split
  skip ^Foo
""")
        with pytest.raises(ValidationError, match="skip.*requires string input"):
            validate_loop(loop)

    def test_valid_full_pipeline(self):
        """Full valid pipeline passes."""
        loop = parse_loop("""\
source: df -h
kind: disk
observer: test
parse:
  skip ^Filesystem
  split
  pick 0, 4, 5 -> fs, pct, mount
  pct: strip "%" | int
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert shape.fields == ("fs", "pct", "mount")


class TestJsonFormatValidation:
    """Validation specific to JSON format."""

    def test_json_with_split_fails(self):
        """JSON format doesn't allow split."""
        loop = parse_loop("""\
source: curl -s http://api.example.com
format: json
kind: api
observer: http
parse:
  split
""")
        with pytest.raises(ValidationError, match="split is not valid with format: json"):
            validate_loop(loop)

    def test_json_with_skip_fails(self):
        """JSON format doesn't allow skip."""
        loop = parse_loop("""\
source: curl -s http://api.example.com
format: json
kind: api
observer: http
parse:
  skip ^foo
""")
        with pytest.raises(ValidationError, match="skip is not valid with format: json"):
            validate_loop(loop)


class TestVertexValidation:
    """Vertex file validation."""

    def test_valid_vertex(self):
        """Valid vertex passes."""
        vertex = parse_vertex("""\
name: test
loops:
  counter:
    fold:
      count: +1
""")
        validate_vertex(vertex)  # Should not raise

    def test_route_to_undefined_loop_fails(self):
        """Routes must reference defined loops."""
        vertex = parse_vertex("""\
name: test
loops:
  counter:
    fold:
      count: +1
routes:
  events: undefined_loop
""")
        with pytest.raises(ValidationError, match="undefined loop 'undefined_loop'"):
            validate_vertex(vertex)

    def test_duplicate_fold_target_fails(self):
        """Duplicate fold targets are not allowed."""
        vertex = parse_vertex("""\
name: test
loops:
  counter:
    fold:
      count: +1
      count: latest
""")
        with pytest.raises(ValidationError, match="duplicate fold target 'count'"):
            validate_vertex(vertex)


class TestValidateGeneric:
    """Test the generic validate() function."""

    def test_validate_loop_file(self):
        """validate() works with LoopFile."""
        loop = parse_loop("""\
source: echo
kind: test
observer: test
""")
        result = validate(loop)
        assert result is None  # No parse section

    def test_validate_vertex_file(self):
        """validate() works with VertexFile."""
        vertex = parse_vertex("""\
name: test
loops:
  counter:
    fold:
      count: +1
""")
        result = validate(vertex)
        assert result is None  # Vertex validation returns None
