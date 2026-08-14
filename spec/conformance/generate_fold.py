"""Generator for fold/replay conformance vectors (spec/conformance/vectors/fold/*.json).

Builds golden vectors pinning atoms.Spec.replay semantics:
Spec (as JSON), sequence of fact payloads, and exact final state.

Run once to generate/regenerate frozen vector files:
    uv run python spec/conformance/generate_fold.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from atoms import (
    Avg,
    Collect,
    Count,
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

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "fold"


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


@dataclass(frozen=True)
class Case:
    name: str
    description: str
    spec: Spec
    payloads: list[dict[str, Any]]


CASES: list[Case] = [
    # 1. Fold-key string projection: int 0 and str "0" merge into "0" with _n == 2
    Case(
        name="fold-key-string-projection-merge",
        description="Pins decision:design/fold-key-string-projection: integer 0 and string '0' project to the identical string key '0' and merge into one entry with _n=2.",
        spec=Spec(
            name="fold_key_merge",
            state_fields=(Field(name="items", kind="dict"),),
            folds=(Upsert(target="items", key="id"),),
        ),
        payloads=[
            {"_ts": 100.0, "id": 0, "val": "first"},
            {"_ts": 101.0, "id": "0", "val": "second"},
        ],
    ),
    # 2. Fold-key string projection: 0, 0.0, False yield THREE distinct string keys
    Case(
        name="fold-key-string-projection-distinct-types",
        description="Pins decision:design/fold-key-string-projection: keys 0, 0.0, and False project to three distinct string keys '0', '0.0', and 'False'.",
        spec=Spec(
            name="fold_key_distinct",
            state_fields=(Field(name="items", kind="dict"),),
            folds=(Upsert(target="items", key="id"),),
        ),
        payloads=[
            {"_ts": 100.0, "id": 0, "tag": "int-zero"},
            {"_ts": 101.0, "id": 0.0, "tag": "float-zero"},
            {"_ts": 102.0, "id": False, "tag": "bool-false"},
        ],
    ),
    # 3. Upsert last-write-wins, merge defaults, ref accumulation
    Case(
        name="upsert-last-write-wins-and-merge",
        description="Pins decision:design/fold-merge-default: successive upserts for the same key overlay new fields, preserve unmentioned prior fields, accumulate _n, and merge refs.",
        spec=Spec(
            name="upsert_merge_spec",
            state_fields=(Field(name="users", kind="dict"),),
            folds=(Upsert(target="users", key="id"),),
        ),
        payloads=[
            {
                "_ts": 10.0,
                "id": "u1",
                "name": "Alice",
                "role": "engineer",
                "ref": "doc-1",
            },
            {
                "_ts": 11.0,
                "id": "u1",
                "role": "lead",
                "ref": "doc-2, doc-1",
            },
        ],
    ),
    # 4. Count fold
    Case(
        name="count-basic",
        description="Pins Count fold: increments counter once per payload regardless of payload content.",
        spec=Spec(
            name="count_spec",
            state_fields=(Field(name="events", kind="int"),),
            folds=(Count(target="events"),),
        ),
        payloads=[
            {"_ts": 1.0, "kind": "A"},
            {"_ts": 2.0, "kind": "B"},
            {},
        ],
    ),
    # 5. Sum float precision (0.1 + 0.2)
    Case(
        name="sum-float-precision",
        description="Pins Sum fold float arithmetic semantics: adding 0.1 and 0.2 produces exact IEEE-754 representation 0.30000000000000004.",
        spec=Spec(
            name="sum_float_spec",
            state_fields=(Field(name="total", kind="float"),),
            folds=(Sum(target="total", field="amount"),),
        ),
        payloads=[
            {"amount": 0.1},
            {"amount": 0.2},
        ],
    ),
    # 6. Min and Max folds
    Case(
        name="min-max-tracking",
        description="Pins Min and Max fold operations: correctly replaces initial None and tracks running minimum and maximum values.",
        spec=Spec(
            name="min_max_spec",
            state_fields=(
                Field(name="min_temp", kind="float"),
                Field(name="max_temp", kind="float"),
            ),
            folds=(
                Min(target="min_temp", field="temp"),
                Max(target="max_temp", field="temp"),
            ),
        ),
        payloads=[
            {"temp": 15.5},
            {"temp": -3.2},
            {"temp": 42.0},
            {"temp": 0.0},
        ],
    ),
    # 7. Avg running average with hidden state
    Case(
        name="avg-running-average",
        description="Pins Avg fold running average: maintains target_sum and target_count in state alongside running mean.",
        spec=Spec(
            name="avg_spec",
            state_fields=(Field(name="latency", kind="float"),),
            folds=(Avg(target="latency", field="ms"),),
        ),
        payloads=[
            {"ms": 10.0},
            {"ms": 20.0},
            {"ms": 60.0},
        ],
    ),
    # 8. Latest fold timestamp tracking and rejection of missing _ts
    Case(
        name="latest-timestamp-tracking",
        description="Pins Latest fold: captures _ts timestamp deterministically without wall clock and rejects payloads lacking _ts.",
        spec=Spec(
            name="latest_spec",
            state_fields=(Field(name="last_seen", kind="float"),),
            folds=(Latest(target="last_seen"),),
        ),
        payloads=[
            {"_ts": 100.0, "event": "start"},
            {"event": "no_ts"},
            {"_ts": 250.5, "event": "update"},
        ],
    ),
    # 9. Collect bounded history and ref parsing
    Case(
        name="collect-bounded-and-refs",
        description="Pins Collect fold bounded history: keeps up to max items dropping oldest, and parses ref into sorted _refs.",
        spec=Spec(
            name="collect_spec",
            state_fields=(Field(name="history", kind="list"),),
            folds=(Collect(target="history", max=2),),
        ),
        payloads=[
            {"_ts": 1.0, "msg": "first", "ref": "r1"},
            {"_ts": 2.0, "msg": "second"},
            {"_ts": 3.0, "msg": "third", "ref": "r2, r1"},
        ],
    ),
    # 10. Window size boundary (exact size, then one more)
    Case(
        name="window-size-boundary",
        description="Pins Window fold boundary behavior: buffers field values up to size and drops oldest when exceeded.",
        spec=Spec(
            name="window_spec",
            state_fields=(Field(name="intervals", kind="list"),),
            folds=(Window(target="intervals", field="val", size=3),),
        ),
        payloads=[
            {"val": 10},
            {"val": 20},
            {"val": 30},
            {"val": 40},
        ],
    ),
    # 11. TopN descending tie-breaking
    Case(
        name="top-n-descending-ties",
        description="Pins TopN fold descending sort and tie-breaking: retains top n items by score, preserving insertion order on ties.",
        spec=Spec(
            name="top_n_spec",
            state_fields=(Field(name="leaders", kind="dict"),),
            folds=(TopN(target="leaders", key="name", by="score", n=2, desc=True),),
        ),
        payloads=[
            {"name": "alice", "score": 100},
            {"name": "bob", "score": 100},
            {"name": "charlie", "score": 100},
        ],
    ),
    # 12. Missing source field handling
    Case(
        name="missing-source-fields-skipped",
        description="Pins missing source field semantics: numeric folds (Sum, Min, Max, Avg) and Window/Upsert silently skip payloads lacking the field.",
        spec=Spec(
            name="missing_fields_spec",
            state_fields=(
                Field(name="total", kind="float"),
                Field(name="lo", kind="float"),
                Field(name="hi", kind="float"),
                Field(name="mean", kind="float"),
                Field(name="buf", kind="list"),
                Field(name="tab", kind="dict"),
            ),
            folds=(
                Sum(target="total", field="v"),
                Min(target="lo", field="v"),
                Max(target="hi", field="v"),
                Avg(target="mean", field="v"),
                Window(target="buf", field="v", size=3),
                Upsert(target="tab", key="k"),
            ),
        ),
        payloads=[
            {"other": 123},
        ],
    ),
    # 13. None as a fold key
    Case(
        name="upsert-null-key-skipped",
        description="Pins null fold key semantics: an Upsert payload with explicit null key value is ignored without mutating state.",
        spec=Spec(
            name="null_key_spec",
            state_fields=(Field(name="entries", kind="dict"),),
            folds=(Upsert(target="entries", key="id"),),
        ),
        payloads=[
            {"_ts": 1.0, "id": None, "val": "ignored"},
            {"_ts": 2.0, "id": "valid", "val": "kept"},
        ],
    ),
    # 14. Empty input payloads
    Case(
        name="empty-payloads-initial-state",
        description="Pins empty replay semantics: zero payloads replayed on a spec yields initial state exactly.",
        spec=Spec(
            name="empty_spec",
            state_fields=(
                Field(name="str_f", kind="str"),
                Field(name="int_f", kind="int"),
                Field(name="float_f", kind="float"),
                Field(name="bool_f", kind="bool"),
                Field(name="dict_f", kind="dict"),
                Field(name="list_f", kind="list"),
            ),
            folds=(
                Count(target="int_f"),
                Upsert(target="dict_f", key="k"),
                Collect(target="list_f"),
            ),
        ),
        payloads=[],
    ),
    # 15. Off-type rejection with counter
    Case(
        name="numeric-fold-off-type-rejection",
        description="Pins decision:design/fold-off-type-skip-with-counter: non-numeric values including bool are skipped and increment target_rejected counter without mutating state or bumping Avg denominator.",
        spec=Spec(
            name="rejection_spec",
            state_fields=(
                Field(name="sum_val", kind="float"),
                Field(name="avg_val", kind="float"),
                Field(name="min_val", kind="float"),
                Field(name="max_val", kind="float"),
            ),
            folds=(
                Sum(target="sum_val", field="v"),
                Avg(target="avg_val", field="v"),
                Min(target="min_val", field="v"),
                Max(target="max_val", field="v"),
            ),
        ),
        payloads=[
            {"v": 10},
            {"v": "invalid"},
            {"v": True},
            {"v": 20},
        ],
    ),
    # 16. Composed realistic inventory spec
    Case(
        name="composed-inventory-spec",
        description="Pins realistic multi-fold composition: combining Count, Latest, Sum, and Upsert over an inventory event sequence.",
        spec=Spec(
            name="inventory_tracker",
            state_fields=(
                Field(name="transactions", kind="int"),
                Field(name="last_ts", kind="float"),
                Field(name="total_qty", kind="int"),
                Field(name="items", kind="dict"),
            ),
            folds=(
                Count(target="transactions"),
                Latest(target="last_ts"),
                Sum(target="total_qty", field="qty"),
                Upsert(target="items", key="sku"),
            ),
        ),
        payloads=[
            {"_ts": 1000.0, "sku": "SKU-A", "name": "Widget", "qty": 5, "ref": "po-1"},
            {"_ts": 1005.0, "sku": "SKU-B", "name": "Gadget", "qty": 10, "ref": "po-2"},
            {"_ts": 1010.0, "sku": "SKU-A", "price": 19.99, "qty": 3, "ref": "po-3"},
        ],
    ),
]


def generate_all() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        # Replay using reference implementation to produce ground-truth state
        final_state = case.spec.replay(case.payloads)
        # Deep round-trip through JSON to guarantee plain JSON types
        serialized_state = json.loads(json.dumps(final_state))

        vector = {
            "name": case.name,
            "description": case.description,
            "input": {
                "spec": spec_to_dict(case.spec),
                "payloads": case.payloads,
            },
            "expected": serialized_state,
        }

        out_path = OUTPUT_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    generate_all()
