# peers: identity primitives
#
# Observer = just a name (string)
# Grant = horizon + potential (optional policy)
# Peer = name + horizon + potential (convenience bundle: Observer + Grant)
#
# None = unrestricted. frozenset() = explicitly empty (locked out).
# Constraints emerge through delegation, not through upfront enumeration.

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Grant:
    """Optional policy: what an observer can see/do.

    Separates permission policy from identity. Observer is just a name;
    Grant holds the constraints.

    Attributes:
        horizon: What you can see (None = unrestricted)
        potential: What you can do (None = unrestricted)
    """

    horizon: frozenset[str] | None = None
    potential: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class Peer:
    """Atomic identity: name + horizon + potential.

    A Peer is who is acting, what they can see (horizon),
    and what they can do (potential).

    None means unrestricted — the peer can see/do anything.
    An explicit frozenset constrains to those entries only.
    """

    name: str
    horizon: frozenset[str] | None = None   # None = unrestricted
    potential: frozenset[str] | None = None  # None = unrestricted


def grant(
    peer: Peer,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Peer:
    """Expand peer with additional permissions (union).

    No-op on unrestricted dimensions — can't add to 'everything'.
    """
    new_horizon = peer.horizon
    if horizon is not None and new_horizon is not None:
        new_horizon = new_horizon | frozenset(horizon)

    new_potential = peer.potential
    if potential is not None and new_potential is not None:
        new_potential = new_potential | frozenset(potential)

    return replace(peer, horizon=new_horizon, potential=new_potential)


def restrict(
    peer: Peer,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Peer:
    """Narrow peer permissions (intersection).

    Restricting an unrestricted dimension gives the specific set.
    """
    new_horizon = peer.horizon
    if horizon is not None:
        if new_horizon is None:
            new_horizon = frozenset(horizon)
        else:
            new_horizon = new_horizon & frozenset(horizon)

    new_potential = peer.potential
    if potential is not None:
        if new_potential is None:
            new_potential = frozenset(potential)
        else:
            new_potential = new_potential & frozenset(potential)

    return replace(peer, horizon=new_horizon, potential=new_potential)


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


def grant_of(peer: Peer) -> Grant:
    """Extract Grant from Peer.

    Separates the policy (horizon + potential) from the identity (name).
    """
    return Grant(horizon=peer.horizon, potential=peer.potential)


def expand_grant(
    g: Grant,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Grant:
    """Expand grant with additional permissions (union).

    No-op on unrestricted dimensions — can't add to 'everything'.
    """
    new_horizon = g.horizon
    if horizon is not None and new_horizon is not None:
        new_horizon = new_horizon | frozenset(horizon)

    new_potential = g.potential
    if potential is not None and new_potential is not None:
        new_potential = new_potential | frozenset(potential)

    return replace(g, horizon=new_horizon, potential=new_potential)


def restrict_grant(
    g: Grant,
    *,
    horizon: set[str] | None = None,
    potential: set[str] | None = None,
) -> Grant:
    """Narrow grant permissions (intersection).

    Restricting an unrestricted dimension gives the specific set.
    """
    new_horizon = g.horizon
    if horizon is not None:
        if new_horizon is None:
            new_horizon = frozenset(horizon)
        else:
            new_horizon = new_horizon & frozenset(horizon)

    new_potential = g.potential
    if potential is not None:
        if new_potential is None:
            new_potential = frozenset(potential)
        else:
            new_potential = new_potential & frozenset(potential)

    return replace(g, horizon=new_horizon, potential=new_potential)


__all__ = ["Peer", "Grant", "grant", "restrict", "delegate", "grant_of", "expand_grant", "restrict_grant"]
