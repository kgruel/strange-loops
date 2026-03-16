"""Tests for Boundary validation — covers __post_init__ error paths."""

import pytest
from atoms.boundary import Boundary


class TestBoundaryValidation:
    def test_when_mode(self):
        b = Boundary(kind="session", mode="when")
        assert b.kind == "session"

    def test_every_mode(self):
        b = Boundary(count=5, mode="every")
        assert b.count == 5

    def test_after_mode(self):
        b = Boundary(count=10, mode="after")
        assert b.count == 10

    def test_no_kind_no_count_raises(self):
        with pytest.raises(ValueError, match="must have kind or count"):
            Boundary()

    def test_both_kind_and_count_raises(self):
        with pytest.raises(ValueError, match="cannot have both"):
            Boundary(kind="x", count=5)

    def test_when_without_kind_raises(self):
        with pytest.raises(ValueError, match="requires kind"):
            Boundary(count=5, mode="when")

    def test_after_without_count_raises(self):
        with pytest.raises(ValueError, match="requires count"):
            Boundary(kind="x", mode="after")

    def test_every_without_count_raises(self):
        with pytest.raises(ValueError, match="requires count"):
            Boundary(kind="x", mode="every")

    def test_with_match(self):
        b = Boundary(kind="session", match=(("status", "closed"),))
        assert b.match == (("status", "closed"),)

    def test_with_run(self):
        b = Boundary(kind="x", run="echo done")
        assert b.run == "echo done"
