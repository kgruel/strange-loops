"""Tests for Source and ClosableSource protocols — 0% coverage."""

import asyncio
from engine import VertexSource, ClosableSource


class _FakeSource:
    """Concrete source that yields items."""
    def __init__(self, items):
        self._items = iter(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration


class _FakeClosable(_FakeSource):
    def __init__(self, items):
        super().__init__(items)
        self.closed = False
    async def close(self):
        self.closed = True


class TestSourceProtocol:
    def test_conforms(self):
        src = _FakeSource([1, 2, 3])
        assert isinstance(src, VertexSource)

    def test_iteration(self):
        async def _run():
            src = _FakeSource([10, 20])
            results = [x async for x in src]
            assert results == [10, 20]
        asyncio.run(_run())

    def test_empty_source(self):
        async def _run():
            src = _FakeSource([])
            results = [x async for x in src]
            assert results == []
        asyncio.run(_run())


class TestClosableSource:
    def test_conforms(self):
        src = _FakeClosable([1])
        assert isinstance(src, ClosableSource)

    def test_close(self):
        async def _run():
            src = _FakeClosable([1, 2])
            results = [x async for x in src]
            assert results == [1, 2]
            await src.close()
            assert src.closed
        asyncio.run(_run())
