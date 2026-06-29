"""Tests for cli.views.fold._colon_address_suggestion — colon/slash address.

Guards friction:read-address-separator-colon-vs-slash: the positional address
is kind/key (slash). Reaching for the ref idiom kind:key (colon) used to be
silently ignored, widening to the whole fold. It must now be caught.
"""

from __future__ import annotations

from loops.cli.views.fold import _colon_address_suggestion


class TestColonAddressSuggestion:
    def test_no_slash_colon_is_caught(self):
        assert (
            _colon_address_suggestion("thread:human-umwelt", None, None)
            == "thread/human-umwelt"
        )

    def test_colon_before_slash_in_key_is_caught(self):
        # kind:key where the key itself is namespaced — colon is the (wrong)
        # kind/key separator, so only the first colon is rewritten.
        assert (
            _colon_address_suggestion("decision:design/foo", None, None)
            == "decision/design/foo"
        )

    def test_valid_slash_address_passes(self):
        assert _colon_address_suggestion("thread/human-umwelt", None, None) is None

    def test_slash_only_address_passes(self):
        assert _colon_address_suggestion("design/foo", None, None) is None

    def test_explicit_kind_flag_suppresses(self):
        # --kind/--key win; the entity is not consulted, so don't second-guess.
        assert _colon_address_suggestion("thread:foo", "decision", None) is None
        assert _colon_address_suggestion("thread:foo", None, "k") is None

    def test_none_entity_passes(self):
        assert _colon_address_suggestion(None, None, None) is None
