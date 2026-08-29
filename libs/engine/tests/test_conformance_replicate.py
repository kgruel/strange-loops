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

# The three families §D.2 requires, and the EXACT vector inventory of each.
#
# Filenames rather than a count, and a count rather than "at least one": a
# family check that only asks whether the family is non-empty goes green when a
# fixture is deleted, right up until the last one goes. That is the shape of
# ratchet that stops ratcheting quietly — the vectors are the oracle, so a
# vector that disappears takes a claim with it and must say which one.
#
# GROW this when a vector is added; shrink it only when a claim is genuinely
# retired, and say which in the commit.
VECTOR_INVENTORY: dict[str, frozenset[str]] = {
    "replicate-exact-suffix-": frozenset({
        "replicate-exact-suffix-single-record-accepted",
        "replicate-exact-suffix-batch-lands-whole",
        "replicate-exact-suffix-refuses-a-gap-above-the-head",
        "replicate-exact-suffix-refuses-a-stale-full-head-pin",
    }),
    "replicate-same-height-": frozenset({
        "replicate-same-height-fork-at-the-head-refuses",
        "replicate-same-height-fork-below-the-head-refuses",
        "replicate-same-height-agreement-is-not-a-fork",
    }),
    "replicate-catch-up-": frozenset({
        "replicate-catch-up-preserves-signed-records-byte-for-byte",
        "replicate-catch-up-preserves-authored-time-and-origin",
        "replicate-catch-up-from-a-genesis-only-replica",
    }),
}


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


def test_the_replicate_vector_inventory_is_exactly_what_is_on_disk():
    """Every named vector present, and no unclassified vector present.

    Both directions. A missing fixture fails NAMING ITSELF, so a deleted
    vector cannot go unnoticed while the family still has siblings; and a
    vector belonging to no family fails too, so a new claim cannot be added
    without being filed under the family it belongs to.
    """
    on_disk = {path.stem for path in _load_vectors(REPLICATE_VECTORS_DIR)}
    expected = frozenset().union(*VECTOR_INVENTORY.values())

    assert on_disk == expected, (
        f"missing: {sorted(expected - on_disk)}; "
        f"unclassified: {sorted(on_disk - expected)}"
    )
    for family, members in VECTOR_INVENTORY.items():
        assert members, f"the {family!r} family names no vectors"
        for stem in members:
            assert stem.startswith(family), (
                f"{stem!r} is filed under {family!r} but is not named for it"
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
