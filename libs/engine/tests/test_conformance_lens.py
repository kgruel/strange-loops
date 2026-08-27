"""Conformance runner for the declared read lens.

Loads all vectors dynamically from spec/conformance/vectors/lens/*.json.

Fold replay is receipt order (rowid ASC), which is per-store. Reads across a
combine vertex's member stores have no receipt axis, so they read under a
DECLARED key: `input.ordering`, defaulting to `{"by_key": "ts"}` when absent.

- The default ts family runs through the production combined read
  (`vertex_facts`), whose (ts ASC, id ASC) ordering IS that declaration. It
  is the last place ts tie-breaking and sub-millisecond ts precision still
  carry ordering force.
- Declared non-default keys totalize the combined read's records through the
  atoms primitive, which owns the one `(K(record), id ASC)` definition.

Field resolution is `atoms.resolve_key_field` (`ts`/`id` from the envelope,
everything else from the payload) — the SAME function the generator and
`StoreReader.ordered` bind, so the family rule is shared rather than restated
per surface. `lens-by-key-payload-seq`, whose payload-key order disagrees with
both its ts order and its id order, still catches a reader that resolves keys
its own way.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact
from atoms.ordering import ByKey, OrderingError, resolve_key_field, totalize
from engine.sqlite_store import SqliteStore
from engine.vertex_reader import vertex_facts

REPO_ROOT = Path(__file__).resolve().parents[3]
LENS_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "lens"

_MEMBER_KDL = (
    'name "{label}"\n'
    'store "{store}"\n'
    'loops {{\n  {kind} {{\n    fold {{\n      n "inc"\n    }}\n  }}\n}}\n'
)
_LOOPS_KDL = 'loops {{\n  {kind} {{\n    fold {{\n      n "inc"\n    }}\n  }}\n}}\n'


#: The ordering a vector is read under when `input.ordering` is absent.
DEFAULT_ORDERING = ByKey("ts")


def _decode_ordering(wire: dict[str, Any] | None) -> ByKey:
    if wire is None:
        return DEFAULT_ORDERING
    assert "by_key" in wire, f"unsupported lens ordering on the wire: {wire!r}"
    return ByKey(wire["by_key"])


def _totalize_rows(rows: list[dict[str, Any]], ordering: ByKey) -> list[dict[str, Any]]:
    return totalize(rows, ordering, get_field=resolve_key_field, get_id=lambda r: r["id"])


def _load_vectors(vectors_dir: Path) -> list[Path]:
    return sorted(vectors_dir.glob("*.json"))


def _decode_fact(data: dict[str, Any]) -> Fact:
    return Fact(
        kind=data["kind"],
        ts=data["ts"],
        payload=data["payload"],
        observer=data["observer"],
        origin=data.get("origin", ""),
    )


def _build_combine_vertex(root: Path, kind: str, members: dict[str, Any]) -> Path:
    member_paths = []
    for label, facts in members.items():
        store_path = root / f"{label}.db"
        vertex_path = root / f"{label}.vertex"
        vertex_path.write_text(
            _MEMBER_KDL.format(label=label, store=store_path, kind=kind)
        )
        store = SqliteStore(
            path=store_path,
            serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
            deserialize=Fact.from_dict,
        )
        for fid, fact_dict in facts:
            store.append(_decode_fact(fact_dict), id_override=fid)
        store.close()
        member_paths.append(vertex_path)

    parent = root / "parent.vertex"
    refs = "\n".join(f'  vertex "{p}"' for p in member_paths)
    parent.write_text(
        f'name "parent"\ncombine {{\n{refs}\n}}\n' + _LOOPS_KDL.format(kind=kind)
    )
    return parent


@pytest.mark.parametrize(
    "vector_path", _load_vectors(LENS_VECTORS_DIR), ids=lambda p: p.stem
)
def test_conformance_lens(vector_path: Path, tmp_path: Path) -> None:
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    for key in ("name", "description", "input", "expected"):
        assert key in vector, f"Vector {vector_path} missing {key!r}"

    kind = vector["input"]["kind"]
    parent = _build_combine_vertex(tmp_path, kind, vector["input"]["members"])

    rows = vertex_facts(parent, 0.0, float("inf"), kind=kind)
    ordering = _decode_ordering(vector["input"].get("ordering"))

    if ordering == DEFAULT_ORDERING:
        # The production combined read's (ts ASC, id ASC) IS this declaration.
        assert [r["id"] for r in rows] == vector["expected"]["lens_order"]
        return

    if "error" in vector["expected"]:
        with pytest.raises(OrderingError):
            _totalize_rows(rows, ordering)
        return

    ordered = _totalize_rows(rows, ordering)
    assert [r["id"] for r in ordered] == vector["expected"]["lens_order"]


def test_lens_area_is_not_empty() -> None:
    """Guard the discovery glob: an empty area would pass vacuously."""
    assert _load_vectors(LENS_VECTORS_DIR), "no lens vectors discovered"


def test_lens_area_covers_both_key_families_and_a_refusal() -> None:
    """Guard the key axis itself.

    The runner branches three ways; a vector set that lost its non-default-key
    family, or its refusal case, would still pass every parametrized case while
    silently exercising only the ts arm.
    """
    orderings, refusals = [], 0
    for path in _load_vectors(LENS_VECTORS_DIR):
        with path.open(encoding="utf-8") as f:
            vector = json.load(f)
        orderings.append(_decode_ordering(vector["input"].get("ordering")))
        refusals += "error" in vector["expected"]

    assert DEFAULT_ORDERING in orderings, "ts family missing"
    assert any(o != DEFAULT_ORDERING for o in orderings), "no non-ts key family"
    assert refusals, "no refusal vector"


#: An adversarial record set for the cross-surface check: the payload key
#: `seq`, the envelope `ts` and the envelope `id` each impose a DIFFERENT
#: order (mirroring `lens-by-key-payload-seq`), so two surfaces that disagree
#: about where a key resolves cannot accidentally agree on the sequence.
_CROSS_SURFACE_FACTS = [
    ("01TESTULID0000000000000003", {"kind": "record", "ts": 1000.0,
     "payload": {"seq": 2}, "observer": "kyle"}),
    ("01TESTULID0000000000000001", {"kind": "record", "ts": 3000.0,
     "payload": {"seq": 3}, "observer": "kyle"}),
    ("01TESTULID0000000000000002", {"kind": "record", "ts": 2000.0,
     "payload": {"seq": 1, "kind": "in-the-payload"}, "observer": "kyle"}),
]


@pytest.mark.parametrize(
    "field,expected_size", [("ts", 3), ("id", 3), ("seq", 3), ("kind", 1)]
)
def test_ordered_and_the_lens_resolver_agree_on_the_key_family(
    field: str, expected_size: int, tmp_path: Path
) -> None:
    """`StoreReader.ordered` and the conformance lens read one declaration alike.

    The family rule (`ts`/`id` from the envelope, everything else from the
    payload) is `atoms.resolve_key_field`, but sharing a function only helps
    if every surface actually routes through it. This holds the two ends
    against each other on all three arms: an envelope key that is
    column-backed (`ts`), an envelope key that is the id itself, and a payload
    key, and a stored column that is NOT an envelope key (`kind`), which
    resolves against the payload like any other declared key. Under the
    payload-only resolver `ordered` used to carry, the `ts` arm returns []
    against a full lens order; under a resolver that treats every stored
    column as envelope-backed, the `kind` arm returns all three.
    """
    from atoms import ByKey
    from engine.store_reader import StoreReader

    parent = _build_combine_vertex(
        tmp_path, "record", {"a": [(fid, f) for fid, f in _CROSS_SURFACE_FACTS]}
    )
    rows = vertex_facts(parent, 0.0, float("inf"), kind="record")
    lens_order = [r["id"] for r in _totalize_rows(rows, ByKey(field))]

    with StoreReader(tmp_path / "a.db") as reader:
        reader_order = [f["id"] for f in reader.ordered(len(rows), ByKey(field))]

    assert reader_order == lens_order
    # Guard against a vacuous pass: each arm's size is pinned, so an
    # agreed-upon EMPTY projection can never stand in for agreement.
    assert len(lens_order) == expected_size
