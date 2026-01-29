"""Tests for Surface on_start / on_stop lifecycle hooks."""

import asyncio
from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest

from cells.tui import Surface


def _make_surface(**kwargs):
    """Create a Surface with mocked terminal internals so run() works in tests."""
    surface = Surface(**kwargs)
    # Mock the writer so no terminal interaction occurs
    writer = MagicMock()
    writer.size.return_value = (80, 24)
    surface._writer = writer
    # Mock keyboard so context manager is a no-op and get_key returns None
    kb = MagicMock()
    kb.__enter__ = MagicMock(return_value=kb)
    kb.__exit__ = MagicMock(return_value=False)
    kb.get_key.return_value = None
    surface._keyboard = kb
    return surface


class TestLifecycleOnStart:
    @pytest.mark.asyncio
    async def test_on_start_called(self):
        called = []

        async def on_start():
            called.append("start")

        surface = _make_surface(on_start=on_start)
        # Quit immediately from on_start so run() exits
        original_on_start = surface._on_start

        async def start_then_quit():
            await original_on_start()
            surface.quit()

        surface._on_start = start_then_quit

        await surface.run()
        assert "start" in called

    @pytest.mark.asyncio
    async def test_on_start_called_before_loop(self):
        """on_start fires before any update/render cycle."""
        order = []

        async def on_start():
            order.append("start")

        surface = _make_surface(on_start=on_start)

        original_update = surface.update

        def tracking_update():
            order.append("update")
            original_update()

        surface.update = tracking_update

        async def start_then_quit():
            await surface._on_start.__wrapped__()
            surface.quit()

        # Simpler approach: on_start quits immediately, so update never runs
        async def on_start_quit():
            order.append("start")
            surface.quit()

        surface._on_start = on_start_quit

        await surface.run()
        assert order == ["start"]  # update never ran because we quit in on_start


class TestLifecycleOnStop:
    @pytest.mark.asyncio
    async def test_on_stop_called(self):
        called = []

        async def on_stop():
            called.append("stop")

        surface = _make_surface(on_stop=on_stop)

        # Quit immediately from first update so we exit the loop
        def quit_on_update():
            surface.quit()

        surface.update = quit_on_update

        await surface.run()
        assert "stop" in called

    @pytest.mark.asyncio
    async def test_on_stop_called_on_exception(self):
        """on_stop fires even when the loop raises an exception."""
        called = []

        async def on_stop():
            called.append("stop")

        surface = _make_surface(on_stop=on_stop)

        def raise_on_update():
            raise RuntimeError("boom")

        surface.update = raise_on_update

        with pytest.raises(RuntimeError, match="boom"):
            await surface.run()

        assert "stop" in called


class TestLifecycleOrder:
    @pytest.mark.asyncio
    async def test_start_before_stop(self):
        order = []

        async def on_start():
            order.append("start")
            # quit so the loop exits immediately
            # (surface reference captured via closure below)

        async def on_stop():
            order.append("stop")

        surface = _make_surface(on_start=on_start, on_stop=on_stop)

        # Replace on_start to also quit
        async def start_and_quit():
            order.append("start")
            surface.quit()

        surface._on_start = start_and_quit

        await surface.run()
        assert order == ["start", "stop"]


class TestLifecycleBackwardsCompat:
    @pytest.mark.asyncio
    async def test_no_hooks_works(self):
        """Surface with no lifecycle hooks still works."""
        surface = _make_surface()

        def quit_on_update():
            surface.quit()

        surface.update = quit_on_update

        await surface.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_none_hooks_works(self):
        """Explicitly passing None for hooks still works."""
        surface = _make_surface(on_start=None, on_stop=None)

        def quit_on_update():
            surface.quit()

        surface.update = quit_on_update

        await surface.run()  # Should not raise

    def test_constructor_defaults(self):
        """Default constructor has no lifecycle hooks."""
        surface = Surface()
        assert surface._on_start is None
        assert surface._on_stop is None
