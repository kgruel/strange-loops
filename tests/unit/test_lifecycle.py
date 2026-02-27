"""Tests for Surface on_start / on_stop lifecycle hooks."""

import pytest

from painted.tui import Surface, TestSurface


class _QueueKeyboard:
    def __init__(self, inputs=()):
        self._inputs = list(inputs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def get_input(self):
        if not self._inputs:
            return None
        return self._inputs.pop(0)


def _make_surface(**kwargs) -> Surface:
    surface = Surface(fps_cap=1000, **kwargs)
    harness = TestSurface(surface, width=80, height=24, input_queue=[])
    # Surface.run() calls writer.size() to allocate buffers; keep it deterministic.
    surface._writer.size = lambda: (harness.width, harness.height)  # type: ignore[method-assign]
    surface._keyboard = _QueueKeyboard()
    return surface


class TestLifecycleOnStart:
    @pytest.mark.asyncio
    async def test_on_start_called(self):
        called = []

        async def on_start():
            called.append("start")

        surface = _make_surface(on_start=on_start)

        original_on_start = surface._on_start

        async def start_then_quit():
            assert original_on_start is not None
            await original_on_start()
            surface.quit()

        surface._on_start = start_then_quit  # type: ignore[assignment]

        await surface.run()
        assert "start" in called

    @pytest.mark.asyncio
    async def test_on_start_called_before_loop(self):
        """on_start fires before any update/render cycle."""
        order = []

        async def on_start():
            order.append("start")
            surface.quit()

        surface = _make_surface(on_start=on_start)

        original_update = surface.update

        def tracking_update():
            order.append("update")
            original_update()

        surface.update = tracking_update  # type: ignore[assignment]

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

        surface.update = quit_on_update  # type: ignore[assignment]

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

        surface.update = raise_on_update  # type: ignore[assignment]

        with pytest.raises(RuntimeError, match="boom"):
            await surface.run()

        assert "stop" in called


class TestLifecycleOrder:
    @pytest.mark.asyncio
    async def test_start_before_stop(self):
        order = []
        surface_holder: dict[str, Surface] = {}

        async def on_start():
            order.append("start")
            surface_holder["surface"].quit()

        async def on_stop():
            order.append("stop")

        surface = _make_surface(on_start=on_start, on_stop=on_stop)
        surface_holder["surface"] = surface

        await surface.run()
        assert order == ["start", "stop"]


class TestLifecycleBackwardsCompat:
    @pytest.mark.asyncio
    async def test_no_hooks_works(self):
        """Surface with no lifecycle hooks still works."""
        surface = _make_surface()

        def quit_on_update():
            surface.quit()

        surface.update = quit_on_update  # type: ignore[assignment]

        await surface.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_none_hooks_works(self):
        """Explicitly passing None for hooks still works."""
        surface = _make_surface(on_start=None, on_stop=None)

        def quit_on_update():
            surface.quit()

        surface.update = quit_on_update  # type: ignore[assignment]

        await surface.run()  # Should not raise

    def test_constructor_defaults(self):
        """Default constructor has no lifecycle hooks."""
        surface = Surface()
        assert surface._on_start is None
        assert surface._on_stop is None
