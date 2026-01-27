"""Tests for capability-as-fact pattern.

Self-contained: inlines shape definition and helpers.
"""

from facts import Fact
from peers import Peer, grant, delegate
from shapes import Facet, Fold, Shape


# --- Inline shape + helpers (self-contained) ---

def _shape():
    return Shape(
        name="peer-potential",
        about="Fold capability grant/revoke facts into current potential",
        input_facets=(
            Facet(name="peer", kind="str"),
            Facet(name="capability", kind="str"),
            Facet(name="granted", kind="bool"),
        ),
        state_facets=(
            Facet(name="capabilities", kind="dict"),
            Facet(name="history", kind="list"),
        ),
        folds=(
            Fold(op="upsert", target="capabilities", props={"key": "capability"}),
            Fold(op="collect", target="history", props={"max": 100}),
        ),
    )


def _fold(shape, state, fact):
    return shape.apply(state, dict(fact.payload))


def _active(state):
    return frozenset(
        name for name, entry in state["capabilities"].items()
        if entry.get("granted")
    )


class TestCapabilityAsFact:
    def test_grant_appears_in_state(self):
        shape = _shape()
        state = shape.initial_state()

        fact = Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True)
        state = _fold(shape, state, fact)

        assert "deploy" in state["capabilities"]
        assert state["capabilities"]["deploy"]["granted"] is True

    def test_revoke_updates_state(self):
        shape = _shape()
        state = shape.initial_state()

        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=False))

        assert state["capabilities"]["deploy"]["granted"] is False

    def test_active_potential_derives_granted_only(self):
        shape = _shape()
        state = shape.initial_state()

        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="rollback", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="secrets", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="secrets", granted=False))

        active = _active(state)
        assert active == frozenset({"deploy", "rollback"})
        assert "secrets" not in active

    def test_audit_trail_preserves_history(self):
        shape = _shape()
        state = shape.initial_state()

        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=False))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True))

        assert len(state["history"]) == 3
        assert state["history"][0]["granted"] is True
        assert state["history"][1]["granted"] is False
        assert state["history"][2]["granted"] is True

    def test_delegation_narrows_derived_potential(self):
        shape = _shape()
        state = shape.initial_state()

        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True))
        state = _fold(shape, state, Fact.of("peer-potential", peer="kyle", capability="rollback", granted=True))

        kyle = Peer(name="kyle")
        kyle = grant(kyle, potential=_active(state))
        assert kyle.potential == frozenset({"deploy", "rollback"})

        agent = delegate(kyle, "kyle/deploy-agent", potential={"deploy"})
        assert agent.potential == frozenset({"deploy"})
        assert "rollback" not in agent.potential
