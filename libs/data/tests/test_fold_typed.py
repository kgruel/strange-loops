"""Tests for typed fold classes: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max."""

import pytest

from data import (
    Collect,
    Count,
    Facet,
    Latest,
    Max,
    Min,
    Shape,
    Sum,
    TopN,
    Upsert,
)


class TestTypedFoldDataclasses:
    """Tests for typed fold dataclass properties."""

    def test_latest_frozen(self):
        f = Latest(target="last_ts")
        assert f.target == "last_ts"
        with pytest.raises(AttributeError):
            f.target = "other"

    def test_count_frozen(self):
        f = Count(target="n")
        assert f.target == "n"
        with pytest.raises(AttributeError):
            f.target = "other"

    def test_sum_frozen(self):
        f = Sum(target="total", field="amount")
        assert f.target == "total"
        assert f.field == "amount"
        with pytest.raises(AttributeError):
            f.field = "other"

    def test_collect_defaults(self):
        f = Collect(target="items")
        assert f.target == "items"
        assert f.max == 0  # unbounded by default

    def test_collect_with_max(self):
        f = Collect(target="events", max=100)
        assert f.max == 100

    def test_upsert_frozen(self):
        f = Upsert(target="users", key="id")
        assert f.target == "users"
        assert f.key == "id"
        with pytest.raises(AttributeError):
            f.key = "other"

    def test_top_n_defaults(self):
        f = TopN(target="top", key="id", by="score", n=10)
        assert f.target == "top"
        assert f.key == "id"
        assert f.by == "score"
        assert f.n == 10
        assert f.desc is True  # descending by default

    def test_top_n_ascending(self):
        f = TopN(target="bottom", key="id", by="score", n=5, desc=False)
        assert f.desc is False

    def test_min_frozen(self):
        f = Min(target="lowest", field="temp")
        assert f.target == "lowest"
        assert f.field == "temp"

    def test_max_frozen(self):
        f = Max(target="highest", field="temp")
        assert f.target == "highest"
        assert f.field == "temp"


class TestTypedFoldApply:
    """Tests for typed folds applied via Shape.apply()."""

    def test_latest_with_ts(self):
        s = Shape(
            name="tracker",
            folds=(Latest(target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {"_ts": 1234567890})
        assert result == {"last_ts": 1234567890}

    def test_latest_without_ts(self):
        s = Shape(
            name="tracker",
            folds=(Latest(target="last_ts"),),
        )
        result = s.apply({"last_ts": None}, {})
        assert isinstance(result["last_ts"], float)

    def test_count_increments(self):
        s = Shape(
            name="counter",
            folds=(Count(target="n"),),
        )
        state = {"n": 0}
        state = s.apply(state, {})
        state = s.apply(state, {})
        state = s.apply(state, {})
        assert state == {"n": 3}

    def test_sum_accumulates(self):
        s = Shape(
            name="summer",
            folds=(Sum(target="total", field="amount"),),
        )
        state = {"total": 0}
        state = s.apply(state, {"amount": 10})
        state = s.apply(state, {"amount": 5})
        assert state == {"total": 15}

    def test_sum_missing_field_adds_zero(self):
        s = Shape(
            name="summer",
            folds=(Sum(target="total", field="amount"),),
        )
        result = s.apply({"total": 7}, {"other": 99})
        assert result == {"total": 7}

    def test_collect_appends(self):
        s = Shape(
            name="collector",
            folds=(Collect(target="items"),),
        )
        state = {"items": []}
        state = s.apply(state, {"x": 1})
        state = s.apply(state, {"x": 2})
        assert len(state["items"]) == 2
        assert state["items"][0] == {"x": 1}
        assert state["items"][1] == {"x": 2}

    def test_collect_bounded(self):
        s = Shape(
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

    def test_upsert_inserts_and_updates(self):
        s = Shape(
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

    def test_upsert_ignores_missing_key(self):
        s = Shape(
            name="registry",
            folds=(Upsert(target="users", key="id"),),
        )
        state = {"users": {}}
        result = s.apply(state, {"name": "NoId"})
        assert result == {"users": {}}


class TestTopN:
    """Tests for TopN convenience fold."""

    def test_top_n_keeps_highest(self):
        s = Shape(
            name="top_procs",
            folds=(TopN(target="procs", key="pid", by="cpu", n=3),),
        )
        state = {"procs": {}}
        state = s.apply(state, {"pid": "a", "cpu": 10})
        state = s.apply(state, {"pid": "b", "cpu": 30})
        state = s.apply(state, {"pid": "c", "cpu": 20})
        state = s.apply(state, {"pid": "d", "cpu": 50})  # should evict lowest

        assert len(state["procs"]) == 3
        assert "a" not in state["procs"]  # evicted (lowest)
        assert state["procs"]["b"]["cpu"] == 30
        assert state["procs"]["c"]["cpu"] == 20
        assert state["procs"]["d"]["cpu"] == 50

    def test_top_n_ascending(self):
        s = Shape(
            name="bottom_procs",
            folds=(TopN(target="procs", key="pid", by="cpu", n=2, desc=False),),
        )
        state = {"procs": {}}
        state = s.apply(state, {"pid": "a", "cpu": 10})
        state = s.apply(state, {"pid": "b", "cpu": 30})
        state = s.apply(state, {"pid": "c", "cpu": 20})

        assert len(state["procs"]) == 2
        # Keep lowest 2: a (10), c (20)
        assert "a" in state["procs"]
        assert "c" in state["procs"]
        assert "b" not in state["procs"]  # evicted (highest)

    def test_top_n_updates_existing(self):
        s = Shape(
            name="top_procs",
            folds=(TopN(target="procs", key="pid", by="cpu", n=2),),
        )
        state = {"procs": {}}
        state = s.apply(state, {"pid": "a", "cpu": 10})
        state = s.apply(state, {"pid": "b", "cpu": 20})
        # Update a's CPU to be highest
        state = s.apply(state, {"pid": "a", "cpu": 50})

        assert state["procs"]["a"]["cpu"] == 50

    def test_top_n_ignores_missing_fields(self):
        s = Shape(
            name="top_procs",
            folds=(TopN(target="procs", key="pid", by="cpu", n=2),),
        )
        state = {"procs": {}}
        state = s.apply(state, {"pid": "a", "cpu": 10})
        state = s.apply(state, {"pid": "b"})  # missing cpu
        state = s.apply(state, {"cpu": 20})  # missing pid

        assert len(state["procs"]) == 1
        assert "a" in state["procs"]


class TestMinMax:
    """Tests for Min and Max convenience folds."""

    def test_min_tracks_minimum(self):
        s = Shape(
            name="temp_tracker",
            folds=(Min(target="coldest", field="temp"),),
        )
        state = {"coldest": None}
        state = s.apply(state, {"temp": 20})
        assert state["coldest"] == 20

        state = s.apply(state, {"temp": 15})
        assert state["coldest"] == 15

        state = s.apply(state, {"temp": 25})  # higher, should not update
        assert state["coldest"] == 15

    def test_max_tracks_maximum(self):
        s = Shape(
            name="temp_tracker",
            folds=(Max(target="hottest", field="temp"),),
        )
        state = {"hottest": None}
        state = s.apply(state, {"temp": 20})
        assert state["hottest"] == 20

        state = s.apply(state, {"temp": 25})
        assert state["hottest"] == 25

        state = s.apply(state, {"temp": 15})  # lower, should not update
        assert state["hottest"] == 25

    def test_min_ignores_missing_field(self):
        s = Shape(
            name="tracker",
            folds=(Min(target="min", field="value"),),
        )
        state = {"min": None}
        result = s.apply(state, {"other": 10})
        assert result["min"] is None

    def test_max_ignores_missing_field(self):
        s = Shape(
            name="tracker",
            folds=(Max(target="max", field="value"),),
        )
        state = {"max": None}
        result = s.apply(state, {"other": 10})
        assert result["max"] is None

    def test_min_handles_first_value_from_none(self):
        s = Shape(
            name="tracker",
            folds=(Min(target="min", field="value"),),
        )
        state = {"min": None}
        result = s.apply(state, {"value": 42})
        assert result["min"] == 42

    def test_max_handles_first_value_from_none(self):
        s = Shape(
            name="tracker",
            folds=(Max(target="max", field="value"),),
        )
        state = {"max": None}
        result = s.apply(state, {"value": 42})
        assert result["max"] == 42


class TestMultipleFolds:
    """Tests combining multiple typed folds."""

    def test_multiple_typed_folds(self):
        s = Shape(
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


class TestImmutability:
    """Tests that typed folds preserve immutability guarantees."""

    def test_collect_does_not_mutate_original(self):
        s = Shape(
            name="collector",
            folds=(Collect(target="items"),),
        )
        original = {"items": [{"v": 1}]}
        result = s.apply(original, {"v": 2})
        assert result["items"] == [{"v": 1}, {"v": 2}]
        assert original["items"] == [{"v": 1}], "original list was mutated"

    def test_upsert_does_not_mutate_original(self):
        s = Shape(
            name="registry",
            folds=(Upsert(target="users", key="id"),),
        )
        original = {"users": {"a": {"id": "a", "name": "Alice"}}}
        result = s.apply(original, {"id": "b", "name": "Bob"})
        assert "b" in result["users"]
        assert "b" not in original["users"], "original dict was mutated"

    def test_top_n_does_not_mutate_original(self):
        s = Shape(
            name="top",
            folds=(TopN(target="items", key="id", by="score", n=2),),
        )
        original = {"items": {"a": {"id": "a", "score": 10}}}
        result = s.apply(original, {"id": "b", "score": 20})
        assert "b" in result["items"]
        assert "b" not in original["items"], "original dict was mutated"
