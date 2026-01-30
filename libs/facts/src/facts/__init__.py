"""facts — Fact: the observation atom.

A Fact is an intentional observation — something that happened at a
specific time. Kind is an open string; structure comes from Shape.

Example:
    from facts import Fact

    f = Fact.of("heartbeat", "alice", service="api", latency=42)
    assert f.kind == "heartbeat"
    assert f.observer == "alice"
    assert f.payload["service"] == "api"
"""

from facts.fact import Fact

__all__ = ["Fact"]
