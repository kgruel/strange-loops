"""Tests for Lens — 0% coverage, 24 statements."""

from engine import Lens


class TestLensConstructors:
    def test_defaults(self):
        lens = Lens()
        assert lens.zoom == 1
        assert lens.scope is None

    def test_minimal(self):
        assert Lens.minimal().zoom == 0

    def test_summary(self):
        assert Lens.summary().zoom == 1

    def test_detail(self):
        assert Lens.detail().zoom == 2

    def test_verbose(self):
        assert Lens.verbose().zoom == 3


class TestLensMethods:
    def test_with_zoom(self):
        lens = Lens(zoom=1, scope=frozenset({"a"}))
        new = lens.with_zoom(3)
        assert new.zoom == 3
        assert new.scope == frozenset({"a"})

    def test_with_scope(self):
        lens = Lens(zoom=2)
        scoped = lens.with_scope("heartbeat", "deploy")
        assert scoped.scope == frozenset({"heartbeat", "deploy"})
        assert scoped.zoom == 2

    def test_with_scope_empty_clears(self):
        lens = Lens(scope=frozenset({"x"}))
        assert lens.with_scope().scope is None

    def test_includes_no_scope(self):
        assert Lens().includes("anything") is True

    def test_includes_in_scope(self):
        lens = Lens(scope=frozenset({"a", "b"}))
        assert lens.includes("a") is True
        assert lens.includes("c") is False

    def test_frozen(self):
        import pytest
        lens = Lens()
        with pytest.raises(AttributeError):
            lens.zoom = 5


class TestModuleLazyImport:
    def test_unknown_attribute_raises(self):
        import engine
        import pytest
        with pytest.raises(AttributeError, match="no attribute"):
            engine.NoSuchThing
