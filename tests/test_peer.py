"""Tests for peers primitives."""

from peers import Peer, Scope, grant, restrict, delegate


class TestScope:
    def test_empty_scope(self):
        s = Scope()
        assert s.see == frozenset()
        assert s.do == frozenset()
        assert s.ask == frozenset()

    def test_scope_with_permissions(self):
        s = Scope(
            see=frozenset({"logs", "metrics"}),
            do=frozenset({"deploy"}),
            ask=frozenset({"approval"}),
        )
        assert "logs" in s.see
        assert "deploy" in s.do
        assert "approval" in s.ask


class TestPeer:
    def test_peer_with_default_scope(self):
        p = Peer(name="alice")
        assert p.name == "alice"
        assert p.scope == Scope()

    def test_peer_with_scope(self):
        s = Scope(see=frozenset({"*"}))
        p = Peer(name="admin", scope=s)
        assert p.name == "admin"
        assert "*" in p.scope.see


class TestGrant:
    def test_grant_adds_permissions(self):
        s = Scope(see=frozenset({"a"}))
        s2 = grant(s, see={"b"}, do={"x"})
        assert s2.see == frozenset({"a", "b"})
        assert s2.do == frozenset({"x"})
        # Original unchanged
        assert s.see == frozenset({"a"})
        assert s.do == frozenset()

    def test_grant_none_preserves(self):
        s = Scope(see=frozenset({"a"}), do=frozenset({"x"}))
        s2 = grant(s, see={"b"})
        assert s2.see == frozenset({"a", "b"})
        assert s2.do == frozenset({"x"})  # preserved


class TestRestrict:
    def test_restrict_narrows_scope(self):
        s = Scope(see=frozenset({"a", "b", "c"}))
        s2 = restrict(s, see={"a", "b"})
        assert s2.see == frozenset({"a", "b"})

    def test_restrict_none_preserves(self):
        s = Scope(see=frozenset({"a", "b"}), do=frozenset({"x", "y"}))
        s2 = restrict(s, see={"a"})
        assert s2.see == frozenset({"a"})
        assert s2.do == frozenset({"x", "y"})  # preserved


class TestDelegate:
    def test_delegate_creates_child(self):
        parent = Peer(
            name="admin",
            scope=Scope(
                see=frozenset({"logs", "metrics", "secrets"}),
                do=frozenset({"deploy", "rollback"}),
            ),
        )
        child = delegate(parent, "operator", see={"logs", "metrics"}, do={"deploy"})

        assert child.name == "operator"
        assert child.scope.see == frozenset({"logs", "metrics"})
        assert child.scope.do == frozenset({"deploy"})
        assert "secrets" not in child.scope.see
        assert "rollback" not in child.scope.do

    def test_delegate_cannot_expand(self):
        parent = Peer(name="user", scope=Scope(see=frozenset({"a"})))
        # Trying to delegate with permissions parent doesn't have
        child = delegate(parent, "child", see={"a", "b", "c"})
        # Child only gets intersection
        assert child.scope.see == frozenset({"a"})

    def test_delegate_inherits_when_none(self):
        parent = Peer(
            name="admin",
            scope=Scope(
                see=frozenset({"a", "b"}),
                do=frozenset({"x", "y"}),
            ),
        )
        child = delegate(parent, "helper", do={"x"})
        # see inherited fully, do restricted
        assert child.scope.see == frozenset({"a", "b"})
        assert child.scope.do == frozenset({"x"})
