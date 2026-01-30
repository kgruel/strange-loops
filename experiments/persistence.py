#!/usr/bin/env python3
"""Persistence experiment: demonstrate persist + recover.

Shows the minimum viable persistence pattern:
1. Create a vertex backed by a file store
2. Receive facts, watch state accumulate
3. "Restart" — create new vertex, replay from same store
4. State is recovered

Run: python experiments/persistence.py
"""

import tempfile
from pathlib import Path

from facts import Fact
from ticks import Vertex, FileStore, replay


def main():
    # Use temp file for demo (would be a real path in production)
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
        store_path = Path(f.name)

    print(f"Store: {store_path}\n")

    # --- Session 1: accumulate state ---
    print("=== Session 1: Live operation ===")

    store = FileStore(
        path=store_path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    vertex = Vertex("counter", store=store)
    vertex.register("inc", 0, lambda s, p: s + p.get("n", 1))
    vertex.register("events", [], lambda s, p: s + [p])

    # Receive some facts
    vertex.receive(Fact.of("inc", "alice", n=10), grant=None)
    vertex.receive(Fact.of("inc", "bob", n=5), grant=None)
    vertex.receive(Fact.of("events", "alice", msg="hello"), grant=None)
    vertex.receive(Fact.of("inc", "alice", n=3), grant=None)

    print(f"  inc state: {vertex.state('inc')}")
    print(f"  events state: {vertex.state('events')}")
    print(f"  facts stored: {store.total}")

    store.close()
    print("\n  [Vertex closed — simulating restart]\n")

    # --- Session 2: recover from store ---
    print("=== Session 2: Recovery ===")

    # Fresh store, loads existing facts from file
    store2 = FileStore(
        path=store_path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    print(f"  facts loaded from file: {store2.total}")

    # Fresh vertex, same fold definitions
    vertex2 = Vertex("counter")
    vertex2.register("inc", 0, lambda s, p: s + p.get("n", 1))
    vertex2.register("events", [], lambda s, p: s + [p])

    print(f"  inc state before replay: {vertex2.state('inc')}")

    # Replay stored facts
    cursor = replay(vertex2, store2)

    print(f"  inc state after replay: {vertex2.state('inc')}")
    print(f"  events state after replay: {vertex2.state('events')}")
    print(f"  cursor position: {cursor}")

    # Continue live operation
    print("\n=== Session 2: Continue live ===")
    vertex2.receive(Fact.of("inc", "charlie", n=100), grant=None)
    print(f"  inc state after new fact: {vertex2.state('inc')}")

    store2.close()

    # --- Verify file contents ---
    print(f"\n=== Store contents ({store_path}) ===")
    with open(store_path) as f:
        for i, line in enumerate(f, 1):
            print(f"  {i}: {line.rstrip()}")

    # Cleanup
    store_path.unlink()
    print("\n[Cleaned up temp file]")


if __name__ == "__main__":
    main()
