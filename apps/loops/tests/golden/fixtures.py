"""Deterministic sample data for golden tests.

All timestamps are epoch-based for reproducibility.
"""
from __future__ import annotations

from datetime import datetime, timezone

# Fixed reference point: 2025-01-15T12:00:00 UTC
REF_TS = 1736942400.0
REF_DT = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# ── status ──────────────────────────────────────────────────────────────────
SAMPLE_STATUS = {
    "decisions": [
        {
            "topic": "Use SQLite for persistence",
            "message": "Chose SQLite over filesystem for atomic writes and query support.",
            "ts": "2025-01-15T10:00:00+00:00",
        },
        {
            "topic": "KDL for config format",
            "message": "KDL is human-friendly and supports nested structure.",
            "ts": "2025-01-14T09:30:00+00:00",
        },
    ],
    "threads": [
        {"name": "vertex-routing", "status": "active", "ts": "2025-01-15T11:00:00+00:00"},
        {"name": "tick-nesting", "status": "exploring", "ts": "2025-01-14T16:00:00+00:00"},
    ],
    "tasks": [
        {
            "name": "implement fold",
            "status": "in-progress",
            "summary": "Wire up Spec.apply to projection fold loop.",
            "ts": "2025-01-15T11:30:00+00:00",
        },
        {
            "name": "add observer field",
            "status": "done",
            "summary": "Peer dissolved — observer is now a field on Fact.",
            "ts": "2025-01-14T14:00:00+00:00",
        },
    ],
    "changes": [
        {
            "summary": "Added boundary detection to Spec",
            "files": "libs/atoms/src/atoms/spec.py",
            "ts": "2025-01-15T11:45:00+00:00",
        },
        {
            "summary": "Refactored tick emission",
            "files": "libs/engine/src/engine/temporal.py",
            "ts": "2025-01-15T10:30:00+00:00",
        },
    ],
}

# ── log ─────────────────────────────────────────────────────────────────────
SAMPLE_LOG = [
    {
        "kind": "decision",
        "ts": "2025-01-15T10:00:00+00:00",
        "payload": {
            "topic": "Use SQLite for persistence",
            "message": "Chose SQLite over filesystem for atomic writes.",
        },
        "observer": "kaygee",
    },
    {
        "kind": "task",
        "ts": "2025-01-15T09:30:00+00:00",
        "payload": {
            "name": "implement fold",
            "status": "in-progress",
            "summary": "Wire up Spec.apply.",
        },
        "observer": "kaygee",
    },
    {
        "kind": "change",
        "ts": "2025-01-14T16:00:00+00:00",
        "payload": {
            "summary": "Added boundary detection",
            "files": "libs/atoms/src/atoms/spec.py",
        },
        "observer": "kaygee",
    },
    {
        "kind": "thread",
        "ts": "2025-01-14T15:00:00+00:00",
        "payload": {"name": "vertex-routing", "status": "active"},
        "observer": "kaygee",
    },
]

# ── store ───────────────────────────────────────────────────────────────────
# freshness uses a fixed datetime so we can mock _relative_time
SAMPLE_STORE = {
    "facts": {
        "total": 42,
        "kinds": {
            "disk": {
                "count": 20,
                "latest": REF_DT,
                "sample_payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
                "recent": [
                    {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
                    {"fs": "/dev/sda2", "pct": "78%", "mount": "/data"},
                ],
            },
            "memory": {
                "count": 22,
                "latest": REF_DT,
                "sample_payload": {"used_mb": 4096, "total_mb": 16384},
                "recent": [{"used_mb": 4096, "total_mb": 16384}],
            },
        },
    },
    "ticks": {
        "total": 12,
        "names": {
            "disk": {
                "count": 8,
                "latest": REF_DT,
                "sparkline": "\u2581\u2582\u2583\u2585\u2587\u2588\u2585\u2583",
                "payload_keys": ["fs", "pct", "mount"],
                "latest_payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
            },
            "memory": {
                "count": 4,
                "latest": REF_DT,
                "sparkline": "\u2581\u2583\u2585\u2587",
                "payload_keys": ["used_mb", "total_mb"],
                "latest_payload": {"used_mb": 4096, "total_mb": 16384},
            },
        },
    },
    "freshness": REF_DT,
}

# ── start ───────────────────────────────────────────────────────────────────
SAMPLE_START = {
    "disk": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
    "memory": {"used_mb": 4096, "total_mb": 16384, "free_mb": 12288},
}

# ── compile (loop) ──────────────────────────────────────────────────────────
SAMPLE_COMPILE_LOOP = {
    "type": "loop",
    "name": "disk.loop",
    "command": "df -h",
    "kind": "disk",
    "observer": "system-monitor",
    "every": 60,
    "format": "columns",
    "parse": [
        {"op": "skip_header", "lines": 1},
        {"op": "split", "delimiter": "\\s+"},
        {"op": "pick", "fields": ["fs", "pct", "mount"]},
    ],
}

# ── compile (vertex) ────────────────────────────────────────────────────────
SAMPLE_COMPILE_VERTEX = {
    "type": "vertex",
    "name": "system-monitor",
    "store": "system.db",
    "discover": "./loops/",
    "emit": True,
    "specs": {
        "disk": {
            "state_fields": ["fs", "pct", "mount"],
            "folds": [
                {"field": "pct", "op": "replace"},
                {"field": "mount", "op": "replace"},
            ],
            "boundary": {"kind": "threshold", "field": "pct", "value": "90%"},
        },
        "memory": {
            "state_fields": ["used_mb", "total_mb"],
            "folds": [{"field": "used_mb", "op": "replace"}],
            "boundary": None,
        },
    },
    "routes": {"disk": "disk", "memory": "memory"},
}

# ── validate ────────────────────────────────────────────────────────────────
SAMPLE_VALIDATE = {
    "results": [
        {"path": "loops/disk.loop", "valid": True, "error": None},
        {"path": "loops/memory.loop", "valid": True, "error": None},
        {
            "path": "loops/broken.loop",
            "valid": False,
            "error": "Parse error: unexpected token 'foo' at line 3\nExpected 'command' or 'kind' declaration",
        },
    ],
    "checked": 3,
    "errors": 1,
}

# ── test ────────────────────────────────────────────────────────────────────
SAMPLE_TEST = {
    "results": [
        {"fs": "/dev/disk1", "pct": "27%", "mount": "/"},
        {"fs": "/dev/disk2", "pct": "65%", "mount": "/data"},
        {"fs": "/dev/disk3", "pct": "91%", "mount": "/backup"},
    ],
    "skipped": 1,
}

# ── ls (population) ────────────────────────────────────────────────────────
SAMPLE_LS = {
    "header": ["kind", "feed_url"],
    "rows": [
        {"kind": "disk", "feed_url": "file:///var/log/disk.csv"},
        {"kind": "memory", "feed_url": "file:///var/log/mem.csv"},
        {"kind": "network", "feed_url": "https://monitor.local/net"},
    ],
}

# ── run facts ───────────────────────────────────────────────────────────────
SAMPLE_FACTS = [
    {
        "kind": "disk",
        "ts": 1700000000.0,
        "payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
        "observer": "system-monitor",
        "origin": "disk.loop",
    },
    {
        "kind": "memory",
        "ts": 1700000060.0,
        "payload": {"used_mb": 4096, "total_mb": 16384},
        "observer": "system-monitor",
        "origin": "memory.loop",
    },
]

# ── run ticks ───────────────────────────────────────────────────────────────
SAMPLE_TICKS = [
    {
        "name": "disk",
        "ts": 1700000000.0,
        "payload": {"fs": "/dev/sda1", "pct": "42%", "mount": "/"},
        "origin": "system-monitor",
    },
    {
        "name": "memory",
        "ts": 1700000060.0,
        "payload": {"used_mb": 4096, "total_mb": 16384},
        "origin": "memory.loop",
    },
]
