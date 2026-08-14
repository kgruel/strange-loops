"""Conformance runner for fold/replay semantics against golden vectors.

Loads all vectors from spec/conformance/vectors/fold/*.json dynamically
and validates exact parity between Spec.replay() output and expected state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
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

REPO_ROOT = Path(__file__).resolve().parents[3]
VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "fold"


def _decode_field(data: dict[str, Any]) -> Field:
    return Field(
        name=data["name"],
        kind=data["kind"],
        optional=data.get("optional", False),
    )


def _decode_fold(data: dict[str, Any]) -> FoldOp:
    op = data["op"]
    if op == "latest":
        return Latest(target=data["target"])
    elif op == "count":
        return Count(target=data["target"])
    elif op == "sum":
        return Sum(target=data["target"], field=data["field"])
    elif op == "collect":
        return Collect(target=data["target"], max=data.get("max", 0))
    elif op == "upsert":
        return Upsert(target=data["target"], key=data["key"])
    elif op == "top_n":
        return TopN(
            target=data["target"],
            key=data["key"],
            by=data["by"],
            n=data["n"],
            desc=data.get("desc", True),
        )
    elif op == "min":
        return Min(target=data["target"], field=data["field"])
    elif op == "max":
        return Max(target=data["target"], field=data["field"])
    elif op == "avg":
        return Avg(target=data["target"], field=data["field"])
    elif op == "window":
        return Window(target=data["target"], field=data["field"], size=data["size"])
    else:
        raise ValueError(f"Unknown fold op: {op}")


def _decode_spec(data: dict[str, Any]) -> Spec:
    return Spec(
        name=data["name"],
        about=data.get("about", ""),
        input_fields=tuple(_decode_field(f) for f in data.get("input_fields", ())),
        state_fields=tuple(_decode_field(f) for f in data.get("state_fields", ())),
        folds=tuple(_decode_fold(f) for f in data.get("folds", ())),
    )


def _load_vectors() -> list[Path]:
    return sorted(VECTORS_DIR.glob("*.json"))


@pytest.mark.parametrize("vector_path", _load_vectors(), ids=lambda p: p.stem)
def test_conformance_fold(vector_path: Path) -> None:
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"

    spec = _decode_spec(vector["input"]["spec"])
    payloads = vector["input"]["payloads"]
    expected = vector["expected"]

    actual_state = spec.replay(payloads)
    actual_json = json.loads(json.dumps(actual_state))

    assert actual_json == expected
