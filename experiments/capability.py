"""Capability-as-Fact: event-sourced potential for peers.

Demonstrates folding grant/revoke facts through a Shape to derive
a peer's current potential. No async, no Surface — pure fold mechanics.

Run: uv run python experiments/capability.py
"""

from facts import Fact
from peers import Peer, grant, delegate
from specs import Facet, Fold, Shape


# --- Shape: peer-potential ---
# Folds capability grant/revoke facts into a capabilities dict + audit history.

PEER_POTENTIAL_SHAPE = Shape(
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


def _make_fold(shape: Shape):
    """Bridge: extract Fact payload and delegate to shape.apply.

    Projection receives Facts. Shape.apply receives dicts.
    This is the extraction point — the only place that knows about both.
    """
    def fold(state: dict, fact: Fact) -> dict:
        return shape.apply(state, dict(fact.payload))
    return fold


def active_potential(state: dict) -> frozenset[str]:
    """Derive the set of currently granted capabilities from folded state."""
    return frozenset(
        name
        for name, entry in state["capabilities"].items()
        if entry.get("granted")
    )


def apply_potential(peer: Peer, state: dict) -> Peer:
    """Attach derived potential to a peer via grant()."""
    return grant(peer, potential=active_potential(state))


def main():
    shape = PEER_POTENTIAL_SHAPE
    fold = _make_fold(shape)
    state = shape.initial_state()

    # Start with a bare peer
    kyle = Peer(name="kyle")
    print(f"Initial: {kyle}")
    print(f"Initial state: {state}")
    print()

    # Emit grant facts
    facts = [
        Fact.of("peer-potential", peer="kyle", capability="deploy", granted=True),
        Fact.of("peer-potential", peer="kyle", capability="rollback", granted=True),
        Fact.of("peer-potential", peer="kyle", capability="secrets", granted=True),
    ]

    for f in facts:
        state = fold(state, f)
        print(f"After grant '{f.payload['capability']}': {sorted(active_potential(state))}")

    print()

    # Revoke secrets
    revoke = Fact.of("peer-potential", peer="kyle", capability="secrets", granted=False)
    state = fold(state, revoke)
    print(f"After revoke 'secrets': {sorted(active_potential(state))}")
    print()

    # Derive potential and apply to peer
    derived = active_potential(state)
    kyle_with_potential = apply_potential(kyle, state)
    print(f"Derived potential: {sorted(derived)}")
    print(f"Kyle with potential: {kyle_with_potential}")
    print()

    # Delegate with narrowed potential
    agent = delegate(kyle_with_potential, "kyle/deploy-agent", potential={"deploy"})
    print(f"Delegated agent: {agent}")
    print()

    # Audit trail
    print(f"Audit trail ({len(state['history'])} entries):")
    for entry in state["history"]:
        action = "grant" if entry["granted"] else "revoke"
        print(f"  {action} {entry['capability']} for {entry['peer']}")

    # Assertions
    assert derived == frozenset({"deploy", "rollback"})
    assert kyle_with_potential.potential == frozenset({"deploy", "rollback"})
    assert agent.potential == frozenset({"deploy"})
    assert len(state["history"]) == 4
    assert state["capabilities"]["secrets"]["granted"] is False

    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
