"""Tests for uncovered parse paths — Select, run_parse_many, single-record edge cases."""

from atoms import Coerce, Pick, Rename, Skip, Split, Transform, run_parse
from atoms.parse import Select, run_parse_many, Explode, Project, Where, Flatten


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


class TestTypeGuardReturnsNone:
    """Type guards in parse ops return None for wrong input types."""

    def test_skip_field_mode_on_non_dict(self):
        # L266: Skip with field= on non-dict → None
        result = run_parse("just a string", [Skip(field="status", equals="bad")])
        assert result is None

    def test_split_on_non_string(self):
        # L291: Split on non-string → None
        result = run_parse({"already": "dict"}, [Split()])
        assert result is None

    def test_pick_on_non_list(self):
        # L308: Pick on non-list → None
        result = run_parse("string", [Pick(0)])
        assert result is None

    def test_rename_on_non_list(self):
        # L323: Rename on non-list → None
        result = run_parse("string", [Rename({0: "first"})])
        assert result is None

    def test_transform_on_non_dict(self):
        # L338: Transform on non-dict → None
        result = run_parse("string", [Transform(field="x")])
        assert result is None

    def test_transform_field_not_string(self):
        # L345: Transform field value is not string → None
        result = run_parse({"x": 42}, [Transform(field="x", strip=" ")])
        assert result is None

    def test_coerce_unknown_target_type(self):
        # L384: Unknown target type in _coerce_value → ValueError
        result = run_parse({"x": "val"}, [Coerce(types={"x": complex})])
        assert result is None

    def test_coerce_on_non_dict(self):
        # L390: Coerce on non-dict → None
        result = run_parse("string", [Coerce(types={"x": int})])
        assert result is None

    def test_where_unknown_op(self):
        # L452: Where with unknown op → None
        result = run_parse({"x": 1}, [Where(path="x", op="unknown_op")])
        assert result is None


class TestRunParseManyDispatch:
    """run_parse_many exercising all branch dispatch paths."""

    def test_where_filters_in_stream(self):
        data = {"status": "active"}
        ops = [Where(path="status", op="equals", value="inactive")]
        results = run_parse_many(data, ops)
        assert results == []

    def test_single_ops_in_stream(self):
        # L514-516: Delegate to _apply_single_op in stream mode
        data = {"line": "a b c"}
        ops = [Skip(startswith="x"), Split(delim=" ")]
        results = run_parse_many(data, ops)
        # Skip doesn't match → passes through, then Split can't work on dict
        assert len(results) == 0  # Split on dict returns None

    def test_select_in_stream(self):
        # L508-511: Select path in run_parse_many
        data = {"name": "x", "status": "up", "extra": 1}
        results = run_parse_many(data, [Select("name", "status")])
        assert results == [{"name": "x", "status": "up"}]

    def test_skip_in_stream_filters(self):
        # Skip checks string values directly; dict needs field-mode skip
        data = {"status": "skip_me"}
        ops = [Skip(field="status", startswith="skip")]
        results = run_parse_many(data, ops)
        assert results == []  # Skip matched → filtered out


class TestRunParseSingleDispatch:
    """run_parse exercising single-record pipeline dispatch in the main function."""

    def test_run_parse_empty_pipeline_returns_dict(self):
        # L589: empty pipeline + dict input
        result = run_parse({"a": 1}, [])
        assert result == {"a": 1}

    def test_run_parse_explode_in_single_mode(self):
        # L619-620: Explode in single-record run_parse
        data = {"items": [{"n": "a"}, {"n": "b"}]}
        result = run_parse(data, [Explode(path="items")])
        assert result is not None
        assert result["n"] == "a"  # first element only

    def test_run_parse_unknown_op_returns_none(self):
        # L629: unknown op type → None
        class FakeOp:
            pass
        result = run_parse({"x": 1}, [FakeOp()])
        assert result is None
