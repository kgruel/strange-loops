"""Task lenses — (data, zoom, width) -> Block."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from painted import Zoom
    from painted.core.block import Block


def task_status_view(data: dict | list[dict], zoom: "Zoom", width: int) -> "Block":
    """Render task status data as a Block.

    data is a single task state dict or a list of task state dicts.
    Zoom passed through to render functions.
    """
    from strange_loops.commands.task import render_task, render_task_list

    if isinstance(data, list):
        return render_task_list(data, zoom)
    return render_task(data, zoom)


def task_log_view(data: dict, zoom: "Zoom", width: int) -> "Block":
    """Render task log data as a Block.

    data is {"facts": [...], "ticks": [...]}.
    Zoom handled by log_block_zoom.
    """
    from strange_loops.store import log_block_zoom

    return log_block_zoom(data["facts"], data.get("ticks", []), zoom)
