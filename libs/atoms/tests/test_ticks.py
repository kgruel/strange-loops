"""Tests for TickWindow — the typed weighted-fact-at-window shape."""

import pytest

from atoms import TickWindow


class TestTickWindowConstruction:
    def test_minimal(self):
        tw = TickWindow(index=0, name="project", ts=1000.0)
        assert tw.index == 0
        assert tw.name == "project"
        assert tw.ts == 1000.0
        assert tw.since is None
        assert tw.duration_secs is None

    def test_full(self):
        tw = TickWindow(
            index=2,
            name="project",
            ts=2000.0,
            since=1000.0,
            duration_secs=1000.0,
            observer="kyle",
            boundary_trigger="kyle closed",
            total_items=15,
            total_facts=42,
            kind_summary={"decision": 10, "thread": 5},
            kind_compression={"decision": 1.0, "thread": 6.4},
            ref_count=3,
            delta_added=2,
            delta_updated=3,
            added_keys={"decision": ("auth", "storage")},
            updated_keys={"thread": ("loop-as-primitive", "visibility", "wrap-up")},
        )
        assert tw.index == 2
        assert tw.observer == "kyle"
        assert tw.boundary_trigger == "kyle closed"
        assert tw.total_items == 15
        assert tw.total_facts == 42
        assert tw.kind_summary["decision"] == 10
        assert tw.kind_compression["thread"] == 6.4
        assert tw.ref_count == 3
        assert tw.delta_added == 2
        assert tw.delta_updated == 3
        assert tw.added_keys["decision"] == ("auth", "storage")
        assert tw.updated_keys["thread"] == ("loop-as-primitive", "visibility", "wrap-up")

    def test_defaults(self):
        tw = TickWindow(index=0, name="project", ts=1000.0)
        assert tw.observer == ""
        assert tw.boundary_trigger == ""
        assert tw.total_items == 0
        assert tw.total_facts == 0
        assert tw.kind_summary == {}
        assert tw.kind_compression == {}
        assert tw.ref_count == 0
        assert tw.delta_added == 0
        assert tw.delta_updated == 0
        assert tw.added_keys == {}
        assert tw.updated_keys == {}


class TestTickWindowImmutability:
    def test_frozen_reassign_fails(self):
        tw = TickWindow(index=0, name="project", ts=1000.0)
        with pytest.raises(AttributeError):
            tw.total_items = 99  # type: ignore[misc]

    def test_dict_values_mutable(self):
        """Following FoldState convention: dataclass is frozen, dict values
        are not deeply immutable. Primitives are ephemeral — computed on
        demand, not persisted. Freezing reassignment is sufficient."""
        tw = TickWindow(
            index=0,
            name="project",
            ts=1000.0,
            kind_summary={"decision": 5},
        )
        tw.kind_summary["thread"] = 3
        assert tw.kind_summary["thread"] == 3

    def test_independent_default_dicts(self):
        """Each instance gets its own dict (no shared default mutable state)."""
        a = TickWindow(index=0, name="a", ts=1.0)
        b = TickWindow(index=1, name="b", ts=2.0)
        a.kind_summary["x"] = 1
        assert "x" not in b.kind_summary
