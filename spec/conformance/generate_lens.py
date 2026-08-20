"""Generator for lens conformance vectors.

The `lens` area pins the READ LENS: the declared projection a combine vertex
reads its members under. Fold order is receipt order (`rowid ASC`), which is
per-store; a combine vertex has no receipt axis across members, so a combined
read must name the key it orders by.

Each case names its `Ordering` (`atoms.ordering`). The totalization is
`(K(record), id ASC)` and comes from the atoms primitive `totalize` — this
generator imports it rather than restating the sort.

Two families:

- `ByKey("ts")` — the historical event-time lens, and the default. It pins
  the properties that used to be replay concerns: ties on `ts` break by fact
  `id` ascending, and sub-millisecond `ts` deltas survive storage and still
  order the lens. These vectors are frozen normative artifacts; their
  expected order still comes from the production combined read
  (`vertex_facts`), with `totalize` asserted to agree.
- `ByKey(<payload field>)` — projections under a declared payload key,
  including the adversarial postures the primitive rules on: a record missing
  K is not in the projection, equal K breaks by id ascending, and mixed key
  types are refused.

FIELD RESOLUTION (see `lens_get_field`): `ts` and `id` resolve against the
record envelope; every other key resolves against the payload. The runner
restates this resolver — it cannot import this generator — so
`lens-by-key-payload-seq` is built to order DIFFERENTLY under its payload key
than under `ts`, which is what catches resolver drift between the two.

Run once to generate/regenerate frozen vector files:
    uv run python spec/conformance/generate_lens.py
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

from atoms import Fact
from atoms.ordering import ByKey, Ordering, OrderingError, totalize
from engine.sqlite_store import SqliteStore
from engine.vertex_reader import vertex_facts

from generate_replay import REPO_ROOT, fact_to_dict

LENS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "lens"

#: The ordering a vector is read under when it declares none. Vectors in this
#: family omit `input.ordering` entirely — that omission is what keeps the
#: pre-existing normative files byte-identical.
DEFAULT_ORDERING = ByKey("ts")


def lens_get_field(record: dict[str, Any], field: str) -> Any:
    """Resolve a declared lens key against a combined-read record.

    `ts` and `id` are envelope attributes; every other key is a flat payload
    field. Restated verbatim in the conformance runner.
    """
    if field in ("ts", "id"):
        return record.get(field)
    payload = record.get("payload") or {}
    return payload.get(field)


def ordering_to_wire(ordering: Ordering) -> dict[str, Any]:
    """Serialize an Ordering for the vector wire schema."""
    if isinstance(ordering, ByKey):
        return {"by_key": ordering.field}
    raise ValueError(f"lens vectors declare ByKey orderings only, got {ordering!r}")


@dataclass(frozen=True)
class LensCase:
    name: str
    description: str
    kind: str
    #: Member store label -> facts appended to that member, in append order.
    members: dict[str, list[tuple[str, Fact]]]
    #: The declared read order. Omitted from the vector when it is the default.
    ordering: Ordering = dc_field(default=DEFAULT_ORDERING)
    #: Set when the declared ordering must REFUSE these records; the vector
    #: then carries `expected.error` instead of `expected.lens_order`.
    expect_error: bool = False


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
    LensCase(
        name="lens-by-key-payload-seq",
        description="Pins a declared non-ts lens key: the projection orders by the flat payload field 'seq', not by ts. The seq order is the REVERSE of both the ts order and the id order, so a reader that resolves 'seq' against the envelope, falls back to the ts lens, or sorts by id produces a different sequence and fails.",
        kind="record",
        ordering=ByKey("seq"),
        members={
            "a": [
                (
                    "01TESTULID0000000000000003",
                    Fact(
                        kind="record",
                        ts=3000.0,
                        payload={"seq": 1, "note": "earliest_seq_latest_ts_highest_id"},
                        observer="kyle",
                    ),
                ),
                (
                    "01TESTULID0000000000000001",
                    Fact(
                        kind="record",
                        ts=1000.0,
                        payload={"seq": 3, "note": "latest_seq_earliest_ts_lowest_id"},
                        observer="kyle",
                    ),
                ),
            ],
            "b": [
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="record",
                        ts=2000.0,
                        payload={"seq": 2, "note": "middle"},
                        observer="kyle",
                    ),
                ),
            ],
        },
    ),
    LensCase(
        name="lens-by-key-tie-id-asc",
        description="Pins the tie-break under a declared non-ts key: three records share seq=7, so the projection falls to fact id ASCENDING. Append order and ts order both contradict id order here, so neither can be mistaken for the tie-break.",
        kind="record",
        ordering=ByKey("seq"),
        members={
            "a": [
                (
                    "01TESTULID0000000000000003",
                    Fact(
                        kind="record",
                        ts=1000.0,
                        payload={"seq": 7, "note": "highest_id_earliest_ts"},
                        observer="kyle",
                    ),
                ),
                (
                    "01TESTULID0000000000000001",
                    Fact(
                        kind="record",
                        ts=3000.0,
                        payload={"seq": 7, "note": "lowest_id_latest_ts"},
                        observer="kyle",
                    ),
                ),
            ],
            "b": [
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="record",
                        ts=2000.0,
                        payload={"seq": 7, "note": "middle_id"},
                        observer="kyle",
                    ),
                ),
            ],
        },
    ),
    LensCase(
        name="lens-by-key-missing-field-excluded",
        description="Pins missing-K non-membership: a key names what it projects, so a record whose payload carries no 'seq' is NOT in the ByKey('seq') projection. Exclusion is by declaration, not silent loss — the record is present in both member stores and readable under any other lens.",
        kind="record",
        ordering=ByKey("seq"),
        members={
            "a": [
                (
                    "01TESTULID0000000000000001",
                    Fact(
                        kind="record",
                        ts=1000.0,
                        payload={"seq": 2, "note": "keyed"},
                        observer="kyle",
                    ),
                ),
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="record",
                        ts=2000.0,
                        payload={"note": "no_seq_field_at_all"},
                        observer="kyle",
                    ),
                ),
            ],
            "b": [
                (
                    "01TESTULID0000000000000003",
                    Fact(
                        kind="record",
                        ts=3000.0,
                        payload={"seq": None, "note": "explicit_null_seq"},
                        observer="kyle",
                    ),
                ),
                (
                    "01TESTULID0000000000000004",
                    Fact(
                        kind="record",
                        ts=4000.0,
                        payload={"seq": 1, "note": "keyed_lower"},
                        observer="kyle",
                    ),
                ),
            ],
        },
    ),
    LensCase(
        name="lens-by-key-mixed-types-refused",
        description="Pins type-mixed refusal: 'seq' arrives as an int on one record and a string on another, so the declared projection has no order and the read REFUSES rather than coercing. A reader that stringifies, or that sorts int-before-str by type name, is non-conformant.",
        kind="record",
        ordering=ByKey("seq"),
        expect_error=True,
        members={
            "a": [
                (
                    "01TESTULID0000000000000001",
                    Fact(
                        kind="record",
                        ts=1000.0,
                        payload={"seq": 1, "note": "int_key"},
                        observer="kyle",
                    ),
                ),
            ],
            "b": [
                (
                    "01TESTULID0000000000000002",
                    Fact(
                        kind="record",
                        ts=2000.0,
                        payload={"seq": "2", "note": "string_key"},
                        observer="kyle",
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


def _expected_for(case: LensCase, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The expected block for one case, from the combined read's records.

    The default `ByKey("ts")` family keeps `vertex_facts` as its oracle — those
    vectors are frozen normative artifacts and their order must not start
    depending on a different code path. `totalize` is asserted to AGREE with
    it, which is how the family is pinned "via the atoms primitive" without
    swapping the oracle underneath the frozen files. A disagreement is a
    finding, so it fails the regeneration loudly rather than rewriting bytes.
    """
    def ordered() -> list[dict[str, Any]]:
        return totalize(
            rows, case.ordering, get_field=lens_get_field, get_id=lambda r: r["id"]
        )

    if case.expect_error:
        try:
            ordered()
        except OrderingError:
            return {"error": "OrderingError"}
        raise AssertionError(
            f"{case.name} declares expect_error but {case.ordering!r} accepted its records"
        )

    lens_order = [r["id"] for r in ordered()]

    if case.ordering == DEFAULT_ORDERING:
        production_order = [r["id"] for r in rows]
        if lens_order != production_order:
            raise AssertionError(
                f"{case.name}: atoms totalize disagrees with the production combined "
                f"read under {case.ordering!r} — totalize {lens_order}, "
                f"vertex_facts {production_order}. This is a finding, not a regeneration."
            )
        return {"lens_order": production_order}

    return {"lens_order": lens_order}


def generate_lens_vectors() -> None:
    LENS_DIR.mkdir(parents=True, exist_ok=True)

    for case in LENS_CASES:
        with tempfile.TemporaryDirectory() as tmp_dir:
            parent = build_combine_vertex(Path(tmp_dir), case)
            rows = vertex_facts(parent, 0.0, float("inf"), kind=case.kind)

        expected = _expected_for(case, rows)

        input_block: dict[str, Any] = {
            "kind": case.kind,
            "members": {
                label: [[fid, fact_to_dict(f)] for fid, f in facts]
                for label, facts in case.members.items()
            },
        }
        if case.ordering != DEFAULT_ORDERING:
            input_block["ordering"] = ordering_to_wire(case.ordering)

        vector = {
            "name": case.name,
            "description": case.description,
            "input": input_block,
            "expected": expected,
        }

        out_path = LENS_DIR / f"{case.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(vector, f, indent=2)
            f.write("\n")
        print(f"Wrote {out_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    generate_lens_vectors()
