"""Observer name matching with namespace support.

Observer names can be bare (``loops-claude``) or namespaced
(``kyle/loops-claude``).  Namespaced names encode a delegation
relationship: ``principal/agent``.

Matching rules (flat phase — no hierarchical walk):

- Exact match always succeeds.
- If one side is bare and the other namespaced, match the bare name
  against the namespaced name's leaf (agent part).
- If both sides are namespaced, require exact match.

This keeps backward compatibility: bare names work everywhere they
did before.  Namespaced names participate transparently.
"""

from __future__ import annotations


def observer_leaf(name: str) -> str:
    """Extract the leaf (agent) part of an observer name.

    ``kyle/loops-claude`` → ``loops-claude``
    ``loops-claude`` → ``loops-claude``
    """
    if "/" in name:
        return name.rsplit("/", 1)[1]
    return name


def observer_matches(a: str, b: str) -> bool:
    """Check whether two observer names refer to the same agent.

    Supports namespaced names: ``kyle/loops-claude`` matches
    ``loops-claude`` (bare declaration).  Both bare → exact match.
    Both namespaced → exact match only.
    """
    if a == b:
        return True
    a_ns = "/" in a
    b_ns = "/" in b
    if a_ns and not b_ns:
        return a.rsplit("/", 1)[1] == b
    if b_ns and not a_ns:
        return b.rsplit("/", 1)[1] == a
    # Both namespaced but different full names
    return False
