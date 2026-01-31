"""Alert automation: full pipeline from command to alert, looping back.

Proves the pattern: Source → Parse → Fold → Tick → Alert → back to Vertex.

Architecture:
    CommandSource (df -h) → parse pipeline → disk facts
                                               ↓
                                          vertex.receive(fact)
                                               ↓
                                          fold: Upsert by mount
                                               ↓
                                          boundary → Tick
                                               ↓
                                          inline consumer: check threshold
                                               ↓
                                          if > 90%: emit alert.disk fact
                                               ↓
                                          route back to same vertex
                                               ↓
                                          fold: Collect alerts

Key proof points:
    - Full pipeline from external command to alert
    - Alert routes back into vertex (loop closes)
    - Consumer logic is inline (no new protocol)
    - Threshold is hardcoded (90%)

Run:
    uv run python experiments/sources/alert_automation.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from data import Fact
from data import CommandSource
from data import Coerce, Pick, Rename, Skip, Split, Transform
from vertex import EventStore, Vertex


# -- Constants ---------------------------------------------------------------

THRESHOLD = 90  # Hardcoded alert threshold
STORE_PATH = Path(__file__).parent / "alert_automation.jsonl"


# -- Parse pipeline ----------------------------------------------------------

DISK_PARSE = [
    Skip(startswith="Filesystem"),  # Skip header
    Skip(contains="/System/Volumes"),  # Skip macOS system volumes
    Split(),
    Pick(0, 1, 4, 8),  # fs, size, pct, mount
    Rename({0: "fs", 1: "size", 2: "pct", 3: "mount"}),
    Transform("pct", strip="%"),
    Coerce({"pct": int}),
]


# -- Folds -------------------------------------------------------------------

def disk_fold(state: dict, payload: dict) -> dict:
    """Upsert disk state by mount point."""
    disks = dict(state.get("disks", {}))
    mount = payload.get("mount", "unknown")
    disks[mount] = {
        "fs": payload.get("fs"),
        "size": payload.get("size"),
        "pct": payload.get("pct"),
    }
    return {"disks": disks, "count": state.get("count", 0) + 1}


def alert_fold(state: dict, payload: dict) -> dict:
    """Collect alerts."""
    alerts = list(state.get("alerts", []))
    alerts.append({
        "mount": payload.get("mount"),
        "pct": payload.get("pct"),
        "threshold": payload.get("threshold"),
    })
    return {"alerts": alerts}


# -- Store setup -------------------------------------------------------------

def build_store() -> EventStore[Fact]:
    """Build JSONL-backed store for facts."""
    return EventStore(
        path=STORE_PATH,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )


# -- Vertex setup ------------------------------------------------------------

def build_vertex(store: EventStore[Fact]) -> Vertex:
    """Build vertex with disk and alert folds, backed by store."""
    v = Vertex("disk-monitor", store=store)

    # Disk fold: upsert by mount, boundary on df.complete
    v.register(
        "disk",
        {"disks": {}, "count": 0},
        disk_fold,
        boundary="df.complete",
        reset=False,  # Carry state across runs
    )

    # Alert fold: collect alerts
    v.register(
        "alert.disk",
        {"alerts": []},
        alert_fold,
    )

    return v


# -- Main loop ---------------------------------------------------------------

def make_disk_source() -> CommandSource:
    """Create a one-shot disk source."""
    return CommandSource(
        command="df -h",
        kind="disk",
        observer="df-source",
        interval=None,  # Run once
        parse=DISK_PARSE,
    )


async def main():
    """Run alert automation experiment."""
    # Build store first — loads existing facts if any
    store = build_store()
    loaded_count = store.total

    vertex = build_vertex(store)

    print("Alert automation experiment")
    print("=" * 50)
    print(f"Threshold: {THRESHOLD}%")
    print(f"Store: {STORE_PATH}")
    print(f"  Loaded {loaded_count} facts from previous runs")
    print("Flow: df -h → parse → fold → tick → check → alert → vertex")
    print("=" * 50)
    print()

    tick_count = 0

    # Run 2 collection cycles
    for run_count in range(2):
        print(f"[Run {run_count + 1}] Collecting disk data...")

        # Fresh source each run (interval=None means one-shot)
        disk_source = make_disk_source()

        # Collect all disk facts from one df run
        async for fact in disk_source.stream():
            vertex.receive(fact)

        # Emit boundary to trigger tick
        boundary_fact = Fact.of("df.complete", "disk-monitor")
        tick = vertex.receive(boundary_fact)

        if tick is not None:
            tick_count += 1
            print(f"  Tick #{tick_count}: {tick.payload}")

            # Inline consumer: check threshold
            disks = tick.payload.get("disks", {})
            for mount, info in disks.items():
                pct = info.get("pct", 0)
                if pct > THRESHOLD:
                    print(f"  ALERT: {mount} at {pct}% (threshold: {THRESHOLD}%)")

                    # Emit alert fact back to vertex
                    alert_fact = Fact.of(
                        "alert.disk",
                        "disk-monitor",
                        mount=mount,
                        pct=pct,
                        threshold=THRESHOLD,
                    )
                    vertex.receive(alert_fact)
                    print(f"  → Routed alert.disk back to vertex")

        # Show current state
        disk_state = vertex.state("disk")
        alert_state = vertex.state("alert.disk")
        print(f"  Disk state: {len(disk_state.get('disks', {}))} mounts")
        print(f"  Alert state: {len(alert_state.get('alerts', []))} alerts")
        print()

        if run_count < 1:
            await asyncio.sleep(1.0)

    # Final summary
    print("=" * 50)
    print("Final state:")
    disk_state = vertex.state("disk")
    alert_state = vertex.state("alert.disk")

    print(f"\nDisks ({len(disk_state.get('disks', {}))} mounts):")
    for mount, info in disk_state.get("disks", {}).items():
        marker = " <-- ALERT" if info.get("pct", 0) > THRESHOLD else ""
        print(f"  {mount}: {info['pct']}%{marker}")

    print(f"\nAlerts ({len(alert_state.get('alerts', []))}):")
    for alert in alert_state.get("alerts", []):
        print(f"  {alert['mount']} at {alert['pct']}% (threshold: {alert['threshold']}%)")

    # Store stats
    new_facts = store.total - loaded_count
    print(f"\nStore stats:")
    print(f"  Path: {STORE_PATH}")
    print(f"  Previously loaded: {loaded_count}")
    print(f"  New this session: {new_facts}")
    print(f"  Total persisted: {store.total}")

    store.close()

    print("\n" + "=" * 50)
    print("Proved:")
    print("  - Source → Parse → Fold → Tick → inline check")
    print("  - Alert emitted as Fact, routed back to same vertex")
    print("  - No new protocol, just Facts and Folds")
    print("  - Facts are durable (JSONL), not just ephemeral fold state")


if __name__ == "__main__":
    asyncio.run(main())
