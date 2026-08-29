"""Conformance runner for exact replication (backend-contract.html §08).

Loads all vectors from ``spec/conformance/vectors/replicate/*.json`` the way
``test_conformance_replay.py`` loads its two areas — one glob, one parametrize,
the envelope asserted before the body.

Three properties every vector states, and each is checked here:

1. **The outcome.** Accepted, or refused with a NAMED contract refusal. Only
   contract refusals appear in a vector: a vector is language-neutral, and
   naming this backend's ``AppendRejected`` in one would pin a Python class on
   an implementation that has no such family. The malformed-batch cases live in
   ``test_arrival_transfer.py`` as unit tests for exactly that reason.
2. **The resulting bytes.** ``expected.log`` is the target's complete file,
   line for line. For an accepted vector that is the byte-for-byte hash
   preservation claim; for a refused one it equals ``input.target``, which is
   the refuse-before-mutation claim. Both fall out of the same assertion.
3. **The head.** Stated as well as derivable, so a store that produced the
   right bytes through the wrong head would still be caught.

Offered records are handed over as the plain objects ``json.load`` produced —
deliberately NOT through ``decode_record``. Decoding here would recompute
``rh`` and refuse a deliberately-wrong digest inside the harness, before the
implementation ever got the chance to.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from engine.arrival import ArrivalLog
from engine.arrival_contract import Head, HeadMismatch, SameHeightFork
from engine.arrival_file_backend import FileLedger

REPO_ROOT = Path(__file__).resolve().parents[3]
REPLICATE_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "replicate"

# The refusals a vector may name. A refusal outside this mapping is a vector
# claiming something the contract does not define, and KeyError says so loudly.
REFUSALS = {"SameHeightFork": SameHeightFork, "HeadMismatch": HeadMismatch}

# The three families §D.2 requires, by filename prefix. Asserted as a set so a
# family that silently loses its last vector fails rather than passing vacuously.
FAMILIES = (
    "replicate-exact-suffix-",
    "replicate-same-height-",
    "replicate-catch-up-",
)


def _load_vectors(vectors_dir: Path) -> list[Path]:
    return sorted(vectors_dir.glob("*.json"))


def _head(data: dict[str, Any] | None) -> Head | None:
    if data is None:
        return None
    return Head(
        lineage=data["lineage"],
        ordinal=data["ordinal"],
        record_hash=data["record_hash"],
    )


def test_every_replicate_family_has_vectors():
    """§D.2 names three families; a family with no vectors proves nothing."""
    stems = [path.stem for path in _load_vectors(REPLICATE_VECTORS_DIR)]
    assert stems, "the replicate area holds no vectors at all"
    for family in FAMILIES:
        assert any(stem.startswith(family) for stem in stems), (
            f"no vector in the {family!r} family"
        )


@pytest.mark.parametrize(
    "vector_path", _load_vectors(REPLICATE_VECTORS_DIR), ids=lambda p: p.stem
)
def test_conformance_replicate(vector_path: Path, tmp_path: Path) -> None:
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"
    assert vector["name"] == vector_path.stem, "vector name must match its file stem"

    target_lines = vector["input"]["target"]
    offered = vector["input"]["records"]
    expected = vector["expected"]

    log_path = tmp_path / f"{vector['name']}.arrival"
    log_path.write_text("\n".join(target_lines) + "\n", encoding="utf-8")

    ledger = FileLedger(ArrivalLog(log_path))
    if expected["outcome"] == "accepted":
        commit = ledger.replicate(_head(vector["input"]["expected_head"]), offered)
        assert commit.after == _head(expected["head"])
        assert [dict(record) for record in commit.records] == offered, (
            "the records the commit reports are not the records that were "
            "offered — something was assigned"
        )
    else:
        assert expected["outcome"] == "refused", expected["outcome"]
        with pytest.raises(REFUSALS[expected["refusal"]]):
            ledger.replicate(_head(vector["input"]["expected_head"]), offered)

    assert log_path.read_text(encoding="utf-8").splitlines() == expected["log"]
    assert ledger.head() == _head(expected["head"])
