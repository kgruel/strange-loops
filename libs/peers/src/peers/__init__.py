# peers: identity primitives
#
# Peer = name + horizon + potential (atomic identity)
# horizon = what you can see, potential = what you can do

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Peer:
    """Atomic identity: name + horizon + potential.

    A Peer is who is acting, what they can see (horizon),
    and what they can do (potential).
    """

    name: str
    horizon: frozenset[str] = frozenset()   # what you can observe
    potential: frozenset[str] = frozenset()  # what you can do/emit


def grant(
    peer: Peer,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Peer:
    """Expand peer with additional permissions (union)."""
    return replace(
        peer,
        horizon=peer.horizon | frozenset(horizon or ()),
        potential=peer.potential | frozenset(potential or ()),
    )


def restrict(
    peer: Peer,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Peer:
    """Narrow peer permissions (intersection). Used for delegation."""
    return replace(
        peer,
        horizon=peer.horizon & frozenset(horizon) if horizon is not None else peer.horizon,
        potential=peer.potential & frozenset(potential) if potential is not None else peer.potential,
    )


def delegate(
    peer: Peer,
    name: str,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Peer:
    """Create a child peer with restricted permissions.

    Delegation can only narrow, never expand. If horizon/potential are None,
    inherits parent's value for that dimension.
    """
    restricted = restrict(peer, horizon=horizon, potential=potential)
    return replace(restricted, name=name)


__all__ = ["Peer", "grant", "restrict", "delegate"]
