"""Tests for commands/store.py helper functions."""

from loops.commands.store import _bucket_timestamps, _sparkline_str


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


class TestSparkline:
    def test_basic(self):
        result = _sparkline_str([0, 1, 2, 3, 4])
        assert len(result) == 5
        assert isinstance(result, str)

    def test_empty(self):
        assert _sparkline_str([]) == ""

    def test_all_zeros(self):
        result = _sparkline_str([0, 0, 0])
        assert len(result) == 3

    def test_uniform(self):
        result = _sparkline_str([5, 5, 5])
        assert len(result) == 3
