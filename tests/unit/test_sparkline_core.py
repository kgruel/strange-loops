"""Tests for painted._sparkline_core: sampling, mapping, edge cases."""

from __future__ import annotations

import pytest

from painted._sparkline_core import _map_to_chars, _sample, sparkline_text

BLOCK_CHARS = ("\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588")


# =============================================================================
# sparkline_text top-level
# =============================================================================


class TestSparklineText:
    def test_zero_width_returns_empty(self):
        assert sparkline_text([1, 2, 3], 0, chars=BLOCK_CHARS, sampling="tail") == ""

    def test_negative_width_returns_empty(self):
        assert sparkline_text([1, 2], -1, chars=BLOCK_CHARS, sampling="tail") == ""

    def test_empty_values_returns_padding(self):
        result = sparkline_text([], 5, chars=BLOCK_CHARS, sampling="tail")
        assert result == "     "

    def test_empty_values_custom_pad(self):
        result = sparkline_text([], 3, chars=BLOCK_CHARS, sampling="tail", pad_char=".")
        assert result == "..."

    def test_basic_rendering(self):
        result = sparkline_text([0, 50, 100], 3, chars=BLOCK_CHARS, sampling="tail")
        assert len(result) == 3

    def test_pad_left(self):
        result = sparkline_text([1], 5, chars=BLOCK_CHARS, sampling="tail", pad_left=True)
        assert len(result) == 5
        # Left-padded: spaces on the left, data on the right.
        assert result[0] == " "
        assert result[-1] != " "

    def test_pad_right_default(self):
        result = sparkline_text([1], 5, chars=BLOCK_CHARS, sampling="tail", pad_left=False)
        assert len(result) == 5
        assert result[0] != " "
        assert result[-1] == " "

    def test_tail_sampling(self):
        values = list(range(20))
        result = sparkline_text(values, 5, chars=BLOCK_CHARS, sampling="tail")
        assert len(result) == 5

    def test_uniform_sampling(self):
        values = list(range(20))
        result = sparkline_text(values, 5, chars=BLOCK_CHARS, sampling="uniform")
        assert len(result) == 5

    def test_clamp_true(self):
        # Values outside [lo, hi] are clamped.
        result = sparkline_text(
            [-10, 50, 200], 3, chars=BLOCK_CHARS, sampling="tail", lo=0.0, hi=100.0, clamp=True
        )
        assert len(result) == 3

    def test_range_source_all(self):
        # With range_source="all", range uses all values even when only a subset is sampled.
        values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        result = sparkline_text(values, 3, chars=BLOCK_CHARS, sampling="tail", range_source="all")
        assert len(result) == 3

    def test_range_source_sampled(self):
        values = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 100]
        result = sparkline_text(
            values, 3, chars=BLOCK_CHARS, sampling="tail", range_source="sampled"
        )
        assert len(result) == 3

    def test_explicit_lo_hi(self):
        result = sparkline_text(
            [25, 50, 75], 3, chars=BLOCK_CHARS, sampling="tail", lo=0.0, hi=100.0
        )
        assert len(result) == 3


# =============================================================================
# _sample
# =============================================================================


class TestSample:
    def test_fewer_values_than_width(self):
        result = _sample([1, 2, 3], 10, "tail")
        assert result == [1, 2, 3]

    def test_exact_match(self):
        result = _sample([1, 2, 3], 3, "tail")
        assert result == [1, 2, 3]

    def test_tail_takes_last_n(self):
        result = _sample([10, 20, 30, 40, 50], 3, "tail")
        assert result == [30, 40, 50]

    def test_uniform_evenly_samples(self):
        result = _sample([0, 10, 20, 30, 40, 50, 60, 70, 80, 90], 5, "uniform")
        assert len(result) == 5
        # First element is always values[0].
        assert result[0] == 0.0

    def test_unknown_strategy_raises(self):
        with pytest.raises(ValueError, match="Unknown sampling strategy"):
            _sample([1, 2, 3], 2, "bogus")  # type: ignore[arg-type]


# =============================================================================
# _map_to_chars
# =============================================================================


class TestMapToChars:
    def test_empty_values(self):
        assert _map_to_chars([], BLOCK_CHARS, lo=0, hi=100, clamp=False) == ""

    def test_empty_chars(self):
        assert _map_to_chars([1, 2, 3], [], lo=0, hi=100, clamp=False) == ""

    def test_single_value(self):
        result = _map_to_chars([50], BLOCK_CHARS, lo=0, hi=100, clamp=False)
        assert len(result) == 1
        assert result in BLOCK_CHARS

    def test_equal_lo_hi(self):
        # When lo == hi, span becomes 1.0 (avoids div-by-zero).
        result = _map_to_chars([5, 5, 5], BLOCK_CHARS, lo=5, hi=5, clamp=False)
        assert len(result) == 3

    def test_clamp_constrains_values(self):
        result = _map_to_chars([-100, 200], BLOCK_CHARS, lo=0, hi=100, clamp=True)
        assert len(result) == 2
        # -100 clamped to 0 => lowest char, 200 clamped to 100 => highest char.
        assert result[0] == BLOCK_CHARS[0]
        assert result[1] == BLOCK_CHARS[-1]

    def test_no_clamp_allows_overflow(self):
        # Without clamp, values outside range may map to edge chars via idx clamping.
        result = _map_to_chars([-100, 200], BLOCK_CHARS, lo=0, hi=100, clamp=False)
        assert len(result) == 2
