"""Independent gate oracle for cut A — G1 + G2, written from scratch.

Scenario deliberately different from the implementer's test:
  ord 0 genesis (kaygee, key K1)
  ord 1 fact kaygee (K1)
  ord 2 key introduction: beto/B1, signed kaygee
  ord 3 fact beto (B1)
  ord 4 fact kaygee (K1)
  ord 5 declaration absorb (movement 2)
  ord 6 key introduction: kaygee/K2 (second key for the SAME observer)
  ord 7 fact kaygee signed with K2 (multi-candidate resolution)
  ord 8 seal tick

Then every projection is deleted (including a decoy .jsonl planted first),
and every answer is produced by a FRESH subprocess chdir'd into an empty
directory that receives only the .arrival path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from atoms import Fact
from lang import parse_vertex
from lang.document import vertex_to_documents
from sign import ed25519

from engine.arrival import KEY_INTRODUCTION_KIND, ArrivalLog, AuthorshipUnverified, verify_authorship
from engine.arrival_store import ArrivalStore
from engine.residence import sqlite_sidecars
from engine.tick import Tick

DOMAIN = "gate-a-v1"

VERTEX = 'name "g"\nstore "./g.arrival"\nloops {\n  a { fold { n "inc" } }\n}\n'


class Holder:
    def __init__(self, root: Path, name: str, slot: str) -> None:
        self.kp = ed25519.load_or_generate(root / "keys" / slot)
        self.public = self.kp.public_b64
        self.name = name

    def signer(self, observer: str, digest: str):
        return ed25519.sign(self.kp, digest.encode(), domain=DOMAIN)


def verify(key_b64: str, signature: str, digest: str) -> bool:
    try:
        pub = ed25519.public_key_from_b64(key_b64)
    except ValueError:
        return False
    return ed25519.verify(pub, signature, digest.encode(), domain=DOMAIN)


def build(root: Path) -> tuple[Path, dict]:
    k1 = Holder(root, "kaygee", "k1")
    k2 = Holder(root, "kaygee", "k2")
    b1 = Holder(root, "beto", "b1")

    log = ArrivalLog.mint(root / "g.arrival", observer="kaygee", signer=k1.signer, key=k1.public)

    active = {"kaygee": k1, "beto": b1}

    def store_signer(observer: str, digest: str):
        h = active.get(observer)
        return h.signer(observer, digest) if h else None

    store: ArrivalStore = ArrivalStore(
        path=root / "g.db",
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
        fact_signer=store_signer,
    )
    try:
        store.append(Fact.of("note", "kaygee", message="alpha"))                     # 1
        intro_b = log.append(KEY_INTRODUCTION_KIND, {"observer": "beto", "key": b1.public},
                             observer="kaygee", signer=k1.signer)                    # 2
        store.append(Fact.of("note", "beto", message="bravo"))                       # 3
        store.append(Fact.of("note", "kaygee", message="charlie"))                   # 4
        docs = [d.as_json() for d in vertex_to_documents(parse_vertex(VERTEX))]
        store.absorb_genesis(docs, observer="kaygee", fact_signer=store_signer)      # 5
        intro_k2 = log.append(KEY_INTRODUCTION_KIND, {"observer": "kaygee", "key": k2.public},
                              observer="kaygee", signer=k1.signer)                   # 6
        active["kaygee"] = k2  # kaygee rotates to the new key
        store.append(Fact.of("note", "kaygee", message="delta"))                     # 7
        store.append_tick(Tick(name="seal", ts=datetime.now(UTC), payload={"n": 4}, origin="g"))  # 8

        # sanity while projections still exist: sqlite own_lineage agrees
        row = store._conn.execute("SELECT value FROM store_meta WHERE key='own_lineage'").fetchone()
        assert row and row[0] == log.lineage(), "sqlite own_lineage != arrival lineage"
    finally:
        store.close()

    # decoy legacy projection, then delete EVERY projection
    (root / "g.jsonl").write_text('{"decoy": true}\n')
    index = root / "g.db"
    for p in (index, *sqlite_sidecars(index), root / "g.jsonl"):
        p.unlink(missing_ok=True)
    left = sorted(p.name for p in root.iterdir() if p.is_file())
    assert left == ["g.arrival"] or left == ["g.arrival", "g.arrival.lock"], left

    keys = {"k1": k1.public, "k2": k2.public, "b1": b1.public,
            "intro_b": intro_b["ord"], "intro_k2": intro_k2["ord"]}
    return root / "g.arrival", keys


ANSWER = r'''
import json, os, sys
from pathlib import Path
# chdir-isolated: empty cwd, nothing to consult but the handed path.
assert list(Path.cwd().iterdir()) == [], "answer cwd is not empty"
from sign import ed25519
from engine.arrival import ArrivalLog, verify_authorship

DOMAIN = "gate-a-v1"
def verify(key_b64, signature, digest):
    try:
        pub = ed25519.public_key_from_b64(key_b64)
    except ValueError:
        return False
    return ed25519.verify(pub, signature, digest.encode(), domain=DOMAIN)

log_path, meta_json = sys.argv[1], sys.argv[2]
meta = json.loads(meta_json)
log = ArrivalLog(Path(log_path))

records = list(log.walk())          # the walk IS the integrity statement
lineage = log.lineage()

# G1 identity: every record in one lineage; own_lineage re-derivable
assert all(r["lin"] == lineage for r in records)
decl = [r for r in records
        if r["k"] == "fact" and r["body"].get("kind") == "_decl.genesis"]
assert len(decl) == 1
assert decl[0]["body"]["id"] == lineage, "own_lineage not derivable from log"
payload = json.loads(decl[0]["body"]["payload"])
assert set(payload) == {"protocol", "documents"}, f"era pins present: {set(payload)}"

# G1 ordering: dense from 0
assert [r["ord"] for r in records] == list(range(len(records)))

# G1 records
kinds = [r["k"] for r in records]
assert kinds == ["genesis", "fact", "key", "fact", "fact", "fact", "key", "fact", "tick"], kinds
msgs = [json.loads(r["body"]["payload"]).get("message")
        for r in records if r["k"] == "fact" and r["body"].get("kind") == "note"]
assert msgs == ["alpha", "bravo", "charlie", "delta"], msgs
assert records[-1]["body"]["t"] == "tick"

# G1/G2 authorship: every signature verifies from the log alone
rows = verify_authorship(log, verify)
signed = [r["ord"] for r in records if "sig" in r]
assert [r.ordinal for r in rows] == signed and signed

# G2 exclusivity trace: (key, lineage, ordinal); keys live AT the coordinates
trace = sorted({(r.key, r.introduced_lineage, r.introduced_ordinal) for r in rows})
expect = sorted({
    (meta["k1"], lineage, 0),
    (meta["b1"], lineage, meta["intro_b"]),
    (meta["k2"], lineage, meta["intro_k2"]),
})
assert trace == expect, (trace, expect)
assert log.read(0)["body"]["key"] == meta["k1"]
assert log.read(meta["intro_b"])["body"]["key"] == meta["b1"]
assert log.read(meta["intro_k2"])["body"]["key"] == meta["k2"]
# the ord-7 fact verified under K2, introduced at intro_k2 -- multi-key resolution
r7 = [r for r in rows if r.ordinal == 7]
assert r7 and r7[0].key == meta["k2"] and r7[0].introduced_ordinal == meta["intro_k2"]
print("G1G2-ANSWER-OK trace:")
for r in rows:
    print(f"  ord={r.ordinal:>2} observer={r.observer:<8} key={r.key[:16]}... <- ({r.introduced_lineage[:8]}..., {r.introduced_ordinal})")
'''


def adversarial(root: Path) -> None:
    k = Holder(root, "kyle", "ak")
    a = Holder(root, "ana", "aa")

    # A: record by an observer BEFORE their key introduction (< N) refuses
    d = root / "advA"; d.mkdir()
    log = ArrivalLog.mint(d / "s.arrival", observer="kyle", signer=k.signer, key=k.public)
    log.append("note", {"m": 1}, observer="ana", signer=a.signer)           # ord 1, ana not introduced
    log.append(KEY_INTRODUCTION_KIND, {"observer": "ana", "key": a.public},
               observer="kyle", signer=k.signer)                             # ord 2
    try:
        verify_authorship(log, verify)
        raise AssertionError("A: record before introduction verified")
    except AuthorshipUnverified as e:
        assert e.ordinal == 1, e.ordinal
        print("ADV-A ok: pre-introduction record refused at ordinal 1")

    # B: introduction signed by the not-yet-valid key itself (self-cert at N) refuses
    d = root / "advB"; d.mkdir()
    log = ArrivalLog.mint(d / "s.arrival", observer="kyle", signer=k.signer, key=k.public)
    log.append(KEY_INTRODUCTION_KIND, {"observer": "ana", "key": a.public},
               observer="ana", signer=a.signer)                              # ord 1, self-cert
    try:
        verify_authorship(log, verify)
        raise AssertionError("B: self-certifying introduction verified")
    except AuthorshipUnverified as e:
        assert e.ordinal == 1, e.ordinal
        print("ADV-B ok: self-certification above ordinal 0 refused")

    # C: genesis signed by a key other than its own body key refuses at 0
    d = root / "advC"; d.mkdir()
    log = ArrivalLog.mint(d / "s.arrival", observer="kyle", signer=k.signer, key=a.public)
    try:
        verify_authorship(log, verify)
        raise AssertionError("C: mismatched genesis verified")
    except AuthorshipUnverified as e:
        assert e.ordinal == 0, e.ordinal
        print("ADV-C ok: genesis not self-certifying refused at ordinal 0")

    # D: a record AT the introduction ordinal cannot use the introduced key --
    # covered by B (the introduction IS the record at N); additionally a
    # record signed by ana at N+... under kyle's observer must refuse
    d = root / "advD"; d.mkdir()
    log = ArrivalLog.mint(d / "s.arrival", observer="kyle", signer=k.signer, key=k.public)
    log.append(KEY_INTRODUCTION_KIND, {"observer": "ana", "key": a.public},
               observer="kyle", signer=k.signer)                             # ord 1
    log.append("note", {"m": 2}, observer="kyle", signer=a.signer)           # ord 2: kyle record, ana's sig
    try:
        verify_authorship(log, verify)
        raise AssertionError("D: cross-observer key verified")
    except AuthorshipUnverified as e:
        assert e.ordinal == 2, e.ordinal
        print("ADV-D ok: observer binding holds (another observer's key refused)")


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        log_path, meta = build(root / "store")
        answer_dir = root / "empty"
        answer_dir.mkdir()
        script = root / "answer.py"
        script.write_text(ANSWER)
        r = subprocess.run([sys.executable, str(script), str(log_path), json.dumps(meta)],
                           cwd=answer_dir, capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        assert r.returncode == 0, "answer subprocess failed"
        adversarial(root / "adv")
    print("GATE-G1-G2-OK")


if __name__ == "__main__":
    Path.mkdir  # no-op
    main()
