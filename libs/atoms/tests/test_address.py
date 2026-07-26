"""Unit tests for atoms.Address — the entity-reference value-object.

Two constructors, two populations: ``parse`` for self-describing refs,
``for_edge`` for declaration-qualified edge values. The distinction is
load-bearing (it is what fixes the emit/read slash-split disagreement), so
each rule is pinned independently here.
"""

import dataclasses

import pytest

from atoms import Address


class TestReadings:
    """Dual-reading for the MATCH path — a slash address is ambiguous (sol-P1)."""

    def test_colon_single_exact_reading(self):
        # Colon declares the kind — one reading, no ambiguity, no alias.
        assert Address.readings("decision:design/foo") == (Address("decision", "design/foo"),)
        assert Address.readings("thread:arc-name") == (Address("thread", "arc-name"),)

    def test_slash_yields_both_readings(self):
        # Legacy kind-qualified (primary) AND bare whole-key.
        assert Address.readings("design/foo") == (
            Address("design", "foo"),
            Address("", "design/foo"),
        )
        assert Address.readings("decision/atoms/n-on-fold-item") == (
            Address("decision", "atoms/n-on-fold-item"),
            Address("", "decision/atoms/n-on-fold-item"),
        )

    def test_bare_single_reading(self):
        assert Address.readings("arc-name") == (Address("", "arc-name"),)

    def test_empty_and_colon_empty_half_yield_no_readings(self):
        assert Address.readings("") == ()
        assert Address.readings("   ") == ()
        assert Address.readings(":key") == ()
        assert Address.readings("kind:") == ()

    def test_slash_empty_half_keeps_only_bare_reading(self):
        # No valid legacy kind-qualified reading, but the whole string is still
        # a (degenerate) bare key — harmless, matches nothing real.
        assert Address.readings("/key") == (Address("", "/key"),)
        assert Address.readings("kind/") == (Address("", "kind/"),)

    def test_parse_returns_primary_reading(self):
        for raw in ("decision:design/foo", "design/foo", "arc-name"):
            assert Address.parse(raw) == Address.readings(raw)[0]


class TestParse:
    """Self-describing refs — the corpus population (item.refs, cites)."""

    def test_colon_binds_tighter_than_key_slash(self):
        # The colon splits kind from key; slashes inside the key stay.
        assert Address.parse("decision:design/foo") == Address("decision", "design/foo")
        assert Address.parse("thread:arc-name") == Address("thread", "arc-name")

    def test_legacy_slash_splits_on_first_slash(self):
        # The 493-live-refs branch: kind is the FIRST segment, key is the rest.
        assert Address.parse("thread/arc") == Address("thread", "arc")
        assert Address.parse("decision/atoms/n-on-fold-item") == Address(
            "decision", "atoms/n-on-fold-item"
        )

    def test_bare_separatorless_key_has_empty_kind(self):
        # No separator → kind unknown; matches any kind bearing the key.
        assert Address.parse("arc-name") == Address("", "arc-name")

    def test_empty_and_empty_half_are_none(self):
        assert Address.parse("") is None
        assert Address.parse("   ") is None
        assert Address.parse(":key") is None
        assert Address.parse("kind:") is None
        assert Address.parse("/key") is None
        assert Address.parse("kind/") is None

    def test_strips_surrounding_whitespace(self):
        assert Address.parse("  decision:auth  ") == Address("decision", "auth")


class TestForEdge:
    """Declaration-qualified edge values — the declared-edge population."""

    def test_bare_value_qualified_with_target(self):
        # Declaration licenses a bare key — no separator required.
        assert Address.for_edge("acme", "person") == Address("person", "acme")

    def test_slashed_value_qualified_whole_not_split(self):
        # The defect-(b) fix: a slashed edge value is qualified WHOLE, matching
        # the read-time lift — NOT slash-split the way parse() would.
        assert Address.for_edge("design/foo", "person") == Address("person", "design/foo")

    def test_explicit_colon_overrides_declared_target(self):
        assert Address.for_edge("org:acme", "person") == Address("org", "acme")
        assert Address.for_edge("person:design/foo", "person") == Address(
            "person", "design/foo"
        )

    def test_empty_is_none(self):
        assert Address.for_edge("", "person") is None
        assert Address.for_edge("   ", "person") is None


class TestStr:
    """__str__ is the canonical rendered form — the read-lift boundary."""

    def test_kind_qualified_renders_colon(self):
        assert str(Address("person", "acme")) == "person:acme"
        assert str(Address("decision", "design/foo")) == "decision:design/foo"

    def test_bare_renders_key_only(self):
        assert str(Address("", "arc-name")) == "arc-name"

    def test_for_edge_str_is_canonical_edge_address(self):
        # Byte-identity guard for the read-lift: str(for_edge(...)) is the
        # canonical kind:key string the edge projection stores and renders.
        assert str(Address.for_edge("acme", "person")) == "person:acme"
        assert str(Address.for_edge("design/foo", "person")) == "person:design/foo"
        assert str(Address.for_edge("org:acme", "person")) == "org:acme"

    def test_parse_str_round_trip_for_colon(self):
        for raw in ("decision:design/foo", "thread:arc-name", "arc-name"):
            assert str(Address.parse(raw)) == raw

    def test_parse_canonicalizes_legacy_slash_to_colon(self):
        # Legacy slash refs render canonical on the way out (not a round-trip).
        assert str(Address.parse("decision/design/foo")) == "decision:design/foo"


class TestFrozen:
    def test_is_frozen(self):
        a = Address("person", "acme")
        with pytest.raises(dataclasses.FrozenInstanceError):
            a.kind = "org"  # type: ignore[misc]

    def test_hashable_for_counter_keys(self):
        # _compute_inbound_refs keys a Counter by Address — must be hashable.
        assert Address("decision", "x") == Address("decision", "x")
        assert hash(Address("decision", "x")) == hash(Address("decision", "x"))
        assert Address("decision", "x") != Address("thread", "x")
