"""Conformance runner for the (ts, id) read lens.

Loads all vectors dynamically from spec/conformance/vectors/lens/*.json.

Fold replay is receipt order (rowid ASC), which is per-store. Reads across
a combine vertex's member stores have no receipt axis, so they fall back to
the explicit (ts ASC, id ASC) read lens. These vectors pin that lens — the
last place where ts tie-breaking and sub-millisecond ts precision still
carry ordering force.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from atoms import Fact
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
    assert [r["id"] for r in rows] == vector["expected"]["lens_order"]


def test_lens_area_is_not_empty() -> None:
    """Guard the discovery glob: an empty area would pass vacuously."""
    assert _load_vectors(LENS_VECTORS_DIR), "no lens vectors discovered"
