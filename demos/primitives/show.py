#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["painted"]
# ///
"""show() — zero-config display.

show(data) auto-dispatches by data shape: scalars print directly,
dicts and lists render through shape_lens, Blocks pass through.
Format auto-detects from TTY (styled) vs pipe (JSON).

This is the top of the ladder — everything below it done for you.

Run: uv run demos/primitives/show.py
"""

from painted import show

# --- Scalars: print directly ---

show("deploy complete")
show(42)
show(True)
show()

# --- Dict: key-value rendering ---

show({"host": "prod-1", "status": "healthy", "uptime": "14d 3h", "cpu": 0.45})
show()

# --- List: item rendering ---

show(["api", "worker", "scheduler", "cache"])
show()

# --- Nested: tree rendering ---

show({
    "cluster": {
        "prod-1": {"status": "healthy", "cpu": 0.45},
        "prod-2": {"status": "degraded", "cpu": 0.91},
    },
    "version": "2.4.1",
})
show()

# --- Numeric: chart rendering ---

show([3, 7, 2, 9, 5, 8, 1, 6, 4, 10, 3, 7])
