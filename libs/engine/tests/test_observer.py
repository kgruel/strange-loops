"""Tests for observer name matching with namespace support."""

from engine.observer import observer_leaf, observer_matches


class TestObserverLeaf:
    def test_bare_name(self):
        assert observer_leaf("loops-claude") == "loops-claude"

    def test_namespaced(self):
        assert observer_leaf("kyle/loops-claude") == "loops-claude"

    def test_empty(self):
        assert observer_leaf("") == ""

    def test_multi_segment(self):
        """Multi-segment paths take the last segment."""
        assert observer_leaf("org/team/agent") == "agent"


class TestObserverMatches:
    # --- Exact match ---
    def test_exact_bare(self):
        assert observer_matches("loops-claude", "loops-claude")

    def test_exact_namespaced(self):
        assert observer_matches("kyle/loops-claude", "kyle/loops-claude")

    # --- Bare vs namespaced ---
    def test_namespaced_matches_bare_declaration(self):
        """kyle/loops-claude should match bare declaration loops-claude."""
        assert observer_matches("kyle/loops-claude", "loops-claude")

    def test_bare_matches_namespaced_declaration(self):
        """Symmetric: bare loops-claude matches namespaced kyle/loops-claude."""
        assert observer_matches("loops-claude", "kyle/loops-claude")

    # --- Non-matches ---
    def test_different_bare_names(self):
        assert not observer_matches("loops-claude", "meta-claude")

    def test_different_namespaced(self):
        """Two different namespaced names don't match even with same leaf."""
        assert not observer_matches("kyle/loops-claude", "meta/loops-claude")

    def test_different_agents_same_principal(self):
        assert not observer_matches("kyle/loops-claude", "kyle/meta-claude")

    def test_partial_name_no_match(self):
        """Substring of leaf doesn't match."""
        assert not observer_matches("claude", "loops-claude")

    # --- Edge cases ---
    def test_empty_strings(self):
        assert observer_matches("", "")

    def test_empty_vs_nonempty(self):
        assert not observer_matches("", "kyle")

    # --- Backward compatibility ---
    def test_bare_kyle(self):
        """Plain 'kyle' matches 'kyle' — the common case."""
        assert observer_matches("kyle", "kyle")

    def test_bare_agent_names(self):
        """All current bare agent names match themselves."""
        for name in ("kyle", "loops-claude", "meta-claude", "orchestrator"):
            assert observer_matches(name, name)
