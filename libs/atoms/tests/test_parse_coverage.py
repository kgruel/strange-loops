"""Tests for uncovered parse paths — Select, run_parse_many, single-record edge cases."""

from atoms.parse import Select, run_parse, run_parse_many, Explode, Project, Where, Flatten


class TestSelect:
    def test_select_fields(self):
        op = Select("name", "state")
        result = run_parse({"name": "x", "state": "up", "extra": 1}, [op])
        assert result == {"name": "x", "state": "up"}

    def test_select_missing_field(self):
        op = Select("name", "missing")
        result = run_parse({"name": "x"}, [op])
        assert result == {"name": "x"}

    def test_select_all_missing(self):
        op = Select("a", "b")
        result = run_parse({"c": 1}, [op])
        assert result is None

    def test_select_non_dict(self):
        op = Select("a")
        result = run_parse("not a dict", [op])
        assert result is None


class TestRunParseMany:
    def test_basic(self):
        results = run_parse_many("hello world", [])
        assert results == ["hello world"]

    def test_with_explode(self):
        data = {"items": [{"name": "a"}, {"name": "b"}]}
        ops = [Explode(path="items")]
        results = run_parse_many(data, ops)
        assert len(results) == 2

    def test_with_select(self):
        data = {"x": 1, "y": 2, "z": 3}
        results = run_parse_many(data, [Select("x", "y")])
        assert results == [{"x": 1, "y": 2}]


class TestSingleRecordEdgeCases:
    def test_project_on_non_dict(self):
        result = run_parse("string", [Project(fields={"out": "in"})])
        assert result is None

    def test_explode_on_non_dict(self):
        result = run_parse("string", [Explode(path="items")])
        assert result is None

    def test_flatten_on_non_dict(self):
        result = run_parse("string", [Flatten(field="items", into="text", extract=("name",))])
        assert result is None

    def test_where_on_non_dict(self):
        """Where on non-dict input passes through (no path to check)."""
        result = run_parse("string", [Where(path="x", op="equals", value="y")])
        assert result is None or isinstance(result, str)
