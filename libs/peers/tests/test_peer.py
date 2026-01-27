"""Tests for peers primitives."""

from peers import Peer, grant, restrict, delegate


class TestPeer:
    def test_peer_defaults(self):
        p = Peer(name="alice")
        assert p.name == "alice"
        assert p.horizon == frozenset()
        assert p.potential == frozenset()

    def test_peer_with_dimensions(self):
        p = Peer(
            name="admin",
            horizon=frozenset({"logs", "metrics"}),
            potential=frozenset({"deploy"}),
        )
        assert "logs" in p.horizon
        assert "deploy" in p.potential

    def test_peer_is_frozen(self):
        p = Peer(name="alice")
        try:
            p.name = "bob"
            assert False, "should raise"
        except AttributeError:
            pass


class TestGrant:
    def test_grant_adds_permissions(self):
        p = Peer(name="alice", horizon=frozenset({"a"}))
        p2 = grant(p, horizon={"b"}, potential={"x"})
        assert p2.horizon == frozenset({"a", "b"})
        assert p2.potential == frozenset({"x"})
        # Original unchanged
        assert p.horizon == frozenset({"a"})
        assert p.potential == frozenset()

    def test_grant_none_preserves(self):
        p = Peer(name="alice", horizon=frozenset({"a"}), potential=frozenset({"x"}))
        p2 = grant(p, horizon={"b"})
        assert p2.horizon == frozenset({"a", "b"})
        assert p2.potential == frozenset({"x"})  # preserved


class TestRestrict:
    def test_restrict_narrows(self):
        p = Peer(name="alice", horizon=frozenset({"a", "b", "c"}))
        p2 = restrict(p, horizon={"a", "b"})
        assert p2.horizon == frozenset({"a", "b"})

    def test_restrict_none_preserves(self):
        p = Peer(
            name="alice",
            horizon=frozenset({"a", "b"}),
            potential=frozenset({"x", "y"}),
        )
        p2 = restrict(p, horizon={"a"})
        assert p2.horizon == frozenset({"a"})
        assert p2.potential == frozenset({"x", "y"})  # preserved

    def test_restrict_immutable(self):
        p = Peer(name="alice", horizon=frozenset({"a", "b"}))
        restrict(p, horizon={"a"})
        assert p.horizon == frozenset({"a", "b"})  # original unchanged


class TestDelegate:
    def test_delegate_creates_child(self):
        parent = Peer(
            name="admin",
            horizon=frozenset({"logs", "metrics", "secrets"}),
            potential=frozenset({"deploy", "rollback"}),
        )
        child = delegate(parent, "operator", horizon={"logs", "metrics"}, potential={"deploy"})

        assert child.name == "operator"
        assert child.horizon == frozenset({"logs", "metrics"})
        assert child.potential == frozenset({"deploy"})
        assert "secrets" not in child.horizon
        assert "rollback" not in child.potential

    def test_delegate_cannot_expand(self):
        parent = Peer(name="user", horizon=frozenset({"a"}))
        child = delegate(parent, "child", horizon={"a", "b", "c"})
        assert child.horizon == frozenset({"a"})

    def test_delegate_inherits_when_none(self):
        parent = Peer(
            name="admin",
            horizon=frozenset({"a", "b"}),
            potential=frozenset({"x", "y"}),
        )
        child = delegate(parent, "helper", potential={"x"})
        # horizon inherited fully, potential restricted
        assert child.horizon == frozenset({"a", "b"})
        assert child.potential == frozenset({"x"})
