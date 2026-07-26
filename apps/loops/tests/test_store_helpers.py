"""Tests for commands/store.py helper functions."""

from loops.commands.store import _bucket_timestamps
from loops.lenses._statview import spark


class TestBucketTimestamps:
    def test_basic(self):
        ts = [10.0, 20.0, 30.0, 40.0, 50.0]
        buckets = _bucket_timestamps(ts, width=5)
        assert len(buckets) == 5
        assert sum(buckets) == len(ts)

    def test_empty(self):
        assert _bucket_timestamps([], width=10) == []

    def test_zero_width(self):
        assert _bucket_timestamps([1.0], width=0) == []

    def test_single_timestamp(self):
        """All at same time → spike in middle."""
        buckets = _bucket_timestamps([5.0, 5.0, 5.0], width=5)
        assert len(buckets) == 5
        assert max(buckets) == 3.0

    def test_two_timestamps(self):
        buckets = _bucket_timestamps([0.0, 100.0], width=10)
        assert len(buckets) == 10
        assert sum(buckets) == 2


class TestBucketedSpark:
    """The store rollup's sparkline is ``_bucket_timestamps`` composed with the
    canonical ``_statview.spark`` — store.py holds no glyph ladder of its own
    (the deleted ``_sparkline_str`` fork). ``spark``'s own contract is asserted
    in ``TestSpark`` below; these cover the seam, including the float bucket
    counts spark has to accept from this caller."""

    def test_bucketed_counts_render(self):
        buckets = _bucket_timestamps([10.0, 20.0, 30.0, 40.0, 50.0], width=5)
        result = spark(buckets)
        assert len(result) == 5

    def test_empty_bucketing_renders_empty(self):
        assert spark(_bucket_timestamps([], width=8)) == ""


class TestSpark:
    def test_empty(self):
        assert spark([]) == ""

    def test_all_zero_reads_as_dim_baseline(self):
        assert spark([0, 0, 0]) == "···"

    def test_uniform_is_flat_at_max(self):
        assert spark([5, 5, 5]) == "███"

    def test_ascending_ends_at_max(self):
        result = spark([0, 1, 2, 3])
        assert len(result) == 4
        assert result[0] == "·"      # zero → visible gap, not blank
        assert result[-1] == "█"

    def test_small_nonzero_bucket_is_never_blank(self):
        """The property that made spark canonical: a bucket with real activity
        renders as a glyph however small its share of the max."""
        result = spark([1, 100])
        assert result[0] not in (" ", "·")
        assert " " not in result

    def test_length_matches_input(self):
        for n in (1, 5, 10, 20):
            assert len(spark(list(range(n)))) == n
