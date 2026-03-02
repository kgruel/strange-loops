"""Tests for Spec.replay — bulk fold correctness parity with apply()."""

from __future__ import annotations

from atoms import Spec
from atoms.facet import Field
from atoms.fold import Collect, Count, Latest, Sum, Upsert


class TestSpecReplay:
    """Spec.replay() must produce identical final state to sequential apply()."""

    def _apply_loop(self, spec: Spec, payloads: list[dict]) -> dict:
        """Reference implementation: fold via apply() loop."""
        state = spec.initial_state()
        for p in payloads:
            state = spec.apply(state, p)
        return state

    def test_upsert_parity(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="items", kind="dict"),),
            folds=(Upsert(target="items", key="topic"),),
        )
        payloads = [
            {"topic": "a", "msg": "first"},
            {"topic": "b", "msg": "second"},
            {"topic": "a", "msg": "updated"},
        ]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)

    def test_collect_parity(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="items", kind="list"),),
            folds=(Collect(target="items", max=2),),
        )
        payloads = [{"x": 1}, {"x": 2}, {"x": 3}]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)

    def test_count_parity(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="n", kind="int"),),
            folds=(Count(target="n"),),
        )
        payloads = [{}, {}, {}, {}]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)

    def test_sum_parity(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="total", kind="float"),),
            folds=(Sum(target="total", field="value"),),
        )
        payloads = [{"value": 10}, {"value": 20}, {"value": 30}]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)

    def test_latest_parity(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="ts", kind="float"),),
            folds=(Latest(target="ts"),),
        )
        payloads = [{"_ts": 1000.0}, {"_ts": 2000.0}, {"_ts": 3000.0}]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)

    def test_empty_payloads(self):
        spec = Spec(
            name="test",
            state_fields=(Field(name="items", kind="dict"),),
            folds=(Upsert(target="items", key="k"),),
        )
        assert spec.replay([]) == spec.initial_state()

    def test_multiple_folds(self):
        """Spec with multiple fold ops on different targets."""
        spec = Spec(
            name="test",
            state_fields=(
                Field(name="items", kind="dict"),
                Field(name="n", kind="int"),
            ),
            folds=(
                Upsert(target="items", key="name"),
                Count(target="n"),
            ),
        )
        payloads = [
            {"name": "a", "v": 1},
            {"name": "b", "v": 2},
            {"name": "a", "v": 3},
        ]
        assert spec.replay(payloads) == self._apply_loop(spec, payloads)
