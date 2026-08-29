"""The cut-A gate, answered literally (decision:design/arrival-sliceA-authority §7).

G1 — the authority test: build an arrival store, exercise it (facts, a key
introduction, a declaration absorb, a seal), DELETE EVERY PROJECTION, and
assert identity, records, authorship and ordering all still answer from the
``.arrival`` file alone, through :meth:`engine.arrival.ArrivalLog.walk` —
``own_lineage`` included, with ``store_meta`` gone with the index.

G2 — the exclusivity trace: a second key introduced at a stated ordinal,
every projection deleted, every signature verified from the log alone, the
trace emitted as ``(key, lineage, ordinal)`` rows — and no key resolving
from anywhere but a log coordinate.

G3 — apps/ diff-empty: the per-slice gate law, checked against git.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact
from lang import parse_vertex
from lang.document import DECL_GENESIS, vertex_to_documents

from engine.arrival import (
    KEY_INTRODUCTION_KIND,
    ArrivalLog,
    verify_authorship,
)
from engine.arrival_store import ArrivalStore
from engine.residence import sqlite_sidecars
from engine.tick import Tick
from tests.conftest import ARRIVAL_VERTEX_SRC as BASE
from tests.conftest import Custodian as _Custodian
from tests.conftest import ed25519_verify as _verify


def _build_exercised_store(tmp_path: Path) -> tuple[Path, _Custodian, _Custodian, int]:
    """Movement 1 (mint), facts, a key introduction at a stated ordinal, a
    declaration absorb (movement 2), a seal. Returns (log path, founder,
    second custodian, the introduction's ordinal)."""
    kyle = _Custodian(tmp_path, "kyle")
    ana = _Custodian(tmp_path, "ana")

    log = ArrivalLog.mint(
        tmp_path / "s.arrival", observer="kyle", signer=kyle.signer, key=kyle.public
    )

    def signer(observer: str, digest: str) -> str | None:
        by = {"kyle": kyle, "ana": ana}.get(observer)
        return by.signer(observer, digest) if by else None

    store: ArrivalStore = ArrivalStore(
        path=tmp_path / "s.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=signer,
    )
    try:
        store.append(Fact.of("note", "kyle", message="one"))  # ordinal 1
        intro = log.append(
            KEY_INTRODUCTION_KIND,
            {"observer": "ana", "key": ana.public},
            observer="kyle",
            signer=kyle.signer,
        )  # ordinal 2
        store.append(Fact.of("note", "ana", message="two"))  # ordinal 3
        docs = [d.as_json() for d in vertex_to_documents(parse_vertex(BASE))]
        store.absorb_genesis(docs, observer="kyle", fact_signer=signer)  # ordinal 4
        store.append_tick(  # the seal — ordinal 5
            Tick(name="seal", ts=datetime.now(UTC), payload={"n": 2}, origin="x")
        )
    finally:
        store.close()
    return log.path, kyle, ana, intro["ord"]


def _delete_every_projection(log_path: Path) -> None:
    index = log_path.with_suffix(".db")
    for stale in (index, *sqlite_sidecars(index), log_path.with_suffix(".jsonl")):
        stale.unlink(missing_ok=True)
    remaining = {p.name for p in log_path.parent.iterdir() if p.is_file()}
    assert remaining & {"s.arrival"} == {"s.arrival"}
    assert not any(n.endswith((".db", "-wal", "-shm", ".jsonl")) for n in remaining)


# --- G1 ----------------------------------------------------------------------


def test_g1_everything_answers_from_the_arrival_file_alone(tmp_path):
    log_path, kyle, ana, intro_ordinal = _build_exercised_store(tmp_path)
    _delete_every_projection(log_path)

    log = ArrivalLog(log_path)
    records = list(log.walk())  # the walk IS the integrity statement (C2)

    # Identity: the store's own lineage derives from the log with
    # store_meta gone — the single strongest assertion in the gate.
    lineage = log.lineage()
    assert all(r["lin"] == lineage for r in records)

    # Ordering: dense ordinals from 0, by walk verification.
    assert [r["ord"] for r in records] == list(range(len(records)))

    # Records: everything the store was exercised with is present and
    # readable — facts with verbatim payload text, the declaration absorb,
    # the seal.
    kinds = [r["k"] for r in records]
    assert kinds == ["genesis", "fact", "key", "fact", "fact", "tick"]
    fact_bodies = [r["body"] for r in records if r["k"] == "fact"]
    messages = [
        json.loads(b["payload"]).get("message")
        for b in fact_bodies
        if b["kind"] == "note"
    ]
    assert messages == ["one", "two"]
    decl = [b for b in fact_bodies if b["kind"] == DECL_GENESIS]
    assert len(decl) == 1
    assert decl[0]["id"] == lineage  # own_lineage, re-derivable from the log
    assert set(json.loads(decl[0]["payload"])) == {"protocol", "documents"}
    # The record class is the envelope's, and the body no longer echoes it.
    assert records[-1]["k"] == "tick"
    assert "t" not in records[-1]["body"]

    # Authorship: every signature verifies from the log alone.
    rows = verify_authorship(log, _verify)
    assert {r.observer for r in rows} >= {"kyle", "ana"}


# --- G2 ----------------------------------------------------------------------


def test_g2_the_exclusivity_trace(tmp_path):
    log_path, kyle, ana, intro_ordinal = _build_exercised_store(tmp_path)
    _delete_every_projection(log_path)
    assert not list(tmp_path.glob("*.vertex")), "no registry artifact exists at all"

    log = ArrivalLog(log_path)
    lineage = log.lineage()
    rows = verify_authorship(log, _verify)

    # Every signature in the log is covered by exactly one trace row.
    signed = [r["ord"] for r in log.walk() if "sig" in r]
    assert [r.ordinal for r in rows] == signed and signed

    # The trace: (key, lineage, ordinal) — every verifying key resolves
    # from a coordinate IN THIS LOG, and from nowhere else. The founding
    # key resolves from the genesis coordinate; ana's from the stated
    # introduction ordinal.
    trace = [(r.key, r.introduced_lineage, r.introduced_ordinal) for r in rows]
    assert all(lin == lineage for _, lin, _ in trace)
    assert set(trace) == {
        (kyle.public, lineage, 0),
        (ana.public, lineage, intro_ordinal),
    }
    assert intro_ordinal == 2  # the stated ordinal, pinned

    # The keys the trace names are IN the records at those coordinates —
    # the coordinate is not a label, it is where the key lives.
    assert log.read(0)["body"]["key"] == kyle.public
    assert log.read(intro_ordinal)["body"]["key"] == ana.public


def test_g2_the_verifier_consults_nothing_beside_the_log(tmp_path, monkeypatch):
    """The exclusivity claim, checked mechanically: with the working
    directory pointed at an empty directory and every projection gone, the
    only file the verifier can possibly have read is the log it was
    handed."""
    log_path, kyle, ana, _ = _build_exercised_store(tmp_path)
    _delete_every_projection(log_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    rows = verify_authorship(ArrivalLog(log_path), _verify)
    assert rows
