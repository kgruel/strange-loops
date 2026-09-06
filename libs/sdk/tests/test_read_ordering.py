"""sdk read paths under a DECLARED ordering (Cut C, Q2).

The sdk routes on the SAME defaults and the SAME refusal as the combined read.
``ordering=None`` reroutes nothing — the defaults are already the axes these
paths serve — so today's callers are byte-identical.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from atoms import Arrival, ByKey
from test_read import _aggregate_with_backdated_reassertion

from sdk import SdkValueError, read_facts


@pytest.fixture
def single_store_vertex(tmp_path: Path) -> Path:
    from sdk import emit_fact

    vertex = tmp_path / "solo.vertex"
    vertex.write_text(
        'name "solo"\nstore ".loops/data/solo.db"\n'
        'loops {\n  task {\n    fold {\n      items "collect" 100\n    }\n  }\n}\n',
        encoding="utf-8",
    )
    for i in range(4):
        emit_fact(vertex, "task", {"name": f"t{i}"}, observer="o")
    return vertex


class TestOrderingIsOptionalAndDefaultsAreTodaysBehavior:
    def test_omitting_ordering_matches_declaring_the_served_default(
        self, single_store_vertex: Path
    ) -> None:
        """Single store: the served axis is Arrival(), and declaring it is a no-op."""
        default = read_facts(single_store_vertex, limit=50, order="oldest")
        declared = read_facts(
            single_store_vertex, limit=50, order="oldest", ordering=Arrival()
        )
        assert [f["id"] for f in declared.items] == [f["id"] for f in default.items]
        assert len(default.items) == 4

    def test_aggregate_default_matches_declared_bykey_ts(self, tmp_path: Path) -> None:
        parent, _receipt_last, _ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=2
        )
        default = read_facts(parent, limit=50, order="oldest")
        declared = read_facts(parent, limit=50, order="oldest", ordering=ByKey("ts"))
        assert [f["id"] for f in declared.items] == [f["id"] for f in default.items]


class TestAggregateRefusesArrival:
    def test_arrival_on_a_multi_member_aggregate_refuses(self, tmp_path: Path) -> None:
        parent, _receipt_last, _ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=2
        )
        with pytest.raises(SdkValueError) as excinfo:
            read_facts(parent, limit=50, ordering=Arrival())

        message = str(excinfo.value)
        assert "dense per-log" in message  # the reason
        assert "ByKey" in message  # the alternative

    def test_arrival_on_a_single_member_aggregate_also_refuses(
        self, tmp_path: Path
    ) -> None:
        """read_facts keys on DECLARATION SHAPE, not member count.

        A one-member aggregate's page still comes off the (ts, id) lens here —
        unlike the fold, which member-counts — so serving a declared Arrival()
        would be a lie. It refuses instead. The divergence between the two
        surfaces predates this cut; only the refusal is new.
        """
        parent, _receipt_last, _ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=1
        )
        with pytest.raises(SdkValueError, match="dense per-log"):
            read_facts(parent, limit=50, ordering=Arrival())


    def test_arrival_refuses_on_an_aggregate_with_zero_resolvable_members(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """The refusal is DECLARATION-shaped, not availability-dependent.

        `read_facts` already keys on declaration shape rather than member count
        (see the one-member case above), so this holds without a change — the
        pin is what stops a later "resolve the members first, then validate"
        refactor from making the same declaration accepted while its members
        happen to be missing and refused once they come back.
        """
        home = tmp_path / "loops_home"
        home.mkdir()
        monkeypatch.setenv("LOOPS_HOME", str(home))
        parent = tmp_path / "combined.vertex"
        parent.write_text(
            'name "combined"\ncombine {\n    vertex "absent-a"\n    vertex "absent-b"\n}\n'
            'loops {\n  task {\n    fold {\n      items "collect" 100\n    }\n  }\n}\n',
            encoding="utf-8",
        )

        with pytest.raises(SdkValueError) as excinfo:
            read_facts(parent, limit=50, ordering=Arrival())
        assert "dense per-log" in str(excinfo.value)

        # And the default on that same empty aggregate still just reads empty.
        assert read_facts(parent, limit=50).items == []
        assert read_facts(parent, limit=50, ordering=ByKey("ts")).items == []


class TestUnsupportedOrderingsRefuseRatherThanApproximate:
    def test_bykey_on_a_single_store_page_refuses(
        self, single_store_vertex: Path
    ) -> None:
        """Ordering-aware witness pagination is not this cut — say so, don't fake it."""
        with pytest.raises(SdkValueError) as excinfo:
            read_facts(single_store_vertex, limit=50, ordering=ByKey("ts"))
        message = str(excinfo.value)
        assert "not supported on a paged read" in message
        assert "Arrival()" in message  # names what this path does serve

    def test_bykey_on_a_non_default_field_refuses_on_an_aggregate(
        self, tmp_path: Path
    ) -> None:
        parent, _receipt_last, _ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=2
        )
        with pytest.raises(SdkValueError, match="not supported on a paged read"):
            read_facts(parent, limit=50, ordering=ByKey("name"))


class TestBareStoreTargets:
    def test_a_bare_db_is_one_store_so_arrival_is_its_axis(
        self, single_store_vertex: Path
    ) -> None:
        db = single_store_vertex.parent / ".loops" / "data" / "solo.db"
        assert db.exists()
        default = read_facts(db, limit=50, order="oldest")
        declared = read_facts(db, limit=50, order="oldest", ordering=Arrival())
        assert [f["id"] for f in declared.items] == [f["id"] for f in default.items]

    def test_a_bare_db_refuses_bykey(self, single_store_vertex: Path) -> None:
        db = single_store_vertex.parent / ".loops" / "data" / "solo.db"
        with pytest.raises(SdkValueError, match="not supported on a paged read"):
            read_facts(db, limit=50, ordering=ByKey("ts"))


class TestResolveEntityRidesTheResolvedOrdering:
    """The member-count branch now names the ordering it resolved."""

    def test_one_member_rides_arrival(self, tmp_path: Path) -> None:
        from sdk import resolve_entity

        parent, receipt_last, ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=1
        )
        assert receipt_last != ts_latest
        assert resolve_entity(parent, "task", "name", "z").fact_id == receipt_last

    def test_two_members_ride_the_lens(self, tmp_path: Path) -> None:
        from sdk import resolve_entity

        parent, _receipt_last, ts_latest = _aggregate_with_backdated_reassertion(
            tmp_path, n_members=2
        )
        assert resolve_entity(parent, "task", "name", "z").fact_id == ts_latest
