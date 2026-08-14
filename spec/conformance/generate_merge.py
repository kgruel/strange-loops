"""Generator for merge conformance vectors.

Builds golden vectors pinning:
- Disjoint merge append order
- Overlap primary-key deduplication
- Deduplication position authority (target row position wins)
- Divergent collision behavior (target survives, source silently dropped; friction:merge-divergent-collision-invisible)
- Witness prefix invariance under merge (SPEC §9.3)
- Boundary edge cases: empty source, empty target, self-merge, both empty
- Post-merge rowid sequence vs (ts, id) replay total order

Run once to generate/regenerate frozen vector files:
    uv run python spec/conformance/generate_merge.py
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
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
from store.merge import merge_store

REPO_ROOT = Path(__file__).resolve().parents[2]
MERGE_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "merge"


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
class MergeCase:
    name: str
    description: str
    target_facts: list[tuple[str, Fact]]
    source_facts: list[tuple[str, Fact]] = field(default_factory=list)
    self_merge: bool = False
    spec: Spec | None = None
    cursors: dict[str, str] | None = None


MERGE_CASES: list[MergeCase] = [
    # 1. Disjoint merge: target gains source rows appended after its own
    MergeCase(
        name="merge-disjoint-append-order",
        description="Pins disjoint store merge: target gains source rows appended after its existing rows in source (ts, id) order; expected pins the complete post-merge rowid sequence.",
        target_facts=[
            (
                "01TARGET000000000000000001",
                Fact(
                    kind="event",
                    ts=100.0,
                    payload={"k": "t1"},
                    observer="alice",
                ),
            ),
            (
                "01TARGET000000000000000002",
                Fact(
                    kind="event",
                    ts=200.0,
                    payload={"k": "t2"},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[
            (
                "01SOURCE000000000000000001",
                Fact(
                    kind="event",
                    ts=150.0,
                    payload={"k": "s1"},
                    observer="bob",
                ),
            ),
            (
                "01SOURCE000000000000000002",
                Fact(
                    kind="event",
                    ts=250.0,
                    payload={"k": "s2"},
                    observer="bob",
                ),
            ),
        ],
    ),
    # 2. Overlap dedup: shared ids skipped
    MergeCase(
        name="merge-overlap-dedup",
        description="Pins merge primary-key deduplication: shared fact IDs between target and source are skipped via INSERT OR IGNORE, preserving target row positions and updating MergeResult counters.",
        target_facts=[
            (
                "01SHARED000000000000000001",
                Fact(
                    kind="metric",
                    ts=10.0,
                    payload={"m": "cpu", "v": 10},
                    observer="alice",
                ),
            ),
            (
                "01SHARED000000000000000002",
                Fact(
                    kind="metric",
                    ts=20.0,
                    payload={"m": "mem", "v": 20},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[
            (
                "01SHARED000000000000000002",
                Fact(
                    kind="metric",
                    ts=20.0,
                    payload={"m": "mem", "v": 20},
                    observer="alice",
                ),
            ),
            (
                "01SOURCE000000000000000003",
                Fact(
                    kind="metric",
                    ts=30.0,
                    payload={"m": "disk", "v": 30},
                    observer="bob",
                ),
            ),
        ],
    ),
    # 3. Identical-id, identical-content in both stores at different rowids
    MergeCase(
        name="merge-identical-id-different-rowids-target-position-wins",
        description="Pins merge deduplication position authority: when an identical fact exists at different rowid positions in target and source, target's receipt rowid position wins and the source instance is skipped.",
        target_facts=[
            (
                "01TARGET000000000000000001",
                Fact(
                    kind="log",
                    ts=100.0,
                    payload={"msg": "t_first"},
                    observer="alice",
                ),
            ),
            (
                "01SHARED00000000000000000X",
                Fact(
                    kind="log",
                    ts=200.0,
                    payload={"msg": "shared_mid"},
                    observer="alice",
                ),
            ),
            (
                "01TARGET000000000000000002",
                Fact(
                    kind="log",
                    ts=300.0,
                    payload={"msg": "t_last"},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[
            (
                "01SHARED00000000000000000X",
                Fact(
                    kind="log",
                    ts=200.0,
                    payload={"msg": "shared_mid"},
                    observer="alice",
                ),
            ),
            (
                "01SOURCE000000000000000001",
                Fact(
                    kind="log",
                    ts=400.0,
                    payload={"msg": "s_new"},
                    observer="bob",
                ),
            ),
        ],
    ),
    # 4. Divergent-collision (same id, DIFFERENT content)
    MergeCase(
        name="merge-divergent-collision-target-wins",
        description="Pins decision:friction:merge-divergent-collision-invisible: on primary-key ID collision with divergent payload content, target's version survives, source's version is silently dropped, and MergeResult counts it as skipped; this vector documents CURRENT behavior and will be edited deliberately when facts_divergent lands.",
        target_facts=[
            (
                "01COLLISION0000000000000001",
                Fact(
                    kind="config",
                    ts=100.0,
                    payload={"setting": "mode", "val": "target_active"},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[
            (
                "01COLLISION0000000000000001",
                Fact(
                    kind="config",
                    ts=100.0,
                    payload={"setting": "mode", "val": "source_divergent_override"},
                    observer="bob",
                ),
            ),
        ],
    ),
    # 5. Merge then witness: backdated source facts do not change fold-at-P
    MergeCase(
        name="merge-witness-prefix-invariance",
        description="Pins witness prefix invariance under merge (SPEC §9.3): merging backdated source facts into a target with an existing witness cursor P leaves the fold state at P unchanged because witness boundaries are append-order (rowid), not event-time (ts).",
        spec=Spec(
            name="account",
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
        target_facts=[
            (
                "01TARGET000000000000000001",
                Fact(
                    kind="account",
                    ts=100.0,
                    payload={"amount": 500.0, "desc": "init"},
                    observer="bank",
                ),
            ),
            (
                "01TARGET000000000000000002",
                Fact(
                    kind="account",
                    ts=200.0,
                    payload={"amount": -100.0, "desc": "atm"},
                    observer="bank",
                ),
            ),
        ],
        source_facts=[
            (
                "01SOURCE000000000000000001",
                Fact(
                    kind="account",
                    ts=50.0,
                    payload={"amount": 25.0, "desc": "backdated_interest"},
                    observer="bank",
                ),
            ),
            (
                "01SOURCE000000000000000002",
                Fact(
                    kind="account",
                    ts=300.0,
                    payload={"amount": 200.0, "desc": "salary"},
                    observer="bank",
                ),
            ),
        ],
        cursors={
            "p_cursor": "01TARGET000000000000000002",
            "head": "head",
        },
    ),
    # 6. Empty source
    MergeCase(
        name="merge-empty-source",
        description="Pins empty source merge boundary: merging an empty source store into a populated target adds 0 facts, skips 0 facts, and leaves target store contents unchanged.",
        target_facts=[
            (
                "01TARGET000000000000000001",
                Fact(
                    kind="note",
                    ts=100.0,
                    payload={"text": "hello"},
                    observer="alice",
                ),
            ),
            (
                "01TARGET000000000000000002",
                Fact(
                    kind="note",
                    ts=200.0,
                    payload={"text": "world"},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[],
    ),
    # 7. Empty target
    MergeCase(
        name="merge-empty-target",
        description="Pins empty target merge boundary: merging a populated source store into an empty target store adds all source facts and preserves source ordering.",
        target_facts=[],
        source_facts=[
            (
                "01SOURCE000000000000000001",
                Fact(
                    kind="item",
                    ts=10.0,
                    payload={"name": "first"},
                    observer="bob",
                ),
            ),
            (
                "01SOURCE000000000000000002",
                Fact(
                    kind="item",
                    ts=20.0,
                    payload={"name": "second"},
                    observer="bob",
                ),
            ),
        ],
    ),
    # 8. Self-merge idempotence
    MergeCase(
        name="merge-self-idempotence",
        description="Pins self-merge idempotence edge case: merging a store into itself adds 0 facts, skips all existing facts as duplicates, and leaves store contents unchanged.",
        target_facts=[
            (
                "01SELF00000000000000000001",
                Fact(
                    kind="ping",
                    ts=100.0,
                    payload={"seq": 1},
                    observer="alice",
                ),
            ),
            (
                "01SELF00000000000000000002",
                Fact(
                    kind="ping",
                    ts=200.0,
                    payload={"seq": 2},
                    observer="alice",
                ),
            ),
        ],
        self_merge=True,
    ),
    # 9. Both empty
    MergeCase(
        name="merge-both-empty",
        description="Pins empty target and empty source merge boundary: merging two empty stores produces zero added and zero skipped facts.",
        target_facts=[],
        source_facts=[],
    ),
    # 10. Interleaved timestamps: rowid append sequence vs (ts, id) replay total order
    MergeCase(
        name="merge-interleaved-timestamps-replay-total-order",
        description="Pins post-merge rowid append sequence vs replay total order: target retains initial rows at rowids 1-2 and appends source rows at rowids 3-5 in source (ts, id) order, while full store replay orders all 5 facts by (ts ASC, id ASC).",
        spec=Spec(
            name="event_stream",
            state_fields=(
                Field(name="events", kind="list"),
                Field(name="count", kind="int"),
            ),
            folds=(
                Collect(target="events"),
                Count(target="count"),
            ),
        ),
        target_facts=[
            (
                "01TARGET000000000000000001",
                Fact(
                    kind="event_stream",
                    ts=100.0,
                    payload={"step": "T1"},
                    observer="alice",
                ),
            ),
            (
                "01TARGET000000000000000002",
                Fact(
                    kind="event_stream",
                    ts=300.0,
                    payload={"step": "T2"},
                    observer="alice",
                ),
            ),
        ],
        source_facts=[
            (
                "01SOURCE000000000000000001",
                Fact(
                    kind="event_stream",
                    ts=50.0,
                    payload={"step": "S1"},
                    observer="bob",
                ),
            ),
            (
                "01SOURCE000000000000000002",
                Fact(
                    kind="event_stream",
                    ts=200.0,
                    payload={"step": "S2"},
                    observer="bob",
                ),
            ),
            (
                "01SOURCE000000000000000003",
                Fact(
                    kind="event_stream",
                    ts=400.0,
                    payload={"step": "S3"},
                    observer="bob",
                ),
            ),
        ],
        cursors={
            "head": "head",
        },
    ),
]


def _populate(db_path: Path, facts: list[tuple[str, Fact]]) -> None:
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact in facts:
        store.append(fact, id_override=fid)
    store.close()


def generate_merge_vectors() -> None:
    MERGE_DIR.mkdir(parents=True, exist_ok=True)
    for case in MERGE_CASES:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            target_path = tmp_path / "target.db"
            source_path = tmp_path / "source.db"

            _populate(target_path, case.target_facts)
            if not case.self_merge:
                _populate(source_path, case.source_facts)
                merge_res = merge_store(target_path, source_path)
            else:
                merge_res = merge_store(target_path, target_path)

            conn = sqlite3.connect(str(target_path))
            rows = conn.execute(
                "SELECT id, kind, ts, observer, origin, payload FROM facts ORDER BY rowid ASC"
            ).fetchall()
            conn.close()

            post_merge_ids = [r[0] for r in rows]
            post_merge_facts = [
                [
                    r[0],
                    {
                        "kind": r[1],
                        "ts": r[2],
                        "payload": json.loads(r[5]),
                        "observer": r[3],
                        "origin": r[4],
                    },
                ]
                for r in rows
            ]

            witness_folds: dict[str, Any] = {}
            if case.spec and case.cursors:
                for label, cursor_addr in case.cursors.items():
                    pos = resolve_witness_position(target_path, cursor_addr)
                    with StoreReader(target_path) as reader:
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
                        witness_folds[label] = json.loads(json.dumps(state))

        input_doc: dict[str, Any] = {
            "target": [[fid, fact_to_dict(f)] for fid, f in case.target_facts],
        }
        if not case.self_merge:
            input_doc["source"] = [[fid, fact_to_dict(f)] for fid, f in case.source_facts]
        else:
            input_doc["self_merge"] = True

        if case.spec:
            input_doc["spec"] = spec_to_dict(case.spec)
        if case.cursors:
            input_doc["cursors"] = case.cursors

        expected_doc: dict[str, Any] = {
            "result": {
                "facts_added": merge_res.facts_added,
                "facts_skipped": merge_res.facts_skipped,
                "ticks_added": merge_res.ticks_added,
                "ticks_skipped": merge_res.ticks_skipped,
            },
            "post_merge_ids": post_merge_ids,
            "post_merge_facts": post_merge_facts,
        }
        if witness_folds:
            expected_doc["witness_folds"] = witness_folds

        vector = {
            "name": case.name,
            "description": case.description,
            "input": input_doc,
            "expected": expected_doc,
        }

        out_path = MERGE_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    generate_merge_vectors()
