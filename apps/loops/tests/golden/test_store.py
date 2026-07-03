"""Golden tests for the store command."""
from __future__ import annotations

from unittest.mock import patch
from datetime import datetime, timedelta

import pytest
from painted import Zoom

from loops.lenses.store import store_view

from .fixtures import SAMPLE_STORE, REF_DT
from .helpers import block_to_text


def _frozen_relative_time(dt: datetime) -> str:
    """Deterministic recency: the grammar vocabulary, frozen at REF_DT + 5m."""
    age = ((REF_DT + timedelta(minutes=5)) - dt).total_seconds()
    if age < 60:
        return "now"
    if age < 3600:
        return f"{int(age / 60)}m"
    if age < 86400:
        return f"{int(age / 3600)}h"
    if age < 604800:
        return f"{int(age / 86400)}d"
    if age < 2592000:
        return f"{int(age / 604800)}w"
    return f"{dt.strftime('%b')} {dt.day}"


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_store_demo(golden, zoom):
    with patch("loops.lenses.store.recency", _frozen_relative_time):
        block = store_view(SAMPLE_STORE, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
