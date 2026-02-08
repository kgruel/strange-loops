"""Tests for specs core types: Field, Spec, Boundary, and typed folds."""

import pytest

from atoms import (
    Boundary,
    Collect,
    Count,
    Facet,
    Field,
    Latest,
    Shape,
    Spec,
    Sum,
    Upsert,
    ValidationError,
)
from atoms.types import coerce_value, initial_value, type_matches


class TestField:
    """Tests for Field dataclass."""

    def test_basic_field(self):
        f = Field(name="count", kind="int")
        assert f.name == "count"
        assert f.kind == "int"
        assert f.optional is False

    def test_optional_field(self):
        f = Field(name="label", kind="str", optional=True)
        assert f.optional is True

    def test_from_type_str_required(self):
        f = Field.from_type_str("age", "int")
        assert f.name == "age"
        assert f.kind == "int"
        assert f.optional is False

    def test_from_type_str_optional(self):
        f = Field.from_type_str("nickname", "str?")
        assert f.name == "nickname"
        assert f.kind == "str"
        assert f.optional is True

    def test_frozen(self):
        f = Field(name="x", kind="int")
        with pytest.raises(AttributeError):
            f.name = "y"


class TestFacetBackwardCompat:
    """Tests for Facet backward compatibility alias."""

    def test_facet_is_field(self):
        assert Facet is Field

    def test_facet_creates_field(self):
        f = Facet(name="count", kind="int")
        assert isinstance(f, Field)
        assert f.name == "count"


class TestSpec:
    """Tests for Spec dataclass."""

    def test_empty_spec(self):
        f = Spec(name="empty")
        assert f.name == "empty"
        assert f.about == ""
        assert f.input_fields == ()
        assert f.state_fields == ()
        assert f.folds == ()

    def test_spec_with_about(self):
        f = Spec(name="counter", about="Counts events")
        assert f.about == "Counts events"

    def test_spec_with_fields(self):
        f = Spec(
            name="tracker",
            input_fields=(
                Field("user_id", "str"),
                Field("action", "str"),
            ),
            state_fields=(
                Field("count", "int"),
                Field("users", "set"),
            ),
        )
        assert len(f.input_fields) == 2
        assert len(f.state_fields) == 2

    def test_spec_with_folds(self):
        f = Spec(
            name="accumulator",
            folds=(
                Count(target="total"),
                Upsert(target="seen", key="id"),
            ),
        )
        assert len(f.folds) == 2

    def test_initial_state_dict(self):
        f = Spec(
            name="test",
            state_fields=(Field("items", "dict"),),
        )
        assert f.initial_state() == {"items": {}}

    def test_initial_state_list(self):
        f = Spec(
            name="test",
            state_fields=(Field("events", "list"),),
        )
        assert f.initial_state() == {"events": []}

    def test_initial_state_set(self):
        f = Spec(
            name="test",
            state_fields=(Field("seen", "set"),),
        )
        assert f.initial_state() == {"seen": set()}

    def test_initial_state_int(self):
        f = Spec(
            name="test",
            state_fields=(Field("count", "int"),),
        )
        assert f.initial_state() == {"count": 0}

    def test_initial_state_float(self):
        f = Spec(
            name="test",
            state_fields=(Field("total", "float"),),
        )
        assert f.initial_state() == {"total": 0}

    def test_initial_state_bool(self):
        f = Spec(
            name="test",
            state_fields=(Field("active", "bool"),),
        )
        assert f.initial_state() == {"active": False}

    def test_initial_state_str(self):
        f = Spec(
            name="test",
            state_fields=(Field("label", "str"),),
        )
        assert f.initial_state() == {"label": ""}

    def test_initial_state_datetime(self):
        f = Spec(
            name="test",
            state_fields=(Field("last_seen", "datetime"),),
        )
        assert f.initial_state() == {"last_seen": None}

    def test_initial_state_multiple_fields(self):
        f = Spec(
            name="complex",
            state_fields=(
                Field("count", "int"),
                Field("items", "dict"),
                Field("events", "list"),
                Field("seen", "set"),
            ),
        )
        state = f.initial_state()
        assert state == {
            "count": 0,
            "items": {},
            "events": [],
            "seen": set(),
        }

    def test_input_field_lookup(self):
        f = Spec(
            name="test",
            input_fields=(
                Field("user_id", "str"),
                Field("amount", "int"),
            ),
        )
        assert f.input_field("user_id") == Field("user_id", "str")
        assert f.input_field("amount") == Field("amount", "int")
        assert f.input_field("missing") is None

    def test_state_field_lookup(self):
        f = Spec(
            name="test",
            state_fields=(
                Field("total", "int"),
                Field("items", "dict"),
            ),
        )
        assert f.state_field("total") == Field("total", "int")
        assert f.state_field("items") == Field("items", "dict")
        assert f.state_field("missing") is None

    def test_frozen(self):
        f = Spec(name="test")
        with pytest.raises(AttributeError):
            f.name = "other"


class TestSpecBackwardCompat:
    """Tests for Spec backward compatibility aliases."""

    def test_shape_is_spec(self):
        assert Shape is Spec

    def test_input_facets_alias(self):
        f = Spec(
            name="test",
            input_fields=(Field("x", "int"),),
        )
        assert f.input_facets == f.input_fields
        assert f.input_facets == (Field("x", "int"),)

    def test_state_facets_alias(self):
        f = Spec(
            name="test",
            state_fields=(Field("y", "str"),),
        )
        assert f.state_facets == f.state_fields
        assert f.state_facets == (Field("y", "str"),)

    def test_input_facet_method_alias(self):
        f = Spec(
            name="test",
            input_fields=(Field("x", "int"),),
        )
        assert f.input_facet("x") == f.input_field("x")

    def test_state_facet_method_alias(self):
        f = Spec(
            name="test",
            state_fields=(Field("y", "str"),),
        )
        assert f.state_facet("y") == f.state_field("y")


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


class TestSpecApply:
    """Tests for Spec.apply() fold execution."""

    def test_apply_count(self):
        s = Spec(
            name="counter",
            folds=(Count(target="n"),),
        )
        state = {"n": 0}
        result = s.apply(state, {"anything": True})
        assert result == {"n": 1}

    def test_apply_count_accumulates(self):
        s = Spec(
            name="counter",
            folds=(Count(target="n"),),
        )
        state = {"n": 0}
        state = s.apply(state, {})
        state = s.apply(state, {})
        state = s.apply(state, {})
        assert state == {"n": 3}

    def test_apply_sum(self):
        s = Spec(
            name="summer",
            folds=(Sum(target="total", field="amount"),),
        )
        state = {"total": 0}
        result = s.apply(state, {"amount": 10})
        assert result == {"total": 10}
        result = s.apply(result, {"amount": 5})
        assert result == {"total": 15}

    def test_apply_sum_missing_field_defaults_zero(self):
        s = Spec(
            name="summer",
            folds=(Sum(target="total", field="amount"),),
        )
        result = s.apply({"total": 7}, {"other": 99})
        assert result == {"total": 7}

    def test_apply_latest(self):
        s = Spec(
            name="tracker",
            folds=(Latest(target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {"_ts": 1234567890})
        assert result == {"last_ts": 1234567890}

    def test_apply_latest_uses_time_when_no_ts(self):
        s = Spec(
            name="tracker",
            folds=(Latest(target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {})
        assert isinstance(result["last_ts"], float)

    def test_apply_collect(self):
        s = Spec(
            name="collector",
            folds=(Collect(target="items"),),
        )
        state = {"items": []}
        state = s.apply(state, {"x": 1})
        state = s.apply(state, {"x": 2})
        assert len(state["items"]) == 2
        assert state["items"][0] == {"x": 1}
        assert state["items"][1] == {"x": 2}

    def test_apply_collect_bounded(self):
        s = Spec(
            name="collector",
            folds=(Collect(target="items", max=2),),
        )
        state = {"items": []}
        state = s.apply(state, {"v": 1})
        state = s.apply(state, {"v": 2})
        state = s.apply(state, {"v": 3})
        assert len(state["items"]) == 2
        assert state["items"][0] == {"v": 2}
        assert state["items"][1] == {"v": 3}

    def test_apply_upsert(self):
        s = Spec(
            name="registry",
            folds=(Upsert(target="users", key="id"),),
        )
        state = {"users": {}}
        state = s.apply(state, {"id": "a", "name": "Alice"})
        state = s.apply(state, {"id": "b", "name": "Bob"})
        state = s.apply(state, {"id": "a", "name": "Alicia"})
        assert len(state["users"]) == 2
        assert state["users"]["a"]["name"] == "Alicia"
        assert state["users"]["b"]["name"] == "Bob"

    def test_apply_upsert_ignores_missing_key(self):
        s = Spec(
            name="registry",
            folds=(Upsert(target="users", key="id"),),
        )
        state = {"users": {}}
        result = s.apply(state, {"name": "NoId"})
        assert result == {"users": {}}

    def test_apply_preserves_immutability(self):
        """apply() returns a new dict, never mutates original."""
        s = Spec(
            name="counter",
            folds=(Count(target="n"),),
        )
        original = {"n": 0}
        result = s.apply(original, {})
        assert result == {"n": 1}
        assert original == {"n": 0}

    def test_apply_empty_folds_returns_state_copy(self):
        s = Spec(name="passthrough")
        state = {"x": 1, "y": 2}
        result = s.apply(state, {"z": 3})
        assert result == {"x": 1, "y": 2}
        assert result is not state

    def test_apply_multiple_folds(self):
        s = Spec(
            name="multi",
            folds=(
                Count(target="n"),
                Sum(target="total", field="amount"),
                Latest(target="last_ts"),
            ),
        )
        state = {"n": 0, "total": 0, "last_ts": None}
        result = s.apply(state, {"amount": 42, "_ts": 1000})
        assert result == {"n": 1, "total": 42, "last_ts": 1000}


class TestApplyPurity:
    """Tests that Spec.apply() never mutates the original state's nested containers."""

    def test_collect_does_not_mutate_original_list(self):
        """apply() with collect must not modify the original state's list."""
        s = Spec(
            name="collector",
            folds=(Collect(target="items"),),
        )
        original = {"items": [{"v": 1}]}
        result = s.apply(original, {"v": 2})
        assert result["items"] == [{"v": 1}, {"v": 2}]
        assert original["items"] == [{"v": 1}], "original list was mutated"

    def test_upsert_does_not_mutate_original_dict(self):
        """apply() with upsert must not modify the original state's nested dict."""
        s = Spec(
            name="registry",
            folds=(Upsert(target="users", key="id"),),
        )
        original = {"users": {"a": {"id": "a", "name": "Alice"}}}
        result = s.apply(original, {"id": "b", "name": "Bob"})
        assert "b" in result["users"]
        assert "b" not in original["users"], "original dict was mutated"

    def test_two_applies_from_same_base_are_independent(self):
        """Two apply() calls from the same base state produce independent results."""
        s = Spec(
            name="collector",
            folds=(Collect(target="items"),),
        )
        base = {"items": []}
        r1 = s.apply(base, {"v": 1})
        r2 = s.apply(base, {"v": 2})
        assert r1["items"] == [{"v": 1}]
        assert r2["items"] == [{"v": 2}]
        assert base["items"] == [], "base state was mutated"
        assert r1["items"] is not r2["items"], "results share the same list object"


class TestBoundary:
    """Tests for Boundary dataclass."""

    def test_basic_boundary(self):
        b = Boundary(kind="deploy")
        assert b.kind == "deploy"
        assert b.reset is True

    def test_boundary_reset_false(self):
        b = Boundary(kind="heartbeat", reset=False)
        assert b.kind == "heartbeat"
        assert b.reset is False

    def test_boundary_reset_true_explicit(self):
        b = Boundary(kind="cycle-end", reset=True)
        assert b.reset is True

    def test_frozen(self):
        b = Boundary(kind="deploy")
        with pytest.raises(AttributeError):
            b.kind = "other"

    def test_equality(self):
        b1 = Boundary(kind="deploy", reset=True)
        b2 = Boundary(kind="deploy", reset=True)
        assert b1 == b2

    def test_inequality_kind(self):
        b1 = Boundary(kind="deploy")
        b2 = Boundary(kind="heartbeat")
        assert b1 != b2

    def test_inequality_reset(self):
        b1 = Boundary(kind="deploy", reset=True)
        b2 = Boundary(kind="deploy", reset=False)
        assert b1 != b2


class TestSpecBoundary:
    """Tests for Spec with boundary field."""

    def test_spec_default_no_boundary(self):
        s = Spec(name="continuous")
        assert s.boundary is None

    def test_spec_with_boundary(self):
        b = Boundary(kind="deploy")
        s = Spec(name="deploy-monitor", boundary=b)
        assert s.boundary is not None
        assert s.boundary.kind == "deploy"
        assert s.boundary.reset is True

    def test_spec_with_carry_boundary(self):
        b = Boundary(kind="heartbeat", reset=False)
        s = Spec(
            name="health-check",
            state_fields=(Field("count", "int"),),
            folds=(Count(target="count"),),
            boundary=b,
        )
        assert s.boundary.reset is False

    def test_spec_boundary_does_not_affect_apply(self):
        """Boundary is declarative — apply() behavior is unchanged."""
        b = Boundary(kind="deploy")
        s = Spec(
            name="counter",
            folds=(Count(target="n"),),
            boundary=b,
        )
        result = s.apply({"n": 0}, {})
        assert result == {"n": 1}

    def test_spec_frozen_boundary(self):
        b = Boundary(kind="deploy")
        s = Spec(name="test", boundary=b)
        with pytest.raises(AttributeError):
            s.boundary = None


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_can_raise(self):
        with pytest.raises(ValidationError, match="test error"):
            raise ValidationError("test error")

    def test_message(self):
        err = ValidationError("field 'x' missing")
        assert str(err) == "field 'x' missing"
