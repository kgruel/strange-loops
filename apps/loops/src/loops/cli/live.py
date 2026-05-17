"""run_live — InPlaceRenderer wrapper for live-mode display.

Secondary painted-boundary module (alongside ``cli.output``). Owns the
sole runtime import of ``painted.InPlaceRenderer``.

Mirrors siftd's ``cli/data.py:1030-1070`` pattern: ``with InPlaceRenderer()``
context manager, ``renderer.render(block)`` on each tick.

Loops' live mode consumes an async generator (``Operation.stream_fn``)
rather than a sync callback. Dispatch resolves the lens callable and
passes both into ``run_live``.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

# Secondary painted boundary — InPlaceRenderer is the only painted symbol
# we use directly here. Everything else goes through cli.output.
# Importing from the concrete submodule (rather than the top-level package)
# bypasses painted's lazy ``__getattr__`` shim so Pyright can resolve it.
from painted.inplace import InPlaceRenderer

from .output import Block, Fidelity, Reporter


async def _run_live_async(
    stream_fn: Callable[[], AsyncIterator[Any]],
    render: Callable[..., Block],
    fidelity: Fidelity | None,
    reporter: Reporter,
    render_kwargs: dict[str, Any],
) -> int:
    """Animate a stream of data snapshots via InPlaceRenderer.

    Each snapshot is rendered through ``render(data, fidelity, width=…,
    **render_kwargs)``; the resulting Block replaces the prior frame
    in place.

    Exits cleanly when the stream raises StopAsyncIteration or when the
    user interrupts (KeyboardInterrupt). Returns 0 on graceful exit, 130
    on Ctrl-C (UNIX convention for SIGINT).
    """
    width = reporter.width
    try:
        with InPlaceRenderer() as r:
            async for data in stream_fn():
                block = render(data, fidelity, width=width, **render_kwargs)
                r.render(block)
    except KeyboardInterrupt:
        return 130
    except asyncio.CancelledError:
        # Tests cancel the loop via a patched asyncio.sleep; a runtime
        # cancellation reaches the same exit code.
        return 0
    return 0


def run_live(
    stream_fn: Callable[[], AsyncIterator[Any]],
    render: Callable[..., Block],
    fidelity: Fidelity | None,
    reporter: Reporter,
    **render_kwargs: Any,
) -> int:
    """Run an async stream through InPlaceRenderer until exhaustion.

    Args:
        stream_fn: nullary callable returning an async iterator. Each
            yielded value is a data snapshot to render.
        render: lens callable. Signature ``(data, fidelity, *, width,
            **kwargs) -> Block``.
        fidelity: passed to the lens; controls disclosure depth.
        reporter: used only for its ``width`` property.
        **render_kwargs: forwarded to ``render`` as keyword arguments.

    Returns:
        Process exit code (0 = clean, 130 = SIGINT).
    """
    return asyncio.run(
        _run_live_async(stream_fn, render, fidelity, reporter, render_kwargs)
    )
