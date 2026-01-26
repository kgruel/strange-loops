# peers: scoped identity primitives
#
# Peer = name + scope (atomic identity)
# Scope = see + do + ask (boundaries that cascade)

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Scope:
    """Boundaries: what a peer can see, do, and ask.

    Scope cascades through the ecosystem:
    - What facts you can emit/see
    - What ticks you can read/write
    - What forms you can use
    - What cells you can render
    """

    see: frozenset[str] = frozenset()  # what you can observe
    do: frozenset[str] = frozenset()  # what you can modify
    ask: frozenset[str] = frozenset()  # what you can request


@dataclass(frozen=True, slots=True)
class Peer:
    """Atomic identity: name + scope.

    A Peer is who is acting and what they can see/do/ask.
    """

    name: str
    scope: Scope = Scope()


# Scope operations (pure functions, following cells patterns)


def grant(scope: Scope, *, see: set[str] | None = None, do: set[str] | None = None, ask: set[str] | None = None) -> Scope:
    """Expand scope with additional permissions."""
    return replace(
        scope,
        see=scope.see | frozenset(see or ()),
        do=scope.do | frozenset(do or ()),
        ask=scope.ask | frozenset(ask or ()),
    )


def restrict(scope: Scope, *, see: set[str] | None = None, do: set[str] | None = None, ask: set[str] | None = None) -> Scope:
    """Narrow scope (intersection). Used for delegation."""
    return replace(
        scope,
        see=scope.see & frozenset(see) if see is not None else scope.see,
        do=scope.do & frozenset(do) if do is not None else scope.do,
        ask=scope.ask & frozenset(ask) if ask is not None else scope.ask,
    )


def delegate(peer: Peer, name: str, *, see: set[str] | None = None, do: set[str] | None = None, ask: set[str] | None = None) -> Peer:
    """Create a child peer with restricted scope.

    Delegation can only narrow, never expand. If see/do/ask are None,
    inherits parent's scope for that dimension.
    """
    return Peer(
        name=name,
        scope=restrict(peer.scope, see=see, do=do, ask=ask),
    )


__all__ = ["Peer", "Scope", "grant", "restrict", "delegate"]
