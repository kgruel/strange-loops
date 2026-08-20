"""Ordering vectors — the declared read order and its one totalization."""

from dataclasses import FrozenInstanceError

import pytest

from atoms import (
    Arrival,
    ByKey,
    OrderingError,
    resolve_key_field,
    resolve_payload_key,
    totalize,
)


def rec(id_, **fields):
    return {"id": id_, **fields}


class TestByKey:
    def test_sorts_by_key_then_id_ascending(self):
        # Equal K: id breaks the tie, ascending — and the ids are deliberately
        # out of input order, so dropping the tie-break shows up here.
        records = [rec("c", ts=5), rec("a", ts=5), rec("b", ts=1)]
        assert [r["id"] for r in totalize(records, ByKey("ts"))] == ["b", "a", "c"]

    def test_id_is_tie_break_only_never_semantic_time(self):
        # A low key with a high id still sorts before a high key with a low id.
        records = [rec("z", ts=1), rec("a", ts=2)]
        assert [r["id"] for r in totalize(records, ByKey("ts"))] == ["z", "a"]

    def test_key_may_be_any_flat_payload_field(self):
        records = [rec("a", name="pear"), rec("b", name="apple")]
        assert [r["id"] for r in totalize(records, ByKey("name"))] == ["b", "a"]

    def test_returns_a_new_list_leaving_input_order_alone(self):
        records = [rec("a", ts=2), rec("b", ts=1)]
        out = totalize(records, ByKey("ts"))
        assert out is not records
        assert [r["id"] for r in records] == ["a", "b"]

    def test_reads_attributes_when_records_are_not_mappings(self):
        class Row:
            def __init__(self, id, ts):
                self.id = id
                self.ts = ts

        rows = [Row("a", 2), Row("b", 1)]
        assert [r.id for r in totalize(rows, ByKey("ts"))] == ["b", "a"]

    def test_custom_accessors_order_row_tuples(self):
        rows = [("a", 2), ("b", 1)]
        out = totalize(
            rows,
            ByKey("ts"),
            get_field=lambda r, field: r[1],
            get_id=lambda r: r[0],
        )
        assert out == [("b", 1), ("a", 2)]


class TestMissingKey:
    def test_record_without_the_key_is_not_in_the_projection(self):
        records = [rec("a", ts=2), rec("b"), rec("c", ts=1)]
        assert [r["id"] for r in totalize(records, ByKey("ts"))] == ["c", "a"]

    def test_none_value_counts_as_absent(self):
        records = [rec("a", ts=2), rec("b", ts=None), rec("c", ts=1)]
        assert [r["id"] for r in totalize(records, ByKey("ts"))] == ["c", "a"]

    def test_no_record_carries_the_key_yields_an_empty_projection(self):
        assert totalize([rec("a"), rec("b")], ByKey("ts")) == []

    def test_a_keyed_record_with_no_id_raises_the_raw_accessor_error(self):
        # Ruled posture, not an accident: OrderingError means "this ordering
        # does not fit this data". A record with no id is a broken record —
        # the substrate's failure, not the declaration's — so the accessor's
        # own KeyError surfaces unwrapped.
        with pytest.raises(KeyError):
            totalize([{"ts": 1}], ByKey("ts"))

    def test_a_record_missing_the_key_never_reaches_the_id_accessor(self):
        # Same record, minus the key: excluded before the id is ever read.
        assert totalize([{"other": 1}], ByKey("ts")) == []


class TestMixedTypes:
    def test_string_and_int_under_one_key_refuse(self):
        records = [rec("a", ts="5"), rec("b", ts=5)]
        with pytest.raises(OrderingError) as exc:
            totalize(records, ByKey("ts"))
        message = str(exc.value)
        assert "ts" in message
        assert "str" in message and "int" in message

    def test_bool_is_not_int(self):
        records = [rec("a", flag=1), rec("b", flag=True)]
        with pytest.raises(OrderingError):
            totalize(records, ByKey("flag"))

    def test_int_and_float_under_one_key_refuse(self):
        # Strict same-type refusal: no coercion, even across numeric types.
        records = [rec("a", ts=1), rec("b", ts=2.0)]
        with pytest.raises(OrderingError):
            totalize(records, ByKey("ts"))

    def test_same_typed_values_that_do_not_compare_refuse(self):
        records = [rec("a", ts={"x": 1}), rec("b", ts={"y": 2})]
        with pytest.raises(OrderingError) as exc:
            totalize(records, ByKey("ts"))
        assert "do not compare" in str(exc.value)

    def test_refusal_does_not_blame_the_key_when_the_ids_are_at_fault(self):
        # Equal K, so the sort falls through to the id tie-break — and THOSE
        # do not compare. The key values here are impeccable ints, so a
        # message naming "key values" would point at the wrong tuple element.
        records = [rec({"a": 1}, ts=1), rec({"b": 2}, ts=1)]
        with pytest.raises(OrderingError) as exc:
            totalize(records, ByKey("ts"))
        assert "(K, id)" in str(exc.value)

    def test_records_missing_the_key_do_not_participate_in_the_type_check(self):
        records = [rec("a", ts=2), rec("b"), rec("c", ts=1)]
        assert [r["id"] for r in totalize(records, ByKey("ts"))] == ["c", "a"]


class TestArrival:
    def test_returns_records_in_the_order_given(self):
        records = [rec("c", ts=5), rec("a", ts=1), rec("b", ts=3)]
        assert [r["id"] for r in totalize(records, Arrival())] == ["c", "a", "b"]

    def test_never_synthesizes_order_from_fields_or_id(self):
        # Records with neither an id nor any field: Arrival still works, which
        # pins that the totalization does not reach into the record at all.
        records = [{"n": 2}, {"n": 1}]
        assert totalize(records, Arrival()) == [{"n": 2}, {"n": 1}]

    def test_materializes_an_iterator_into_a_list(self):
        assert totalize(iter([rec("a"), rec("b")]), Arrival()) == [
            {"id": "a"},
            {"id": "b"},
        ]


class TestVariants:
    def test_both_variants_are_frozen_and_compare_by_value(self):
        assert Arrival() == Arrival()
        assert ByKey("ts") == ByKey("ts")
        assert ByKey("ts") != ByKey("name")
        assert {Arrival(), ByKey("ts")}  # hashable
        with pytest.raises(FrozenInstanceError):
            ByKey("ts").field = "name"

    def test_unknown_ordering_refuses(self):
        with pytest.raises(OrderingError):
            totalize([rec("a")], "ts")  # type: ignore[arg-type]


class TestKeyFamilyRule:
    """`resolve_key_field` — which keys come from the envelope, which don't."""

    def test_envelope_keys_come_off_the_envelope(self):
        record = {"id": "a", "ts": 5.0, "payload": {"n": 1}}
        assert resolve_key_field(record, "ts") == 5.0
        assert resolve_key_field(record, "id") == "a"

    def test_a_payload_field_never_shadows_the_envelope(self):
        record = {"id": "a", "ts": 5.0, "payload": {"ts": 999.0, "id": "shadow"}}
        assert resolve_key_field(record, "ts") == 5.0
        assert resolve_key_field(record, "id") == "a"

    def test_every_other_key_comes_off_the_payload(self):
        assert resolve_key_field({"id": "a", "payload": {"n": 7}}, "n") == 7

    @pytest.mark.parametrize("payload", ["raw", 7, 1.5, True, ["a", "b"], None])
    def test_a_non_mapping_payload_has_no_fields_at_all(self, payload):
        """A scalar/list payload is a missing-K NON-MEMBER, not a crash.

        `Fact` permits any JSON payload. A payload that is not a mapping has no
        field `n` in exactly the sense an absent field does, so the answer is
        the same `None` — exclusion by declaration. Calling `.get()` on it would
        raise AttributeError and take down every reader of the projection.
        """
        assert resolve_key_field({"id": "a", "payload": payload}, "n") is None

    @pytest.mark.parametrize("payload", ["raw", 7, ["a"], None])
    def test_envelope_keys_are_unaffected_by_payload_shape(self, payload):
        """ts/id are always present regardless of what the payload carries."""
        record = {"id": "a", "ts": 5.0, "payload": payload}
        assert resolve_key_field(record, "ts") == 5.0
        assert resolve_key_field(record, "id") == "a"

    def test_a_scalar_payload_record_is_excluded_from_the_projection(self):
        """The rule reaching `totalize`: non-member, and it does not raise."""
        records = [
            {"id": "a", "payload": "raw"},
            {"id": "b", "payload": {"n": 1}},
        ]
        ordered = totalize(records, ByKey("n"), get_field=resolve_key_field)
        assert [r["id"] for r in ordered] == ["b"]

    def test_payload_resolution_is_one_definition(self):
        """`resolve_payload_key` is the shared half row-shaped readers use."""
        assert resolve_payload_key({"n": 1}, "n") == 1
        assert resolve_payload_key("raw", "n") is None
        assert resolve_payload_key(None, "n") is None
