"""Register-parity coverage for the G3 retrofit lenses.

stream_view / ticks_view / tick_chain_view gained the ``piped`` register
signature in the spine build (G3). Their registers are visually identical
until the Surface-staging slice (G4) diverges them — these tests pin the
parity CONTRACT now so any divergence must keep both channels
information-faithful (thread:static-honest-060-spine).
"""

from loops.lenses.stream import stream_view
from loops.lenses.store import tick_chain_view
from loops.lenses.ticks import ticks_view

from .parity import assert_register_parity

STREAM_DATA = {
    "vertex": "demo",
    "facts": [
        {
            "kind": "decision",
            "ts": "2025-01-15T10:32:00",
            "observer": "kyle",
            "id": "01JQ8FAAAAAAAAAAAAAAAAAAAA",
            "payload": {"topic": "design/sqlite-persistence",
                        "message": "Chose SQLite over flat files"},
        },
        {
            "kind": "task",
            "ts": "2025-01-14T09:05:00",
            "observer": "loops-claude",
            "id": "01JQ8FBBBBBBBBBBBBBBBBBBBB",
            "payload": {"name": "implement-fold", "status": "in-progress"},
        },
    ],
    "fold_meta": {
        "decision": {"key_field": "topic"},
        "task": {"key_field": "name"},
    },
}

TICKS_DATA = {
    "vertex": "demo",
    "ticks": [
        {
            "name": "demo",
            "ts": "2025-01-15T10:32:00",
            "since": "2025-01-15T09:00:00",
            "origin": "session",
            "boundary": {"name": "session", "status": "end"},
            "kind_counts": {"decision": 3, "task": 2},
        },
        {
            "name": "demo",
            "ts": "2025-01-14T18:00:00",
            "since": "2025-01-14T12:00:00",
            "origin": "manual",
            "boundary": {},
            "kind_counts": {"decision": 1},
        },
    ],
}

CHAIN_DATA = {
    "vertex": "demo",
    "chain_mode": False,
    "chain": {},
    "windows": [
        {
            "ts": 1736935920.0,
            "index": 0,
            "boundary_trigger": "session end",
            "items": 5,
            "facts": 12,
            "added": 12,
            "updated": 0,
        },
    ],
}


class TestStreamParity:
    def test_summary(self):
        assert_register_parity(
            stream_view, STREAM_DATA,
            load_bearing=[
                "design/sqlite-persistence", "implement-fold",
                "decision", "task", "2025-01-15", "2025-01-14",
            ],
        )


class TestTicksParity:
    def test_summary(self):
        assert_register_parity(
            ticks_view, TICKS_DATA,
            load_bearing=["2025-01-15", "2025-01-14", "session end", "#0", "#1"],
        )


class TestTickChainParity:
    def test_density(self):
        assert_register_parity(
            tick_chain_view, CHAIN_DATA,
            load_bearing=["demo", "1 ticks", "session end"],
        )
