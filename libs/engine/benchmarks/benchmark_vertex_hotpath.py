from __future__ import annotations

import statistics
import tempfile
import time
from pathlib import Path

from atoms import Fact
from engine import EventStore, SqliteStore, Vertex
from engine.loop import Loop


REPEATS = 5
RECEIVE_FACTS = 6000
BOUNDARY_CYCLES = 1200
REPLAY_FACTS = 2500
TOPOLOGY_FACTS = 3000


def metric(name: str, value: float) -> None:
    print(f"METRIC {name}={value:.3f}")


def make_fact(kind: str, observer: str = "bench", **payload: object) -> Fact:
    return Fact.of(kind, observer, **payload)


def build_receive_vertex() -> Vertex:
    v = Vertex("receive")
    v.register("metric", 0, lambda s, p: s + int(p["value"]))
    v.register("disk", {"count": 0, "sum": 0}, lambda s, p: {
        "count": s["count"] + 1,
        "sum": s["sum"] + int(p["value"]),
    })
    v.register("proc", {"count": 0, "sum": 0}, lambda s, p: {
        "count": s["count"] + 1,
        "sum": s["sum"] + int(p["value"]),
    })
    v.register("audit", 0, lambda s, p: s + 1)
    v.set_routes({"disk.*": "disk", "proc.*": "proc"})
    return v


def run_receive_scenario() -> float:
    v = build_receive_vertex()
    facts: list[Fact] = []
    for i in range(RECEIVE_FACTS):
        mod = i % 4
        if mod == 0:
            facts.append(make_fact("metric", value=i % 11))
        elif mod == 1:
            facts.append(make_fact("disk.read", value=i % 7))
        elif mod == 2:
            facts.append(make_fact("proc.cpu", value=i % 5))
        else:
            facts.append(make_fact("audit", value=i))

    start = time.perf_counter()
    for fact in facts:
        v.receive(fact)
    return (time.perf_counter() - start) * 1000.0


def run_boundary_scenario() -> float:
    v = Vertex("boundary")
    v.register("task", {}, lambda s, p: {**s, p["name"]: p}, boundary="task")
    v.register("reading", {"count": 0}, lambda s, p: {"count": s["count"] + 1})
    v.register_loop(
        Loop(
            name="batch",
            initial=0,
            fold=lambda s, p: s + 1,
            boundary_count=8,
            boundary_mode="every",
        )
    )
    v.register_vertex_boundary("session", match=(("status", "closed"),))

    start = time.perf_counter()
    for i in range(BOUNDARY_CYCLES):
        v.receive(make_fact("reading", value=i))
        v.receive(make_fact("batch", value=i))
        v.receive(make_fact("task", name=f"job-{i}", status="open"))
        if i % 20 == 19:
            v.receive(make_fact("session", status="closed", cycle=i))
    return (time.perf_counter() - start) * 1000.0


def sqlite_store(path: Path) -> SqliteStore:
    return SqliteStore(path=path, serialize=Fact.to_dict, deserialize=Fact.from_dict)


def run_replay_scenario() -> float:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "bench.db"
        store = sqlite_store(db)
        writer = Vertex("orchestration", store=store)
        writer.register("task", {}, lambda s, p: {**s, p["name"]: p})
        writer.register_vertex_boundary("task", match=(("status", "open"),))
        writer.register("event", 0, lambda s, p: s + 1)

        for i in range(REPLAY_FACTS):
            writer.receive(make_fact("event", value=i))
            writer.receive(make_fact("task", name=f"seed-{i}", status="assigned"))
        store.close()

        store = sqlite_store(db)
        for i in range(REPLAY_FACTS // 5):
            store.append(make_fact("task", name=f"external-{i}", status="open"))

        reader = Vertex("orchestration", store=store)
        reader.register("task", {}, lambda s, p: {**s, p["name"]: p})
        reader.register_vertex_boundary("task", match=(("status", "open"),))
        reader.register("event", 0, lambda s, p: s + 1)

        start = time.perf_counter()
        reader.replay()
        reader.evaluate_boundaries()
        elapsed = (time.perf_counter() - start) * 1000.0
        store.close()
        return elapsed


def run_topology_scenario() -> float:
    parent = Vertex("parent", store=EventStore())
    parent.register("batch", [], lambda s, p: [*s, p])
    parent.register("metric", 0, lambda s, p: s + int(p.get("value", 0)))

    child1 = Vertex("child1")
    child1.register("input", 0, lambda s, p: s + 1, boundary="flush")

    child2 = Vertex("child2")
    child2.register("metric", 0, lambda s, p: s + int(p.get("value", 0)))
    child2.set_routes({"sensor.*": "metric"})

    parent.add_child(child1)
    parent.add_child(child2)

    start = time.perf_counter()
    for i in range(TOPOLOGY_FACTS):
        parent.receive(make_fact("input", value=i))
        parent.receive(make_fact("sensor.temp", value=i % 9))
        if i % 6 == 5:
            parent.receive(make_fact("flush", cycle=i))
    return (time.perf_counter() - start) * 1000.0


def median_ms(fn) -> float:
    samples = [fn() for _ in range(REPEATS)]
    return statistics.median(samples)


def main() -> None:
    receive_ms = median_ms(run_receive_scenario)
    boundary_ms = median_ms(run_boundary_scenario)
    replay_ms = median_ms(run_replay_scenario)
    topology_ms = median_ms(run_topology_scenario)
    vertex_mixed_ms = receive_ms + boundary_ms + replay_ms + topology_ms
    total_facts = (
        RECEIVE_FACTS
        + (BOUNDARY_CYCLES * 3 + BOUNDARY_CYCLES // 20)
        + (REPLAY_FACTS * 2 + REPLAY_FACTS // 5)
        + (TOPOLOGY_FACTS * 2 + TOPOLOGY_FACTS // 6)
    )
    facts_per_sec = total_facts / (vertex_mixed_ms / 1000.0)

    metric("vertex_mixed_ms", vertex_mixed_ms)
    metric("receive_ms", receive_ms)
    metric("boundary_ms", boundary_ms)
    metric("replay_ms", replay_ms)
    metric("topology_ms", topology_ms)
    metric("facts_per_sec", facts_per_sec)


if __name__ == "__main__":
    main()
