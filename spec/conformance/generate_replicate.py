"""Generator for replicate conformance vectors.

Builds golden vectors pinning backend-contract.html §08 "Exact replication" —
the transfer op that consumes PRE-COORDINATED records and assigns nothing.
Three families, each answering a question the others cannot:

- ``replicate-exact-suffix-*``: the accept path, and the two ways a batch can
  fail to be the suffix that follows the head (a gap above it, and a stale
  full-head pin).
- ``replicate-same-height-fork-*``: a record offered at a height the log
  already holds DIFFERENTLY stops replication, at the head and below it — plus
  the negative control, because a fork refusal that also fires on an AGREEING
  record at an occupied height is a refusal that has stopped meaning "fork".
- ``replicate-catch-up-*``: a stale replica brought forward, where the claim is
  BYTE-FOR-BYTE hash preservation. These vectors carry SIGNED records on
  purpose: an implementation that re-coordinated an exact suffix would assign
  the same lineage, ordinal and predecessor and reproduce identical hashes, so
  an unsigned suffix cannot tell assigning from validating. A signature is
  content the assigning path does not carry, so it is what makes the two
  observably different.

Every vector is deterministic: one fixed lineage, fixed authored times, and the
repo's stub signer. Nothing here reads a clock.

Run once to generate/regenerate frozen vector files:
    uv run --package engine python spec/conformance/generate_replicate.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine.arrival import ArrivalLog, build_record, content_commitment
from engine.arrival_contract import Head, HeadMismatch, SameHeightFork
from engine.arrival_file_backend import FileLedger

REPO_ROOT = Path(__file__).resolve().parents[2]
REPLICATE_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "replicate"

# One fixed lineage across every vector in the area, so a reader comparing two
# vectors is comparing histories and not identifiers.
LINEAGE = "01M2REPLICATEVECTORLINEAGE"
OBSERVER = "kyle"
GENESIS_AT = 1750000000.0
KEY = base64.b64encode(b"k" * 32).decode()


def stub_sign(observer: str, commitment: str) -> str:
    """The repo's deterministic stand-in signer (``tests/conftest.stub_sign``).

    Restated here rather than imported: a vector generator that depended on a
    test package would make the frozen vectors a function of the test tree.
    """
    return "sig:" + hashlib.sha256(f"{observer}/{commitment}".encode()).hexdigest()


@dataclass(frozen=True)
class Rec:
    """One record to append above genesis, stated exactly."""

    k: str
    body: dict[str, Any]
    at: float
    origin: str = ""
    signed: bool = False


def build_log(path: Path, records: tuple[Rec, ...]) -> ArrivalLog:
    """A log holding genesis plus ``records``, built through the real appender."""
    log = ArrivalLog.mint(
        path,
        observer=OBSERVER,
        signer=stub_sign,
        key=KEY,
        lineage=LINEAGE,
        at=GENESIS_AT,
    )
    for rec in records:
        head = log.head()
        sig = (
            stub_sign(
                OBSERVER,
                content_commitment(rec.k, rec.at, OBSERVER, rec.origin, rec.body),
            )
            if rec.signed
            else None
        )
        log.append_record(
            build_record(
                lin=LINEAGE,
                ordinal=head["ord"] + 1,
                prev=head["rh"],
                k=rec.k,
                body=rec.body,
                observer=OBSERVER,
                origin=rec.origin,
                at=rec.at,
                sig=sig,
            )
        )
    return log


def note(index: int, *, signed: bool = False, origin: str = "") -> Rec:
    """The plain record every family uses when the content is not the point."""
    return Rec(
        k="note",
        body={"i": index},
        at=GENESIS_AT + 100.0 + index,
        origin=origin,
        signed=signed,
    )


def lines_of(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def head_dict(log: ArrivalLog) -> dict[str, Any]:
    record = log.head()
    return {
        "lineage": record["lin"],
        "ordinal": record["ord"],
        "record_hash": record["rh"],
    }


@dataclass
class Case:
    """One scenario: what the target holds, what is offered, what is pinned."""

    name: str
    description: str
    target: tuple[Rec, ...]
    offered: tuple[Rec, ...]
    # Which of ``offered``'s coordinates to hand over: a slice of the authority
    # log built from ``offered``. Defaults to "everything above the target".
    offer_ordinals: tuple[int, ...] | None = None
    # Overrides the pin the caller passes. None means "the target's real head";
    # False means "no pin at all"; a dict is used verbatim.
    pin: Any = None
    notes: dict[str, Any] = field(default_factory=dict)


CASES: tuple[Case, ...] = (
    # --- family 1: the exact suffix ---------------------------------------
    Case(
        name="replicate-exact-suffix-single-record-accepted",
        description=(
            "One pre-coordinated record that follows the target's head lands "
            "unchanged: replication validates the coordinate it was handed and "
            "assigns nothing (§08 exact replication)."
        ),
        target=(note(1), note(2)),
        offered=(note(1), note(2), note(3)),
        offer_ordinals=(3,),
    ),
    Case(
        name="replicate-exact-suffix-batch-lands-whole",
        description=(
            "A multi-record suffix commits under one head compare and one "
            "durability step; the replica ends byte-identical to the authority "
            "it caught up with."
        ),
        target=(note(1),),
        offered=(note(1), note(2), note(3), note(4)),
        offer_ordinals=(2, 3, 4),
    ),
    Case(
        name="replicate-exact-suffix-refuses-a-gap-above-the-head",
        description=(
            "A batch that starts above head+1 is not a suffix. The head is "
            "intact, so this is a stale view of it and not a fork: HeadMismatch, "
            "and the caller re-reads to find what it is missing."
        ),
        target=(note(1), note(2)),
        offered=(note(1), note(2), note(3), note(4)),
        offer_ordinals=(4,),
    ),
    Case(
        name="replicate-exact-suffix-refuses-a-stale-full-head-pin",
        description=(
            "The compare-and-swap pin is the FULL head. A pin carrying the right "
            "ordinal and a different record hash refuses before any mutation — "
            "the rollback §11 asks backends to detect, which an ordinal-only "
            "compare cannot see."
        ),
        target=(note(1), note(2)),
        offered=(note(1), note(2), note(3)),
        offer_ordinals=(3,),
        pin={"ordinal": 2, "record_hash": "0" * 64},
    ),
    # --- family 2: the same-height fork ------------------------------------
    Case(
        name="replicate-same-height-fork-at-the-head-refuses",
        description=(
            "A record offered at the ordinal the target's head occupies, with a "
            "different record hash, is a fork: the two histories disagree about "
            "what happened at that height. Replication stops rather than "
            "choosing, because choosing is admission into another lineage."
        ),
        target=(note(1), note(2), Rec(k="note", body={"tail": "authority"}, at=1750000200.0)),
        offered=(note(1), note(2), Rec(k="note", body={"tail": "DIVERGENT"}, at=1750000200.0)),
        offer_ordinals=(3,),
    ),
    Case(
        name="replicate-same-height-fork-below-the-head-refuses",
        description=(
            "The fork check reaches below the head, not only at it: a batch "
            "overlapping an interior ordinal with different content refuses "
            "naming that ordinal, so the refusal is a location claim."
        ),
        target=(note(1), Rec(k="note", body={"at2": "authority"}, at=1750000200.0), note(3), note(4)),
        offered=(note(1), Rec(k="note", body={"at2": "DIVERGENT"}, at=1750000200.0), note(3)),
        offer_ordinals=(2, 3),
    ),
    Case(
        name="replicate-same-height-agreement-is-not-a-fork",
        description=(
            "The negative control. A record offered at an occupied height whose "
            "record hash AGREES is a stale re-send, not a fork — retrying after a "
            "re-read fixes it, so it refuses as HeadMismatch. A fork refusal that "
            "fired here would have stopped meaning fork."
        ),
        target=(note(1), note(2), note(3)),
        offered=(note(1), note(2), note(3)),
        offer_ordinals=(3,),
    ),
    # --- family 3: stale-replica catch-up, byte for byte -------------------
    Case(
        name="replicate-catch-up-preserves-signed-records-byte-for-byte",
        description=(
            "A replica three records behind is brought forward with SIGNED "
            "records and ends byte-identical to the authority. The signature is "
            "the discriminator: an implementation that re-coordinated the suffix "
            "would rebuild each record without it, and every record hash from "
            "that height on would change."
        ),
        target=(note(1, signed=True),),
        offered=(
            note(1, signed=True),
            note(2, signed=True),
            note(3, signed=True),
            note(4, signed=True),
        ),
        offer_ordinals=(2, 3, 4),
    ),
    Case(
        name="replicate-catch-up-preserves-authored-time-and-origin",
        description=(
            "Authored time and origin are the record author's, not the replica's. "
            "A suffix carrying times far from any clock the replica would stamp, "
            "and a non-empty origin, lands with both intact."
        ),
        target=(note(1),),
        offered=(
            note(1),
            Rec(k="note", body={"i": 2}, at=1000000000.5, origin="alcove"),
            Rec(k="note", body={"i": 3}, at=2000000000.25, origin="terra"),
        ),
        offer_ordinals=(2, 3),
    ),
    Case(
        name="replicate-catch-up-from-a-genesis-only-replica",
        description=(
            "The widest catch-up a replica can take without an import: it holds "
            "only the genesis it was opened on, and the whole remaining history "
            "arrives as one suffix."
        ),
        target=(),
        offered=(note(1, signed=True), note(2), note(3, origin="alcove")),
        offer_ordinals=(1, 2, 3),
    ),
)


def generate_replicate_vectors() -> None:
    REPLICATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for index, case in enumerate(CASES):
            target_log = build_log(root / f"{index}-target.arrival", case.target)
            authority_log = build_log(root / f"{index}-authority.arrival", case.offered)

            ordinals = case.offer_ordinals or tuple(
                range(target_log.head()["ord"] + 1, authority_log.head()["ord"] + 1)
            )
            offered = [authority_log.read(ordinal) for ordinal in ordinals]

            if case.pin is None:
                pin = Head(**head_dict(target_log))
            elif case.pin is False:
                pin = None
            else:
                pin = Head(
                    lineage=case.pin.get("lineage", LINEAGE),
                    ordinal=case.pin["ordinal"],
                    record_hash=case.pin["record_hash"],
                )

            # Snapshotted BEFORE the operation: for an accepted vector the file
            # is about to change, and `input.target` must state what the target
            # held going in.
            target_lines = lines_of(target_log.path)

            ledger = FileLedger(ArrivalLog(target_log.path))
            outcome, refusal = "accepted", None
            try:
                ledger.replicate(pin, offered)
            except SameHeightFork:
                outcome, refusal = "refused", "SameHeightFork"
            except HeadMismatch:
                outcome, refusal = "refused", "HeadMismatch"

            vector = {
                "name": case.name,
                "description": case.description,
                "input": {
                    "target": target_lines,
                    "records": offered,
                    "expected_head": None if pin is None else {
                        "lineage": pin.lineage,
                        "ordinal": pin.ordinal,
                        "record_hash": pin.record_hash,
                    },
                },
                "expected": {
                    "outcome": outcome,
                    "refusal": refusal,
                    "head": head_dict(ArrivalLog(target_log.path)),
                    "log": lines_of(target_log.path),
                },
            }

            out_path = REPLICATE_DIR / f"{case.name}.json"
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(vector, fh, indent=2)
                fh.write("\n")
            print(f"Wrote {out_path.relative_to(REPO_ROOT)} ({outcome})")


if __name__ == "__main__":
    generate_replicate_vectors()
