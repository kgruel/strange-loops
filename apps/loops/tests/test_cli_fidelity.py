"""Tests for cli.fidelity — fidelity_from_args pure function."""
from __future__ import annotations

import argparse

from loops.cli.fidelity import fidelity_from_args


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


class TestDepth:
    def test_default_is_summary(self):
        # No -q, no -v → depth=1 (SUMMARY)
        f = fidelity_from_args(_ns())
        assert f.depth == 1

    def test_quiet_is_minimal(self):
        f = fidelity_from_args(_ns(quiet=True))
        assert f.depth == 0

    def test_one_verbose_is_detailed(self):
        f = fidelity_from_args(_ns(verbose=1))
        assert f.depth == 2

    def test_two_verbose_is_full(self):
        f = fidelity_from_args(_ns(verbose=2))
        assert f.depth == 3

    def test_three_plus_verbose_clamps_to_full(self):
        f = fidelity_from_args(_ns(verbose=5))
        assert f.depth == 3

    def test_default_depth_override(self):
        # Explicit default when no flags present
        f = fidelity_from_args(_ns(), default_depth=2)
        assert f.depth == 2

    def test_quiet_beats_default_depth(self):
        f = fidelity_from_args(_ns(quiet=True), default_depth=3)
        assert f.depth == 0


class TestDensityBudgets:
    def test_no_budgets(self):
        f = fidelity_from_args(_ns())
        assert f.chars == 0  # 0 = unlimited
        assert f.lines == 0

    def test_max_chars(self):
        f = fidelity_from_args(_ns(max_chars=120))
        assert f.chars == 120

    def test_max_lines(self):
        f = fidelity_from_args(_ns(max_lines=50))
        assert f.lines == 50

    def test_max_chars_none_treated_as_unlimited(self):
        f = fidelity_from_args(_ns(max_chars=None))
        assert f.chars == 0


class TestVisible:
    def test_no_visible_mapping(self):
        f = fidelity_from_args(_ns())
        assert f.visible == frozenset()

    def test_truthy_flag_added(self):
        f = fidelity_from_args(_ns(facts=True), visible={"facts": "facts"})
        assert f.visible == frozenset({"facts"})

    def test_falsy_flag_excluded(self):
        f = fidelity_from_args(_ns(facts=False), visible={"facts": "facts"})
        assert f.visible == frozenset()

    def test_none_flag_excluded(self):
        f = fidelity_from_args(_ns(facts=None), visible={"facts": "facts"})
        assert f.visible == frozenset()

    def test_int_flag_positive_added(self):
        # --refs N where N > 0 means "show refs"
        f = fidelity_from_args(_ns(refs=2), visible={"refs": "refs"})
        assert f.visible == frozenset({"refs"})

    def test_int_flag_zero_excluded(self):
        # --refs 0 (default) means "don't walk refs" — not visible
        f = fidelity_from_args(_ns(refs=0), visible={"refs": "refs"})
        assert f.visible == frozenset()

    def test_multiple_tags(self):
        f = fidelity_from_args(
            _ns(facts=True, refs=1, ticks=False),
            visible={"facts": "facts", "refs": "refs", "ticks": "ticks"},
        )
        assert f.visible == frozenset({"facts", "refs"})

    def test_missing_attr_treated_as_absent(self):
        # The view declared visible={"facts": "facts"} but argparse never
        # registered --facts — getattr returns None, tag absent.
        f = fidelity_from_args(_ns(), visible={"facts": "facts"})
        assert f.visible == frozenset()


class TestFrozen:
    def test_visible_is_frozenset(self):
        f = fidelity_from_args(_ns(facts=True), visible={"facts": "facts"})
        assert isinstance(f.visible, frozenset)
