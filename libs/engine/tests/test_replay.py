"""Tests for replay: recovering vertex state from stored facts."""

import pytest
from atoms import Fact
from engine import Vertex, EventStore, replay


class TestReplay:
    """Replay reads stored facts and feeds them to vertex."""

    def test_replay_empty_store(self):
        """Empty store: no-op, returns 0."""
        store = EventStore()
        vertex = Vertex("test")
        vertex.register("count", 0, lambda s, p: s + 1)

        cursor = replay(vertex, store)

        assert cursor == 0
        assert vertex.state("count") == 0

    def test_replay_reconstructs_state(self):
        """Replay feeds facts to vertex, reconstructing fold state."""
        store = EventStore()
        store.append(Fact(kind="count", ts=1.0, payload={}, observer="test"))
        store.append(Fact(kind="count", ts=2.0, payload={}, observer="test"))
        store.append(Fact(kind="count", ts=3.0, payload={}, observer="test"))

        vertex = Vertex("test")
        vertex.register("count", 0, lambda s, p: s + 1)

        cursor = replay(vertex, store)

        assert cursor == 3
        assert vertex.state("count") == 3

    def test_replay_routes_by_kind(self):
        """Different fact kinds route to different folds."""
        store = EventStore()
        store.append(Fact(kind="a", ts=1.0, payload={"n": 10}, observer="test"))
        store.append(Fact(kind="b", ts=2.0, payload={"n": 5}, observer="test"))
        store.append(Fact(kind="a", ts=3.0, payload={"n": 20}, observer="test"))

        vertex = Vertex("test")
        vertex.register("a", 0, lambda s, p: s + p["n"])
        vertex.register("b", 0, lambda s, p: s + p["n"])

        replay(vertex, store)

        assert vertex.state("a") == 30  # 10 + 20
        assert vertex.state("b") == 5

    def test_replay_from_cursor(self):
        """Partial replay: skip facts before cursor."""
        store = EventStore()
        store.append(Fact(kind="count", ts=1.0, payload={}, observer="test"))
        store.append(Fact(kind="count", ts=2.0, payload={}, observer="test"))
        store.append(Fact(kind="count", ts=3.0, payload={}, observer="test"))

        vertex = Vertex("test")
        vertex.register("count", 0, lambda s, p: s + 1)

        # Simulate: already processed first 2 facts
        cursor = replay(vertex, store, from_cursor=2)

        assert cursor == 3
        assert vertex.state("count") == 1  # only the third fact

    def test_replay_ignores_unregistered_kinds(self):
        """Facts with unregistered kinds pass through silently."""
        store = EventStore()
        store.append(Fact(kind="known", ts=1.0, payload={}, observer="test"))
        store.append(Fact(kind="unknown", ts=2.0, payload={}, observer="test"))
        store.append(Fact(kind="known", ts=3.0, payload={}, observer="test"))

        vertex = Vertex("test")
        vertex.register("known", 0, lambda s, p: s + 1)

        cursor = replay(vertex, store)

        assert cursor == 3
        assert vertex.state("known") == 2


class TestVertexStoresFact:
    """Vertex stores full Fact objects (not tuples)."""

    def test_vertex_stores_full_fact(self):
        """Receive appends the full Fact to store."""
        store = EventStore()
        vertex = Vertex("test", store=store)
        vertex.register("ping", [], lambda s, p: s + [p])

        fact = Fact(kind="ping", ts=123.0, payload={"msg": "hello"}, observer="alice")
        vertex.receive(fact, grant=None)

        assert len(store.events) == 1
        stored = store.events[0]
        assert isinstance(stored, Fact)
        assert stored.kind == "ping"
        assert stored.ts == 123.0
        assert stored.payload["msg"] == "hello"
        assert stored.observer == "alice"

    def test_round_trip_persist_replay(self):
        """Facts stored by vertex can be replayed into fresh vertex."""
        # Session 1: receive facts, store them
        store1 = EventStore()
        v1 = Vertex("test", store=store1)
        v1.register("sum", 0, lambda s, p: s + p["n"])

        v1.receive(Fact(kind="sum", ts=1.0, payload={"n": 10}, observer="a"), grant=None)
        v1.receive(Fact(kind="sum", ts=2.0, payload={"n": 20}, observer="b"), grant=None)

        assert v1.state("sum") == 30

        # "Restart": create new vertex, replay from same store
        v2 = Vertex("test")
        v2.register("sum", 0, lambda s, p: s + p["n"])

        replay(v2, store1)

        assert v2.state("sum") == 30
