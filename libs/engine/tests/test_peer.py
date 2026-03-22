"""Tests for peers primitives."""

from engine import Peer, Grant, grant, restrict, delegate, grant_of, expand_grant, restrict_grant


class TestPeer:
    def test_peer_defaults_unrestricted(self):
        """A new peer is unrestricted by default."""
        p = Peer(name="alice")
        assert p.name == "alice"
        assert p.horizon is None
        assert p.potential is None

    def test_peer_with_explicit_sets(self):
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
    def test_grant_adds_to_explicit(self):
        """Grant expands an explicitly restricted set."""
        p = Peer(name="alice", horizon=frozenset({"a"}), potential=frozenset({"w"}))
        p2 = grant(p, horizon={"b"}, potential={"x"})
        assert p2.horizon == frozenset({"a", "b"})
        assert p2.potential == frozenset({"w", "x"})
        # Original unchanged
        assert p.horizon == frozenset({"a"})
        assert p.potential == frozenset({"w"})

    def test_grant_noop_on_unrestricted(self):
        """Granting to unrestricted is a no-op — can't add to 'everything'."""
        p = Peer(name="alice")
        p2 = grant(p, horizon={"a"}, potential={"x"})
        assert p2.horizon is None
        assert p2.potential is None

    def test_grant_none_arg_preserves(self):
        """Passing None for a dimension preserves it."""
        p = Peer(name="alice", horizon=frozenset({"a"}), potential=frozenset({"x"}))
        p2 = grant(p, horizon={"b"})
        assert p2.horizon == frozenset({"a", "b"})
        assert p2.potential == frozenset({"x"})  # preserved

    def test_grant_mixed_restricted_unrestricted(self):
        """One dimension restricted, one unrestricted."""
        p = Peer(name="alice", horizon=frozenset({"a"}), potential=None)
        p2 = grant(p, horizon={"b"}, potential={"x"})
        assert p2.horizon == frozenset({"a", "b"})  # expanded
        assert p2.potential is None  # no-op


class TestRestrict:
    def test_restrict_narrows_explicit(self):
        p = Peer(name="alice", horizon=frozenset({"a", "b", "c"}))
        p2 = restrict(p, horizon={"a", "b"})
        assert p2.horizon == frozenset({"a", "b"})

    def test_restrict_narrows_unrestricted(self):
        """Restricting unrestricted gives the specific set."""
        p = Peer(name="alice")
        p2 = restrict(p, horizon={"a", "b"})
        assert p2.horizon == frozenset({"a", "b"})
        assert p2.potential is None  # untouched

    def test_restrict_none_arg_preserves(self):
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
    def test_delegate_from_explicit(self):
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

    def test_delegate_from_unrestricted(self):
        """Delegation from unrestricted parent narrows to specific set."""
        parent = Peer(name="root")
        child = delegate(parent, "worker", horizon={"logs"}, potential={"read"})
        assert child.horizon == frozenset({"logs"})
        assert child.potential == frozenset({"read"})

    def test_delegate_cannot_expand(self):
        parent = Peer(name="user", horizon=frozenset({"a"}))
        child = delegate(parent, "child", horizon={"a", "b", "c"})
        assert child.horizon == frozenset({"a"})

    def test_delegate_inherits_when_none_arg(self):
        """Partial delegation inherits unspecified dimensions."""
        parent = Peer(
            name="admin",
            horizon=frozenset({"a", "b"}),
            potential=frozenset({"x", "y"}),
        )
        child = delegate(parent, "helper", potential={"x"})
        # horizon inherited fully, potential restricted
        assert child.horizon == frozenset({"a", "b"})
        assert child.potential == frozenset({"x"})

    def test_delegate_unrestricted_inherits_unrestricted(self):
        """Child of unrestricted parent inherits unrestricted if not specified."""
        parent = Peer(name="root")
        child = delegate(parent, "clone")
        assert child.horizon is None
        assert child.potential is None


class TestGrantDataclass:
    def test_grant_defaults_unrestricted(self):
        """A new grant is unrestricted by default."""
        g = Grant()
        assert g.horizon is None
        assert g.potential is None

    def test_grant_with_explicit_sets(self):
        g = Grant(
            horizon=frozenset({"logs", "metrics"}),
            potential=frozenset({"deploy"}),
        )
        assert "logs" in g.horizon
        assert "deploy" in g.potential

    def test_grant_is_frozen(self):
        g = Grant()
        try:
            g.horizon = frozenset({"a"})
            assert False, "should raise"
        except AttributeError:
            pass


class TestGrantOf:
    def test_grant_of_extracts_policy(self):
        p = Peer(
            name="alice",
            horizon=frozenset({"a", "b"}),
            potential=frozenset({"x"}),
        )
        g = grant_of(p)
        assert g.horizon == frozenset({"a", "b"})
        assert g.potential == frozenset({"x"})

    def test_grant_of_unrestricted(self):
        p = Peer(name="root")
        g = grant_of(p)
        assert g.horizon is None
        assert g.potential is None


class TestExpandGrant:
    def test_expand_adds_to_explicit(self):
        g = Grant(horizon=frozenset({"a"}), potential=frozenset({"w"}))
        g2 = expand_grant(g, horizon={"b"}, potential={"x"})
        assert g2.horizon == frozenset({"a", "b"})
        assert g2.potential == frozenset({"w", "x"})
        # Original unchanged
        assert g.horizon == frozenset({"a"})

    def test_expand_noop_on_unrestricted(self):
        g = Grant()
        g2 = expand_grant(g, horizon={"a"}, potential={"x"})
        assert g2.horizon is None
        assert g2.potential is None


class TestRestrictGrant:
    def test_restrict_narrows_explicit(self):
        g = Grant(horizon=frozenset({"a", "b", "c"}))
        g2 = restrict_grant(g, horizon={"a", "b"})
        assert g2.horizon == frozenset({"a", "b"})

    def test_restrict_narrows_unrestricted(self):
        g = Grant()
        g2 = restrict_grant(g, horizon={"a", "b"})
        assert g2.horizon == frozenset({"a", "b"})
        assert g2.potential is None  # untouched

    def test_restrict_potential_from_unrestricted(self):
        g = Grant()
        g2 = restrict_grant(g, potential={"x", "y"})
        assert g2.potential == frozenset({"x", "y"})
        assert g2.horizon is None

    def test_restrict_potential_narrows_explicit(self):
        g = Grant(potential=frozenset({"x", "y", "z"}))
        g2 = restrict_grant(g, potential={"x", "z"})
        assert g2.potential == frozenset({"x", "z"})
