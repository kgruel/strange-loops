"""Tests for shapes core types: Facet, Fold, Shape."""

import pytest

from shapes import Facet, Fold, Shape, ValidationError
from shapes.types import coerce_value, initial_value, type_matches


class TestFacet:
    """Tests for Facet dataclass."""

    def test_basic_facet(self):
        f = Facet(name="count", kind="int")
        assert f.name == "count"
        assert f.kind == "int"
        assert f.optional is False

    def test_optional_facet(self):
        f = Facet(name="label", kind="str", optional=True)
        assert f.optional is True

    def test_from_type_str_required(self):
        f = Facet.from_type_str("age", "int")
        assert f.name == "age"
        assert f.kind == "int"
        assert f.optional is False

    def test_from_type_str_optional(self):
        f = Facet.from_type_str("nickname", "str?")
        assert f.name == "nickname"
        assert f.kind == "str"
        assert f.optional is True

    def test_frozen(self):
        f = Facet(name="x", kind="int")
        with pytest.raises(AttributeError):
            f.name = "y"


class TestFold:
    """Tests for Fold dataclass."""

    def test_basic_fold(self):
        f = Fold(op="count", target="total")
        assert f.op == "count"
        assert f.target == "total"
        assert f.props == {}

    def test_fold_with_props(self):
        f = Fold(op="collect", target="events", props={"max": 100})
        assert f.props["max"] == 100

    def test_upsert_fold(self):
        f = Fold(op="upsert", target="items", props={"key": "id"})
        assert f.op == "upsert"
        assert f.props["key"] == "id"

    def test_frozen(self):
        f = Fold(op="count", target="n")
        with pytest.raises(AttributeError):
            f.op = "sum"

    def test_props_immutable(self):
        f = Fold(op="collect", target="events", props={"max": 100})
        with pytest.raises(TypeError):
            f.props["max"] = 200


class TestShape:
    """Tests for Shape dataclass."""

    def test_empty_shape(self):
        f = Shape(name="empty")
        assert f.name == "empty"
        assert f.about == ""
        assert f.input_facets == ()
        assert f.state_facets == ()
        assert f.folds == ()

    def test_shape_with_about(self):
        f = Shape(name="counter", about="Counts events")
        assert f.about == "Counts events"

    def test_shape_with_facets(self):
        f = Shape(
            name="tracker",
            input_facets=(
                Facet("user_id", "str"),
                Facet("action", "str"),
            ),
            state_facets=(
                Facet("count", "int"),
                Facet("users", "set"),
            ),
        )
        assert len(f.input_facets) == 2
        assert len(f.state_facets) == 2

    def test_shape_with_folds(self):
        f = Shape(
            name="accumulator",
            folds=(
                Fold(op="count", target="total"),
                Fold(op="upsert", target="seen", props={"key": "id"}),
            ),
        )
        assert len(f.folds) == 2

    def test_initial_state_dict(self):
        f = Shape(
            name="test",
            state_facets=(Facet("items", "dict"),),
        )
        assert f.initial_state() == {"items": {}}

    def test_initial_state_list(self):
        f = Shape(
            name="test",
            state_facets=(Facet("events", "list"),),
        )
        assert f.initial_state() == {"events": []}

    def test_initial_state_set(self):
        f = Shape(
            name="test",
            state_facets=(Facet("seen", "set"),),
        )
        assert f.initial_state() == {"seen": set()}

    def test_initial_state_int(self):
        f = Shape(
            name="test",
            state_facets=(Facet("count", "int"),),
        )
        assert f.initial_state() == {"count": 0}

    def test_initial_state_float(self):
        f = Shape(
            name="test",
            state_facets=(Facet("total", "float"),),
        )
        assert f.initial_state() == {"total": 0}

    def test_initial_state_bool(self):
        f = Shape(
            name="test",
            state_facets=(Facet("active", "bool"),),
        )
        assert f.initial_state() == {"active": False}

    def test_initial_state_str(self):
        f = Shape(
            name="test",
            state_facets=(Facet("label", "str"),),
        )
        assert f.initial_state() == {"label": ""}

    def test_initial_state_datetime(self):
        f = Shape(
            name="test",
            state_facets=(Facet("last_seen", "datetime"),),
        )
        assert f.initial_state() == {"last_seen": None}

    def test_initial_state_multiple_facets(self):
        f = Shape(
            name="complex",
            state_facets=(
                Facet("count", "int"),
                Facet("items", "dict"),
                Facet("events", "list"),
                Facet("seen", "set"),
            ),
        )
        state = f.initial_state()
        assert state == {
            "count": 0,
            "items": {},
            "events": [],
            "seen": set(),
        }

    def test_input_facet_lookup(self):
        f = Shape(
            name="test",
            input_facets=(
                Facet("user_id", "str"),
                Facet("amount", "int"),
            ),
        )
        assert f.input_facet("user_id") == Facet("user_id", "str")
        assert f.input_facet("amount") == Facet("amount", "int")
        assert f.input_facet("missing") is None

    def test_state_facet_lookup(self):
        f = Shape(
            name="test",
            state_facets=(
                Facet("total", "int"),
                Facet("items", "dict"),
            ),
        )
        assert f.state_facet("total") == Facet("total", "int")
        assert f.state_facet("items") == Facet("items", "dict")
        assert f.state_facet("missing") is None

    def test_frozen(self):
        f = Shape(name="test")
        with pytest.raises(AttributeError):
            f.name = "other"


class TestTypeUtilities:
    """Tests for type utility functions."""

    def test_initial_value_all_types(self):
        assert initial_value("dict") == {}
        assert initial_value("list") == []
        assert initial_value("set") == set()
        assert initial_value("int") == 0
        assert initial_value("float") == 0
        assert initial_value("bool") is False
        assert initial_value("str") == ""
        assert initial_value("datetime") is None
        assert initial_value("unknown") is None

    def test_coerce_value_to_int(self):
        assert coerce_value("42", "int") == 42
        assert coerce_value(3.7, "int") == 3
        assert coerce_value(True, "int") == 1
        assert coerce_value(42, "int") == 42
        assert coerce_value("not a number", "int") == "not a number"
        assert coerce_value(None, "int") is None

    def test_coerce_value_to_float(self):
        assert coerce_value("3.14", "float") == 3.14
        assert coerce_value(42, "float") == 42.0
        assert coerce_value(True, "float") == 1.0
        assert coerce_value(3.14, "float") == 3.14
        assert coerce_value("not a number", "float") == "not a number"

    def test_coerce_value_to_bool(self):
        assert coerce_value("true", "bool") is True
        assert coerce_value("True", "bool") is True
        assert coerce_value("1", "bool") is True
        assert coerce_value("yes", "bool") is True
        assert coerce_value("false", "bool") is False
        assert coerce_value("False", "bool") is False
        assert coerce_value("0", "bool") is False
        assert coerce_value("no", "bool") is False
        assert coerce_value(1, "bool") is True
        assert coerce_value(0, "bool") is False
        assert coerce_value("maybe", "bool") == "maybe"

    def test_coerce_value_to_str(self):
        assert coerce_value(42, "str") == "42"
        assert coerce_value("hello", "str") == "hello"

    def test_coerce_value_to_set(self):
        assert coerce_value([1, 2, 3], "set") == {1, 2, 3}
        assert coerce_value({1, 2}, "set") == {1, 2}

    def test_coerce_value_to_list(self):
        assert coerce_value({1, 2, 3}, "list") == [1, 2, 3] or set(coerce_value({1, 2, 3}, "list")) == {1, 2, 3}
        assert coerce_value([1, 2], "list") == [1, 2]

    def test_type_matches_int(self):
        assert type_matches(42, "int") is True
        assert type_matches(True, "int") is False  # bool is not int
        assert type_matches("42", "int") is False

    def test_type_matches_float(self):
        assert type_matches(3.14, "float") is True
        assert type_matches(42, "float") is True  # int is acceptable for float
        assert type_matches(True, "float") is False

    def test_type_matches_bool(self):
        assert type_matches(True, "bool") is True
        assert type_matches(False, "bool") is True
        assert type_matches(1, "bool") is False

    def test_type_matches_str(self):
        assert type_matches("hello", "str") is True
        assert type_matches(42, "str") is False

    def test_type_matches_containers(self):
        assert type_matches({}, "dict") is True
        assert type_matches([], "list") is True
        assert type_matches(set(), "set") is True
        assert type_matches([], "set") is True  # list acceptable as set

    def test_type_matches_datetime(self):
        from datetime import datetime
        assert type_matches("2024-01-01T00:00:00Z", "datetime") is True
        assert type_matches(datetime.now(), "datetime") is True

    def test_type_matches_unknown_permissive(self):
        assert type_matches("anything", "custom_type") is True


class TestShapeApply:
    """Tests for Shape.apply() fold execution."""

    def test_apply_count(self):
        s = Shape(
            name="counter",
            folds=(Fold(op="count", target="n"),),
        )
        state = {"n": 0}
        result = s.apply(state, {"anything": True})
        assert result == {"n": 1}

    def test_apply_count_accumulates(self):
        s = Shape(
            name="counter",
            folds=(Fold(op="count", target="n"),),
        )
        state = {"n": 0}
        state = s.apply(state, {})
        state = s.apply(state, {})
        state = s.apply(state, {})
        assert state == {"n": 3}

    def test_apply_sum(self):
        s = Shape(
            name="summer",
            folds=(Fold(op="sum", target="total", props={"field": "amount"}),),
        )
        state = {"total": 0}
        result = s.apply(state, {"amount": 10})
        assert result == {"total": 10}
        result = s.apply(result, {"amount": 5})
        assert result == {"total": 15}

    def test_apply_sum_missing_field_defaults_zero(self):
        s = Shape(
            name="summer",
            folds=(Fold(op="sum", target="total", props={"field": "amount"}),),
        )
        result = s.apply({"total": 7}, {"other": 99})
        assert result == {"total": 7}

    def test_apply_latest(self):
        s = Shape(
            name="tracker",
            folds=(Fold(op="latest", target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {"_ts": 1234567890})
        assert result == {"last_ts": 1234567890}

    def test_apply_latest_uses_time_when_no_ts(self):
        s = Shape(
            name="tracker",
            folds=(Fold(op="latest", target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {})
        assert isinstance(result["last_ts"], float)

    def test_apply_collect(self):
        s = Shape(
            name="collector",
            folds=(Fold(op="collect", target="items"),),
        )
        state = {"items": []}
        state = s.apply(state, {"x": 1})
        state = s.apply(state, {"x": 2})
        assert len(state["items"]) == 2
        assert state["items"][0] == {"x": 1}
        assert state["items"][1] == {"x": 2}

    def test_apply_collect_bounded(self):
        s = Shape(
            name="collector",
            folds=(Fold(op="collect", target="items", props={"max": 2}),),
        )
        state = {"items": []}
        state = s.apply(state, {"v": 1})
        state = s.apply(state, {"v": 2})
        state = s.apply(state, {"v": 3})
        assert len(state["items"]) == 2
        assert state["items"][0] == {"v": 2}
        assert state["items"][1] == {"v": 3}

    def test_apply_upsert(self):
        s = Shape(
            name="registry",
            folds=(Fold(op="upsert", target="users", props={"key": "id"}),),
        )
        state = {"users": {}}
        state = s.apply(state, {"id": "a", "name": "Alice"})
        state = s.apply(state, {"id": "b", "name": "Bob"})
        state = s.apply(state, {"id": "a", "name": "Alicia"})
        assert len(state["users"]) == 2
        assert state["users"]["a"]["name"] == "Alicia"
        assert state["users"]["b"]["name"] == "Bob"

    def test_apply_upsert_ignores_missing_key(self):
        s = Shape(
            name="registry",
            folds=(Fold(op="upsert", target="users", props={"key": "id"}),),
        )
        state = {"users": {}}
        result = s.apply(state, {"name": "NoId"})
        assert result == {"users": {}}

    def test_apply_preserves_immutability(self):
        """apply() returns a new dict, never mutates original."""
        s = Shape(
            name="counter",
            folds=(Fold(op="count", target="n"),),
        )
        original = {"n": 0}
        result = s.apply(original, {})
        assert result == {"n": 1}
        assert original == {"n": 0}

    def test_apply_empty_folds_returns_state_copy(self):
        s = Shape(name="passthrough")
        state = {"x": 1, "y": 2}
        result = s.apply(state, {"z": 3})
        assert result == {"x": 1, "y": 2}
        assert result is not state

    def test_apply_multiple_folds(self):
        s = Shape(
            name="multi",
            folds=(
                Fold(op="count", target="n"),
                Fold(op="sum", target="total", props={"field": "amount"}),
                Fold(op="latest", target="last_ts"),
            ),
        )
        state = {"n": 0, "total": 0, "last_ts": None}
        result = s.apply(state, {"amount": 42, "_ts": 1000})
        assert result == {"n": 1, "total": 42, "last_ts": 1000}

    def test_apply_unknown_op_raises(self):
        s = Shape(
            name="bad",
            folds=(Fold(op="explode", target="x"),),
        )
        with pytest.raises(ValueError, match="Unknown fold op"):
            s.apply({"x": 0}, {})

    def test_apply_upsert_missing_key_prop_raises(self):
        s = Shape(
            name="bad",
            folds=(Fold(op="upsert", target="x"),),
        )
        with pytest.raises(ValueError, match="upsert fold requires key="):
            s.apply({"x": {}}, {})


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_can_raise(self):
        with pytest.raises(ValidationError, match="test error"):
            raise ValidationError("test error")

    def test_message(self):
        err = ValidationError("facet 'x' missing")
        assert str(err) == "facet 'x' missing"
