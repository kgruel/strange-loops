"""Golden tests for the store command."""
from __future__ import annotations

from unittest.mock import patch
from datetime import datetime, timedelta, timezone

import pytest
from painted import Zoom

from loops.lenses.store import store_view

from .fixtures import SAMPLE_STORE, REF_DT
from .helpers import block_to_text


def _frozen_relative_time(dt: datetime) -> str:
    """Deterministic _relative_time: always relative to REF_DT + 5 minutes."""
    now = REF_DT + timedelta(minutes=5)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_store_demo(golden, zoom):
    with patch("loops.lenses.store._relative_time", _frozen_relative_time):
        block = store_view(SAMPLE_STORE, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
