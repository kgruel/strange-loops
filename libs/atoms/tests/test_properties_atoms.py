"""Property-based tests for atoms invariants using Hypothesis."""

from __future__ import annotations

import copy
from types import MappingProxyType
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from atoms import (
    Avg,
    Collect,
    Count,
    Fact,
    Field,
    FoldOp,
    Latest,
    Max,
    Min,
    Spec,
    Sum,
    TopN,
    Upsert,
    Window,
)
from tests.strategies import (
    fact_lists,
    facts,
    fold_ops,
    payloads,
    timestamps,
)

# =============================================================================
# 1. Fact Construction and Serialization Roundtrip
# =============================================================================


class TestFactProperties:
    """Property tests for Fact atom invariants."""

    @settings(max_examples=200)
    @given(fact=facts())
    def test_fact_dict_roundtrip_fixpoint(self, fact: Fact) -> None:
        """Any valid Fact serializes to a dict and deserializes to an equal Fact at fixpoint."""
        d = fact.to_dict()
        reconstructed = Fact.from_dict(d)

        # 1. Reconstructed fact equals original fact
        assert reconstructed == fact
        assert reconstructed.kind == fact.kind
        assert reconstructed.ts == fact.ts
        assert reconstructed.observer == fact.observer
        assert reconstructed.origin == fact.origin
        assert reconstructed.payload == fact.payload

        # 2. Fixpoint: re-serializing yields identical dict and second deserialization is identical
        d2 = reconstructed.to_dict()
        assert d2 == d
        reconstructed2 = Fact.from_dict(d2)
        assert reconstructed2 == reconstructed

    @settings(max_examples=200)
    @given(fact=facts(), new_ts=timestamps())
    def test_fact_replace_preserves_untouched_fields(self, fact: Fact, new_ts: float) -> None:
        """Replacing a Fact field via __replace__ updates it while preserving untouched fields."""
        replaced = fact.__replace__(ts=new_ts)
        assert replaced.ts == new_ts
        assert replaced.kind == fact.kind
        assert replaced.payload == fact.payload
        assert replaced.observer == fact.observer
        assert replaced.origin == fact.origin

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "FINDING: Fact.__hash__ hashes id(payload) on dict payloads, "
            "violating hash equality for equal facts"
        ),
    )
    @settings(max_examples=200)
    @given(fact=facts())
    def test_fact_hash_equality_consistency(self, fact: Fact) -> None:
        """Equal facts produce identical hash values and can be safely collected into sets."""
        d = fact.to_dict()
        twin = Fact.from_dict(d)
        assert hash(fact) == hash(twin)
        assert len({fact, twin}) == 1


# =============================================================================
# 2. Fold State Determinism and Equivalence
# =============================================================================


def _spec_for_fold_op(op: FoldOp) -> Spec:
    """Construct a Spec with appropriate initial state fields for a given FoldOp."""
    state_fields: list[Field] = []
    if isinstance(op, (Collect, Window)):
        state_fields.append(Field(name=op.target, kind="list"))
    elif isinstance(op, (Upsert, TopN)):
        state_fields.append(Field(name=op.target, kind="dict"))
    elif isinstance(op, Count):
        state_fields.append(Field(name=op.target, kind="int"))
    elif isinstance(op, (Sum, Min, Max, Avg, Latest)):
        state_fields.append(Field(name=op.target, kind="float"))

    return Spec(
        name="test_spec",
        state_fields=tuple(state_fields),
        folds=(op,),
    )


def _prepare_payloads_from_facts(fact_list: list[Fact]) -> list[dict[str, Any]]:
    """Convert a list of facts into a list of dict payloads with _ts injected."""
    result: list[dict[str, Any]] = []
    for f in fact_list:
        if isinstance(f.payload, (dict, MappingProxyType)):
            p = dict(f.payload)
        else:
            p = {"val": f.payload, "amount": f.payload, "score": f.payload}
        p["_ts"] = f.ts
        result.append(p)
    return result


class TestFoldDeterminismProperties:
    """Property tests for Spec fold computation determinism and purity."""

    @settings(max_examples=200)
    @given(fact_list=fact_lists(), op=fold_ops())
    def test_fold_replay_determinism(self, fact_list: list[Fact], op: FoldOp) -> None:
        """Replaying a fact sequence through a Spec produces identical state deterministically."""
        spec = _spec_for_fold_op(op)
        payloads_seq = _prepare_payloads_from_facts(fact_list)

        state1 = spec.replay(payloads_seq)
        state2 = spec.replay(payloads_seq)
        assert state1 == state2

    @settings(max_examples=200)
    @given(fact_list=fact_lists(), op=fold_ops())
    def test_fold_apply_equals_replay(self, fact_list: list[Fact], op: FoldOp) -> None:
        """Iterative Spec.apply from initial_state produces the same final state as Spec.replay."""
        spec = _spec_for_fold_op(op)
        payloads_seq = _prepare_payloads_from_facts(fact_list)

        replay_state = spec.replay(payloads_seq)

        apply_state = spec.initial_state()
        for p in payloads_seq:
            apply_state = spec.apply(apply_state, p)

        assert apply_state == replay_state

    @settings(max_examples=200)
    @given(fact=facts(), op=fold_ops())
    def test_fold_apply_purity(self, fact: Fact, op: FoldOp) -> None:
        """Spec.apply is pure and never mutates the input state dictionary in place."""
        spec = _spec_for_fold_op(op)
        payload = dict(fact.payload) if isinstance(fact.payload, dict) else {"val": fact.payload}
        payload["_ts"] = fact.ts

        initial = spec.initial_state()
        snapshot = copy.deepcopy(initial)

        _ = spec.apply(initial, payload)
        assert initial == snapshot


# =============================================================================
# 3. Fold-Key Sensitivity Probe
# =============================================================================


class TestFoldKeySensitivityProperties:
    """Probe tests documenting the engine's fold-key type sensitivity."""

    @settings(max_examples=200)
    @given(
        val_zero=payloads(),
        val_str_zero=payloads(),
        ts1=timestamps(),
        ts2=timestamps(),
    )
    def test_fold_key_sensitivity_zero_vs_string_zero_distinct_keys(
        self,
        val_zero: dict[str, Any],
        val_str_zero: dict[str, Any],
        ts1: float,
        ts2: float,
    ) -> None:
        """Keyed upsert folds treat integer 0 and string '0' as different keys in fold state."""
        spec = Spec(
            name="key_probe",
            state_fields=(Field(name="entities", kind="dict"),),
            folds=(Upsert(target="entities", key="id"),),
        )

        p1 = {**val_zero, "id": 0, "_ts": ts1}
        p2 = {**val_str_zero, "id": "0", "_ts": ts2}

        state = spec.replay([p1, p2])

        # Observed behavior: int 0 and str "0" do not collide in state dict
        assert 0 in state["entities"]
        assert "0" in state["entities"]
        assert len(state["entities"]) == 2
        assert state["entities"][0]["id"] == 0
        assert state["entities"]["0"]["id"] == "0"
        assert state["entities"][0]["_n"] == 1
        assert state["entities"]["0"]["_n"] == 1

    @settings(max_examples=200)
    @given(
        val_int=st.text(max_size=10),
        val_float=st.text(max_size=10),
        val_bool=st.text(max_size=10),
    )
    def test_fold_key_numeric_and_bool_zero_collide(
        self,
        val_int: str,
        val_float: str,
        val_bool: str,
    ) -> None:
        """Keyed upsert folds treat 0, 0.0, and False as same key under Python dict semantics."""
        spec = Spec(
            name="numeric_key_probe",
            state_fields=(Field(name="entities", kind="dict"),),
            folds=(Upsert(target="entities", key="id"),),
        )

        p1 = {"id": 0, "msg": val_int, "_ts": 1.0}
        p2 = {"id": 0.0, "msg": val_float, "_ts": 2.0}
        p3 = {"id": False, "msg": val_bool, "_ts": 3.0}

        state = spec.replay([p1, p2, p3])

        # Observed behavior: 0, 0.0, False share the same dict bucket in Python
        assert len(state["entities"]) == 1
        assert state["entities"][0]["_n"] == 3
