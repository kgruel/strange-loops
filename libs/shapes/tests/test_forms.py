"""Tests for forms core types: Field, Fold, Form."""

import pytest

from forms import Field, Fold, Form, ValidationError
from forms.types import coerce_value, initial_value, type_matches


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


class TestForm:
    """Tests for Form dataclass."""

    def test_empty_form(self):
        f = Form(name="empty")
        assert f.name == "empty"
        assert f.about == ""
        assert f.input_fields == ()
        assert f.state_fields == ()
        assert f.folds == ()

    def test_form_with_about(self):
        f = Form(name="counter", about="Counts events")
        assert f.about == "Counts events"

    def test_form_with_fields(self):
        f = Form(
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

    def test_form_with_folds(self):
        f = Form(
            name="accumulator",
            folds=(
                Fold(op="count", target="total"),
                Fold(op="upsert", target="seen", props={"key": "id"}),
            ),
        )
        assert len(f.folds) == 2

    def test_initial_state_dict(self):
        f = Form(
            name="test",
            state_fields=(Field("items", "dict"),),
        )
        assert f.initial_state() == {"items": {}}

    def test_initial_state_list(self):
        f = Form(
            name="test",
            state_fields=(Field("events", "list"),),
        )
        assert f.initial_state() == {"events": []}

    def test_initial_state_set(self):
        f = Form(
            name="test",
            state_fields=(Field("seen", "set"),),
        )
        assert f.initial_state() == {"seen": set()}

    def test_initial_state_int(self):
        f = Form(
            name="test",
            state_fields=(Field("count", "int"),),
        )
        assert f.initial_state() == {"count": 0}

    def test_initial_state_float(self):
        f = Form(
            name="test",
            state_fields=(Field("total", "float"),),
        )
        assert f.initial_state() == {"total": 0}

    def test_initial_state_bool(self):
        f = Form(
            name="test",
            state_fields=(Field("active", "bool"),),
        )
        assert f.initial_state() == {"active": False}

    def test_initial_state_str(self):
        f = Form(
            name="test",
            state_fields=(Field("label", "str"),),
        )
        assert f.initial_state() == {"label": ""}

    def test_initial_state_datetime(self):
        f = Form(
            name="test",
            state_fields=(Field("last_seen", "datetime"),),
        )
        assert f.initial_state() == {"last_seen": None}

    def test_initial_state_multiple_fields(self):
        f = Form(
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
        f = Form(
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
        f = Form(
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
        f = Form(name="test")
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


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_can_raise(self):
        with pytest.raises(ValidationError, match="test error"):
            raise ValidationError("test error")

    def test_message(self):
        err = ValidationError("field 'x' missing")
        assert str(err) == "field 'x' missing"
