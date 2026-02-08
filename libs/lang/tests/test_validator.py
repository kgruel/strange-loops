"""Tests for DSL validator."""

import pytest

from lang import ValidationError, parse_loop, parse_vertex
from lang.validator import Shape, ShapeKind, validate, validate_loop, validate_vertex


class TestShapeInference:
    """Shape inference through parse pipeline."""

    def test_no_parse_no_shape(self):
        """No parse section means no shape inference."""
        loop = parse_loop("""\
source "whoami"
kind "identity"
observer "shell"
""")
        shape = validate_loop(loop)
        assert shape is None

    def test_skip_preserves_string(self):
        """Skip keeps string shape."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  skip "^Filesystem"
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.STRING

    def test_split_produces_list(self):
        """Split produces list shape."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.LIST

    def test_pick_with_names_produces_dict(self):
        """Pick with names produces dict shape."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  pick 0 4 {
    names "fs" "pct"
  }
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert shape.fields == ("fs", "pct")
        assert shape.field_types == {"fs": "str", "pct": "str"}

    def test_transform_updates_field_type(self):
        """Transform with coerce updates field type."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  pick 0 4 {
    names "fs" "pct"
  }
  transform "pct" {
    coerce "int"
  }
}
""")
        shape = validate_loop(loop)
        assert shape.field_types["pct"] == "int"
        assert shape.field_types["fs"] == "str"

    def test_transform_chain_uses_last_coerce(self):
        """Transform chain uses the last coerce type."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  pick 0 1 {
    names "name" "value"
  }
  transform "value" {
    strip "%"
    coerce "float"
  }
}
""")
        shape = validate_loop(loop)
        assert shape.field_types["value"] == "float"


class TestFlowValidation:
    """Parse step ordering validation."""

    def test_pick_before_split_fails(self):
        """Pick requires split first."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  pick 0 4 {
    names "fs" "pct"
  }
}
""")
        with pytest.raises(ValidationError, match="pick.*requires list input"):
            validate_loop(loop)

    def test_transform_before_pick_fails(self):
        """Transform requires dict (pick with names)."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  transform "pct" {
    coerce "int"
  }
}
""")
        with pytest.raises(ValidationError, match="transform.*requires dict input"):
            validate_loop(loop)

    def test_transform_unknown_field_fails(self):
        """Transform must reference known field."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  pick 0 4 {
    names "fs" "pct"
  }
  transform "unknown" {
    coerce "int"
  }
}
""")
        with pytest.raises(ValidationError, match="unknown field 'unknown'"):
            validate_loop(loop)

    def test_skip_after_split_fails(self):
        """Skip requires string input."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  split
  skip "^Foo"
}
""")
        with pytest.raises(ValidationError, match="skip.*requires string input"):
            validate_loop(loop)

    def test_valid_full_pipeline(self):
        """Full valid pipeline passes."""
        loop = parse_loop("""\
source "df -h"
kind "disk"
observer "test"
parse {
  skip "^Filesystem"
  split
  pick 0 4 5 {
    names "fs" "pct" "mount"
  }
  transform "pct" {
    strip "%"
    coerce "int"
  }
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert shape.fields == ("fs", "pct", "mount")


class TestJsonFormatValidation:
    """Validation specific to JSON format."""

    def test_json_with_split_fails(self):
        """JSON format doesn't allow split (dict input, not string)."""
        loop = parse_loop("""\
source "curl -s http://api.example.com"
format "json"
kind "api"
observer "http"
parse {
  split
}
""")
        with pytest.raises(ValidationError, match="split.*requires string input"):
            validate_loop(loop)

    def test_json_with_skip_fails(self):
        """JSON format doesn't allow skip (dict input, not string)."""
        loop = parse_loop("""\
source "curl -s http://api.example.com"
format "json"
kind "api"
observer "http"
parse {
  skip "^foo"
}
""")
        with pytest.raises(ValidationError, match="skip.*requires string input"):
            validate_loop(loop)


class TestNewParseStepValidation:
    """Validation for Explode, Project, Where parse steps."""

    def test_where_on_json_valid(self):
        """Where is valid with JSON format."""
        loop = parse_loop("""\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  where path="status" equals="success"
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT

    def test_explode_on_json_valid(self):
        """Explode is valid with JSON format."""
        loop = parse_loop("""\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  explode path="data.alerts"
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT

    def test_project_produces_named_dict(self):
        """Project produces dict shape with declared fields."""
        loop = parse_loop("""\
source "curl -s http://api"
kind "alerts"
observer "test"
format "json"
parse {
  explode path="data.alerts"
  project {
    name path="labels.alertname"
    state path="state"
  }
}
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert shape.fields == ("name", "state")

    def test_full_pipeline_valid(self):
        """Full where → explode → project pipeline is valid."""
        loop = parse_loop("""\
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
""")
        shape = validate_loop(loop)
        assert shape.kind == ShapeKind.DICT
        assert "alertname" in shape.fields


class TestVertexValidation:
    """Vertex file validation."""

    def test_valid_vertex(self):
        """Valid vertex passes."""
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
        validate_vertex(vertex)  # Should not raise

    def test_loop_with_boundary_but_no_fold_is_allowed(self):
        """Override placeholder loops can omit fold when boundary is present."""
        vertex = parse_vertex("""\
name "test"
loops {
  events {
    boundary when="events.complete"
  }
}
""")
        validate_vertex(vertex)  # Should not raise

    def test_loop_with_no_fold_and_no_boundary_fails(self):
        """Loops must have a fold unless a boundary is present."""
        from lang.ast import LoopDef, VertexFile

        vertex = VertexFile(name="test", loops={"events": LoopDef(folds=(), boundary=None)})
        with pytest.raises(ValidationError, match="has no fold declarations"):
            validate_vertex(vertex)

    def test_route_to_undefined_loop_fails(self):
        """Routes must reference defined loops."""
        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
    }
  }
}
routes {
  events "undefined_loop"
}
""")
        with pytest.raises(ValidationError, match="undefined loop 'undefined_loop'"):
            validate_vertex(vertex)

    def test_duplicate_fold_target_fails(self):
        """Duplicate fold targets are not allowed."""
        vertex = parse_vertex("""\
name "test"
loops {
  counter {
    fold {
      count "inc"
      count "latest"
    }
  }
}
""")
        with pytest.raises(ValidationError, match="duplicate fold target 'count'"):
            validate_vertex(vertex)


class TestValidateGeneric:
    """Test the generic validate() function."""

    def test_validate_loop_file(self):
        """validate() works with LoopFile."""
        loop = parse_loop("""\
source "echo"
kind "test"
observer "test"
""")
        result = validate(loop)
        assert result is None  # No parse section

    def test_validate_vertex_file(self):
        """validate() works with VertexFile."""
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
        result = validate(vertex)
        assert result is None  # Vertex validation returns None


class TestTriggerValidation:
    """Validation for on:/every: trigger syntax."""

    def test_on_and_every_mutually_exclusive(self):
        """on: and every: cannot be used together."""
        loop = parse_loop("""\
source "df -h"
on "minute"
every "60s"
kind "disk"
observer "monitor"
""")
        with pytest.raises(ValidationError, match="on: and every: are mutually exclusive"):
            validate_loop(loop)

    def test_pure_timer_valid(self):
        """Pure timer loop (every: without source:) is valid."""
        loop = parse_loop("""\
every "60s"
kind "minute"
observer "clock"
""")
        validate_loop(loop)  # Should not raise

    def test_triggered_source_valid(self):
        """Triggered source (on: with source:) is valid."""
        loop = parse_loop("""\
source "df -h"
on "minute"
kind "disk"
observer "monitor"
""")
        validate_loop(loop)  # Should not raise

    def test_traditional_loop_valid(self):
        """Traditional loop (every: with source:) is valid."""
        loop = parse_loop("""\
source "df -h"
every "60s"
kind "disk"
observer "monitor"
""")
        validate_loop(loop)  # Should not raise
