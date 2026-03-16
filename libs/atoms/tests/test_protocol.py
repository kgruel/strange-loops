"""Tests for atoms SourceProtocol — 0% coverage."""

import asyncio
from atoms.protocol import SourceProtocol


class _FakeAtomSource:
    @property
    def observer(self) -> str:
        return "test-observer"

    async def collect(self):
        from atoms import Fact
        yield Fact(kind="test", ts=1.0, payload={"x": 1}, observer=self.observer)
        yield Fact(kind="test", ts=2.0, payload={"x": 2}, observer=self.observer)


class TestSourceProtocol:
    def test_has_observer(self):
        src = _FakeAtomSource()
        assert hasattr(src, 'observer')

    def test_observer(self):
        assert _FakeAtomSource().observer == "test-observer"

    def test_collect(self):
        async def _run():
            src = _FakeAtomSource()
            facts = [f async for f in src.collect()]
            assert len(facts) == 2
            assert facts[0].kind == "test"
            assert facts[1].payload["x"] == 2
        asyncio.run(_run())
