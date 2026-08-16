"""Generator for replay and witness conformance vectors.

Builds golden vectors pinning:
- Store replay total order (ts ASC, id ASC tie-breaking, sub-ms timestamp precision)
- Witness temporal prefix isolation (SPEC §9.3, genesis sentinel, head fold, append-order invariance against backdated arrivals)

Run once to generate/regenerate frozen vector files:
    uv run python spec/conformance/generate_replay.py
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atoms import (
    Avg,
    Collect,
    Count,
    Fact,
    Field,
    FoldOp,
    Latest,
    Max,
    Min,
    Spec,
    Sum,
    TopN,
    Upsert,
    Window,
)
from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader
from engine.witness import resolve_witness_position

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLAY_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "replay"
WITNESS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "witness"


def field_to_dict(f: Field) -> dict[str, Any]:
    d: dict[str, Any] = {"name": f.name, "kind": f.kind}
    if f.optional:
        d["optional"] = True
    return d


def fold_to_dict(f: FoldOp) -> dict[str, Any]:
    if isinstance(f, Latest):
        return {"op": "latest", "target": f.target}
    elif isinstance(f, Count):
        return {"op": "count", "target": f.target}
    elif isinstance(f, Sum):
        return {"op": "sum", "target": f.target, "field": f.field}
    elif isinstance(f, Collect):
        d: dict[str, Any] = {"op": "collect", "target": f.target}
        if f.max != 0:
            d["max"] = f.max
        return d
    elif isinstance(f, Upsert):
        return {"op": "upsert", "target": f.target, "key": f.key}
    elif isinstance(f, TopN):
        d = {"op": "top_n", "target": f.target, "key": f.key, "by": f.by, "n": f.n}
        if not f.desc:
            d["desc"] = False
        return d
    elif isinstance(f, Min):
        return {"op": "min", "target": f.target, "field": f.field}
    elif isinstance(f, Max):
        return {"op": "max", "target": f.target, "field": f.field}
    elif isinstance(f, Avg):
        return {"op": "avg", "target": f.target, "field": f.field}
    elif isinstance(f, Window):
        return {"op": "window", "target": f.target, "field": f.field, "size": f.size}
    else:
        raise ValueError(f"Unknown fold: {type(f)}")


def spec_to_dict(spec: Spec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": spec.name,
        "state_fields": [field_to_dict(f) for f in spec.state_fields],
        "folds": [fold_to_dict(f) for f in spec.folds],
    }
    if spec.about:
        d["about"] = spec.about
    if spec.input_fields:
        d["input_fields"] = [field_to_dict(f) for f in spec.input_fields]
    return d


def fact_to_dict(fact: Fact) -> dict[str, Any]:
    payload = dict(fact.payload) if isinstance(fact.payload, dict) else fact.to_dict()["payload"]
    return {
        "kind": fact.kind,
        "ts": fact.ts,
        "payload": payload,
        "observer": fact.observer,
        "origin": fact.origin,
    }


@dataclass(frozen=True)
class ReplayCase:
    name: str
    description: str
    spec: Spec
    facts: list[tuple[str, Fact]]


@dataclass(frozen=True)
class WitnessCase:
    name: str
    description: str
    spec: Spec
    facts: list[tuple[str, Fact]]
    cursors: dict[str, str]


# =============================================================================
# Replay Vector Definitions
# =============================================================================

REPLAY_CASES: list[ReplayCase] = [
    # 1. Replay is append ordered, not ts-then-id ordered
    ReplayCase(
        name="replay-append-order-over-ts-order",
        description="Pins decision:design/replay-receipt-order: replay order is receipt order (rowid ascending), not (ts, id); facts appended with out-of-order timestamps are replayed in the order the store received them.",
        spec=Spec(
            name="item",
            state_fields=(
                Field(name="latest_entry", kind="dict"),
                Field(name="history", kind="list"),
            ),
            folds=(
                Upsert(target="latest_entry", key="id"),
                Collect(target="history"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="item",
                    ts=300.0,
                    payload={"id": "entity_1", "val": "ts_300"},
                    observer="alice",
                ),
            ),
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="item",
                    ts=100.0,
                    payload={"id": "entity_1", "val": "ts_100"},
                    observer="alice",
                ),
            ),
            (
                "01TESTULID0000000000000003",
                Fact(
                    kind="item",
                    ts=200.0,
                    payload={"id": "entity_1", "val": "ts_200"},
                    observer="alice",
                ),
            ),
        ],
    ),
    # 2. Timestamp tie -> id ASC tie-breaking
    ReplayCase(
        name="replay-timestamp-tie-id-asc",
        description="Pins decision:design/replay-total-order: when two facts share identical timestamps, replay tie-breaks by fact ID ascending (id ASC), regardless of append order.",
        spec=Spec(
            name="record",
            state_fields=(
                Field(name="items", kind="dict"),
                Field(name="history", kind="list"),
            ),
            folds=(
                Collect(target="history"),
                Upsert(target="items", key="k"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="record",
                    ts=1000.0,
                    payload={"k": "same_key", "val": "from_higher_id"},
                    observer="kyle",
                ),
            ),
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="record",
                    ts=1000.0,
                    payload={"k": "same_key", "val": "from_lower_id"},
                    observer="kyle",
                ),
            ),
        ],
    ),
    # 3. Sub-millisecond ts distinctions survive storage
    ReplayCase(
        name="replay-sub-millisecond-timestamp-precision",
        description="Pins sub-millisecond timestamp precision: timestamps differing by microsecond deltas preserve distinct ordering through store serialization and replay.",
        spec=Spec(
            name="sensor_readings",
            state_fields=(
                Field(name="events", kind="list"),
                Field(name="last", kind="dict"),
            ),
            folds=(
                Collect(target="events"),
                Upsert(target="last", key="sensor"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="sensor_readings",
                    ts=1736942400.000500,
                    payload={"sensor": "s1", "reading": "500us"},
                    observer="sensor",
                ),
            ),
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="sensor_readings",
                    ts=1736942400.000001,
                    payload={"sensor": "s1", "reading": "1us"},
                    observer="sensor",
                ),
            ),
            (
                "01TESTULID0000000000000003",
                Fact(
                    kind="sensor_readings",
                    ts=1736942400.000100,
                    payload={"sensor": "s1", "reading": "100us"},
                    observer="sensor",
                ),
            ),
        ],
    ),
    # 4. Composite replay ordering: multiple ties and interleaved timestamps
    ReplayCase(
        name="replay-multiple-interleaved-timestamp-id-ties",
        description="Pins composite replay ordering under receipt order: a multi-row sequence combining identical timestamps, reverse-ordered IDs, and out-of-order timestamps replays strictly in append order — none of those axes perturb it.",
        spec=Spec(
            name="audit",
            state_fields=(
                Field(name="trail", kind="list"),
                Field(name="total", kind="int"),
            ),
            folds=(
                Collect(target="trail"),
                Count(target="total"),
            ),
        ),
        facts=[
            (
                "01TESTULID000000000000000Z",
                Fact(
                    kind="audit",
                    ts=200.0,
                    payload={"step": "C"},
                    observer="sys",
                ),
            ),
            (
                "01TESTULID000000000000000B",
                Fact(
                    kind="audit",
                    ts=100.0,
                    payload={"step": "B"},
                    observer="sys",
                ),
            ),
            (
                "01TESTULID000000000000000A",
                Fact(
                    kind="audit",
                    ts=100.0,
                    payload={"step": "A"},
                    observer="sys",
                ),
            ),
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="audit",
                    ts=300.0,
                    payload={"step": "D"},
                    observer="sys",
                ),
            ),
        ],
    ),
]


# =============================================================================
# Witness Vector Definitions
# =============================================================================

WITNESS_CASES: list[WitnessCase] = [
    # 5. Fold at cursor P vs P-1 differs by exactly the fact at rowid P
    WitnessCase(
        name="witness-cursor-step-difference",
        description="Pins witness prefix isolation: fold state at cursor P vs cursor P-1 differs by exactly the contribution of the fact at rowid P.",
        spec=Spec(
            name="tx",
            state_fields=(
                Field(name="balance", kind="float"),
                Field(name="count", kind="int"),
                Field(name="history", kind="list"),
            ),
            folds=(
                Sum(target="balance", field="amount"),
                Count(target="count"),
                Collect(target="history"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="tx",
                    ts=10.0,
                    payload={"amount": 100.0, "desc": "deposit"},
                    observer="bank",
                ),
            ),
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="tx",
                    ts=20.0,
                    payload={"amount": -30.0, "desc": "withdrawal"},
                    observer="bank",
                ),
            ),
            (
                "01TESTULID0000000000000003",
                Fact(
                    kind="tx",
                    ts=30.0,
                    payload={"amount": 50.0, "desc": "bonus"},
                    observer="bank",
                ),
            ),
        ],
        cursors={
            "p_minus_1": "01TESTULID0000000000000002",
            "p": "01TESTULID0000000000000003",
        },
    ),
    # 6. Cursor at genesis sentinel -> initial state exactly
    WitnessCase(
        name="witness-genesis-sentinel-initial-state",
        description="Pins witness genesis boundary: cursor at the genesis sentinel (empty string \"\") selects an empty prefix (rowid <= 0) and returns the spec's exact initial state.",
        spec=Spec(
            name="system",
            state_fields=(
                Field(name="events", kind="int"),
                Field(name="entities", kind="dict"),
                Field(name="log", kind="list"),
                Field(name="total", kind="float"),
            ),
            folds=(
                Count(target="events"),
                Upsert(target="entities", key="id"),
                Collect(target="log"),
                Sum(target="total", field="val"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="system",
                    ts=100.0,
                    payload={"id": "node1", "val": 42.0},
                    observer="sys",
                ),
            ),
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="system",
                    ts=101.0,
                    payload={"id": "node2", "val": 58.0},
                    observer="sys",
                ),
            ),
        ],
        cursors={
            "genesis": "",
        },
    ),
    # 7. Cursor at head == unwitnessed full fold
    WitnessCase(
        name="witness-cursor-head-matches-full-fold",
        description="Pins witness head cursor equivalence: fold at cursor 'head' evaluates the complete append prefix and matches the full unwitnessed store replay exactly.",
        spec=Spec(
            name="session",
            state_fields=(
                Field(name="active", kind="dict"),
                Field(name="count", kind="int"),
            ),
            folds=(
                Upsert(target="active", key="user"),
                Count(target="count"),
            ),
        ),
        facts=[
            (
                "01TESTULID0000000000000001",
                Fact(
                    kind="session",
                    ts=10.0,
                    payload={"user": "alice", "status": "online"},
                    observer="auth",
                ),
            ),
            (
                "01TESTULID0000000000000002",
                Fact(
                    kind="session",
                    ts=20.0,
                    payload={"user": "bob", "status": "online"},
                    observer="auth",
                ),
            ),
            (
                "01TESTULID0000000000000003",
                Fact(
                    kind="session",
                    ts=30.0,
                    payload={"user": "alice", "status": "offline"},
                    observer="auth",
                ),
            ),
        ],
        cursors={
            "head": "head",
        },
    ),
    # 8. Backdated fact appended AFTER cursor P excluded from fold-at-P
    WitnessCase(
        name="witness-backdated-fact-excluded-from-prior-cursor",
        description="Pins append-order witness prefix invariance: a backdated fact appended AFTER cursor P is excluded from fold-at-P, and at head it folds LAST — receipt order, so its older timestamp neither pulls it into the prefix nor demotes it at head.",
        spec=Spec(
            name="state",
            state_fields=(
                Field(name="summary", kind="dict"),
                Field(name="history", kind="list"),
            ),
            folds=(
                Upsert(target="summary", key="key"),
                Collect(target="history"),
            ),
        ),
        facts=[
            (
                "01FACT00000000000000000001",
                Fact(
                    kind="state",
                    ts=100.0,
                    payload={"key": "k1", "val": "v1"},
                    observer="kyle",
                ),
            ),
            (
                "01FACT00000000000000000002",
                Fact(
                    kind="state",
                    ts=200.0,
                    payload={"key": "k1", "val": "v2"},
                    observer="kyle",
                ),
            ),
            (
                "01FACT00000000000000000003",
                Fact(
                    kind="state",
                    ts=50.0,
                    payload={"key": "k1", "val": "backdated_v0"},
                    observer="kyle",
                ),
            ),
        ],
        cursors={
            "at_p": "01FACT00000000000000000002",
            "head": "head",
        },
    ),
    # 9. Backdated upsert folds at its receipt position, not its timestamp
    WitnessCase(
        name="witness-backdated-upsert-at-receipt-position",
        description="Pins backdated upsert replay semantics: a fact whose timestamp falls between rowid 1 and rowid 2 is excluded at cursor rowid 1, and at head folds at its own receipt position (last) rather than being re-sorted between rowids 1 and 2.",
        spec=Spec(
            name="config",
            state_fields=(
                Field(name="values", kind="dict"),
                Field(name="updates", kind="list"),
            ),
            folds=(
                Upsert(target="values", key="setting"),
                Collect(target="updates"),
            ),
        ),
        facts=[
            (
                "01FACT00000000000000000001",
                Fact(
                    kind="config",
                    ts=10.0,
                    payload={"setting": "theme", "color": "blue"},
                    observer="kyle",
                ),
            ),
            (
                "01FACT00000000000000000002",
                Fact(
                    kind="config",
                    ts=30.0,
                    payload={"setting": "theme", "color": "dark"},
                    observer="kyle",
                ),
            ),
            (
                "01FACT00000000000000000003",
                Fact(
                    kind="config",
                    ts=20.0,
                    payload={"setting": "theme", "color": "green"},
                    observer="kyle",
                ),
            ),
        ],
        cursors={
            "after_fact_1": "01FACT00000000000000000001",
            "after_fact_2": "01FACT00000000000000000002",
            "head": "head",
        },
    ),
]


def _build_and_replay_store(
    spec: Spec,
    facts: list[tuple[str, Fact]],
    at_rowid: int | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "store.db"
        store = SqliteStore(
            path=db_path,
            serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
            deserialize=Fact.from_dict,
        )
        for fid, fact in facts:
            store.append(fact, id_override=fid)
        store.close()

        with StoreReader(db_path) as reader:
            stored_facts = reader.facts_by_kind(spec.name, at_rowid=at_rowid)
            payloads = []
            for f in stored_facts:
                p = dict(f["payload"])
                p["_ts"] = f["ts"]
                p["_observer"] = f["observer"]
                p["_origin"] = f.get("origin", "")
                p["_id"] = f.get("id")
                payloads.append(p)
            state = spec.replay(payloads)
            return json.loads(json.dumps(state))


def generate_replay_vectors() -> None:
    REPLAY_DIR.mkdir(parents=True, exist_ok=True)
    for case in REPLAY_CASES:
        expected_state = _build_and_replay_store(case.spec, case.facts)

        vector = {
            "name": case.name,
            "description": case.description,
            "input": {
                "spec": spec_to_dict(case.spec),
                "facts": [[fid, fact_to_dict(f)] for fid, f in case.facts],
            },
            "expected": expected_state,
        }

        out_path = REPLAY_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


def generate_witness_vectors() -> None:
    WITNESS_DIR.mkdir(parents=True, exist_ok=True)
    for case in WITNESS_CASES:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "store.db"
            store = SqliteStore(
                path=db_path,
                serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
                deserialize=Fact.from_dict,
            )
            for fid, fact in case.facts:
                store.append(fact, id_override=fid)
            store.close()

            expected_by_cursor: dict[str, Any] = {}
            for label, cursor_addr in case.cursors.items():
                pos = resolve_witness_position(db_path, cursor_addr)
                with StoreReader(db_path) as reader:
                    stored_facts = reader.facts_by_kind(case.spec.name, at_rowid=pos.rowid)
                    payloads = []
                    for f in stored_facts:
                        p = dict(f["payload"])
                        p["_ts"] = f["ts"]
                        p["_observer"] = f["observer"]
                        p["_origin"] = f.get("origin", "")
                        p["_id"] = f.get("id")
                        payloads.append(p)
                    state = case.spec.replay(payloads)
                    expected_by_cursor[label] = json.loads(json.dumps(state))

        vector = {
            "name": case.name,
            "description": case.description,
            "input": {
                "spec": spec_to_dict(case.spec),
                "facts": [[fid, fact_to_dict(f)] for fid, f in case.facts],
                "cursors": case.cursors,
            },
            "expected": expected_by_cursor,
        }

        out_path = WITNESS_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


def generate_all() -> None:
    generate_replay_vectors()
    generate_witness_vectors()


if __name__ == "__main__":
    generate_all()
