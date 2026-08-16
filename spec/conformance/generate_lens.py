"""Generator for lens conformance vectors.

The `lens` area pins the explicit `(ts, id)` READ LENS — the event-time
projection that survived the move of fold replay to receipt order.

Fold order is receipt order (`rowid ASC`), which is per-store. A combine
vertex reads across member stores, where no receipt axis exists, so those
reads fall back to `(ts ASC, id ASC)`. That ordering is what these vectors
pin, and it is the only place the tie-break and precision properties that
used to be replay concerns still have force:

- ties on `ts` break by fact `id` ascending
- sub-millisecond `ts` deltas survive storage and still order the lens

Both cases were relocated here from the `replay` area, where they no longer
assert anything meaningful once replay stopped consulting `ts`.

Run once to generate/regenerate frozen vector files:
    uv run python spec/conformance/generate_lens.py
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from atoms import Fact
from engine.sqlite_store import SqliteStore
from engine.vertex_reader import vertex_facts

from generate_replay import REPO_ROOT, fact_to_dict

LENS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "lens"


@dataclass(frozen=True)
class LensCase:
    name: str
    description: str
    kind: str
    #: Member store label -> facts appended to that member, in append order.
    members: dict[str, list[tuple[str, Fact]]]


LENS_CASES: list[LensCase] = [
    LensCase(
        name="lens-timestamp-tie-id-asc",
        description="Pins the (ts, id) read lens tie-break: two facts sharing a timestamp are returned id ASC across member stores, regardless of which member holds them or the order each member received them.",
        kind="record",
        members={
            "a": [
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="record",
                        ts=1000.0,
                        payload={"k": "same_key", "val": "from_higher_id"},
                        observer="kyle",
                    ),
                ),
            ],
            "b": [
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
        },
    ),
    LensCase(
        name="lens-sub-millisecond-timestamp-precision",
        description="Pins sub-millisecond precision through the (ts, id) read lens: timestamps differing by microsecond deltas survive store serialization and still order the lens, even when the facts were appended in a different order and live in different member stores.",
        kind="sensor_readings",
        members={
            "a": [
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
                    "01TESTULID0000000000000003",
                    Fact(
                        kind="sensor_readings",
                        ts=1736942400.000100,
                        payload={"sensor": "s1", "reading": "100us"},
                        observer="sensor",
                    ),
                ),
            ],
            "b": [
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="sensor_readings",
                        ts=1736942400.000001,
                        payload={"sensor": "s1", "reading": "1us"},
                        observer="sensor",
                    ),
                ),
            ],
        },
    ),
]


_MEMBER_KDL = (
    'name "{label}"\n'
    'store "{store}"\n'
    "loops {{\n  {kind} {{\n    fold {{\n      n \"inc\"\n    }}\n  }}\n}}\n"
)


_LOOPS_KDL = "loops {{\n  {kind} {{\n    fold {{\n      n \"inc\"\n    }}\n  }}\n}}\n"


def build_combine_vertex(root: Path, case: LensCase) -> Path:
    """Scaffold one member vertex per member store plus a combine parent."""
    member_paths = []
    for label, facts in case.members.items():
        store_path = root / f"{label}.db"
        vertex_path = root / f"{label}.vertex"
        vertex_path.write_text(
            _MEMBER_KDL.format(label=label, store=store_path, kind=case.kind)
        )
        store = SqliteStore(
            path=store_path,
            serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
            deserialize=Fact.from_dict,
        )
        for fid, fact in facts:
            store.append(fact, id_override=fid)
        store.close()
        member_paths.append(vertex_path)

    parent = root / "parent.vertex"
    members = "\n".join(f'  vertex "{p}"' for p in member_paths)
    parent.write_text(
        f'name "parent"\ncombine {{\n{members}\n}}\n'
        + _LOOPS_KDL.format(kind=case.kind)
    )
    return parent


def generate_lens_vectors() -> None:
    LENS_DIR.mkdir(parents=True, exist_ok=True)

    for case in LENS_CASES:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = build_combine_vertex(Path(tmp_dir), case)
            rows = vertex_facts(parent, 0.0, float("inf"), kind=case.kind)
            lens_order = [r["id"] for r in rows]

        vector = {
            "name": case.name,
            "description": case.description,
            "input": {
                "kind": case.kind,
                "members": {
                    label: [[fid, fact_to_dict(f)] for fid, f in facts]
                    for label, facts in case.members.items()
                },
            },
            "expected": {"lens_order": lens_order},
        }

        out_path = LENS_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    generate_lens_vectors()
