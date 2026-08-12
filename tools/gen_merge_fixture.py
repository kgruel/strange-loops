#!/usr/bin/env python3
"""Generate the merge-commutativity differential fixture (SPEC §6.2).

The property: merge(A, B) and merge(B, A) must re-fold to the SAME derived
state. Both merge directions lay out different SQLite rowids (insertion order),
but every fact keeps its (ts, id) verbatim, so replaying in (ts, id) order is
merge-commutative. The order-sensitive folds (Collect, Window, Upsert-overwrite)
are exactly the ones that diverge under the incumbent's ORDER BY rowid replay —
this fixture pins the fix-both.

Reference: libs/store/tests/test_merge.py::TestMergeFoldCommutativity and
decision design/fold-replay-order-event-time (loops 14eb723).

Produces two real merged DBs (ab.db = A<-B, ba.db = B<-A) and the Python-replayed
expected state. The Go side reads BOTH DBs through its (ts, id) replay path
(store.Payloads) and must reproduce the identical state from each — a true
differential merge case, even though Go has no merge primitive of its own yet.

Run:  uv run python tools/gen_merge_fixture.py --loops-go ~/Code/loops-go
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _conformance import (
    add_destination_arg,
    loops_commit,
    testdata_dir,
    unlink_store,
)

from atoms import Collect, Field, Spec, Upsert, Window
from engine.sqlite_store import SqliteStore
from store.merge import merge_store

GENERATED_BY = "loops:tools/gen_merge_fixture.py"

KIND = "event"

# Two independently-emitted fact sets whose ts values INTERLEAVE, so neither
# physical merge order matches (ts, id) order. Order-sensitive folds will only
# agree across merge directions if replay honors (ts, id).
#  ts:   0      1      2      3
#  A:   a0            a2
#  B:          b0            b1
A_FACTS = [(1000.0, {"id": "x", "tag": "a0", "note": "first"}),
           (1002.0, {"id": "x", "tag": "a2"})]
B_FACTS = [(1001.0, {"id": "x", "tag": "b0"}),
           (1003.0, {"id": "y", "tag": "b1"})]

# Order-sensitive folds (FINDINGS §2): Collect (append order), Window (FIFO),
# Upsert field-overwrite (last-write-wins).
FOLDS = [
    dict(op="collect", target="log"),
    dict(op="window", target="tags", field="tag", size=3),
    dict(op="upsert", target="entities", key="id"),
]


def build_fold(d):
    op = d["op"]
    if op == "collect": return Collect(target=d["target"], max=d.get("max", 0))
    if op == "window":  return Window(target=d["target"], field=d["field"], size=d["size"])
    if op == "upsert":  return Upsert(target=d["target"], key=d["key"])
    raise ValueError(op)


def _emit(path: Path, facts, start_idx: int):
    unlink_store(path)
    store = SqliteStore(path=path, serialize=lambda d: d, deserialize=lambda d: d)
    # Deterministic ids: A facts FIXA…, B facts FIXB… — distinct id spaces so
    # merge dedups nothing and (ts, id) is total.
    for i, (ts, payload) in enumerate(facts):
        prefix = "FIXA" if start_idx == 0 else "FIXB"
        fid = f"{prefix}{i:022d}"
        store.append({"kind": KIND, "ts": ts, "observer": "fixture",
                      "origin": "", "payload": payload}, id_override=fid)
    store.close()


def _replay_payloads(path: Path):
    """Replay via the production raw path — (ts, id) order, _ts injected."""
    store = SqliteStore(path=path, serialize=lambda d: d, deserialize=lambda d: d)
    out = [p for _, p in store.since_raw(0)]
    store.close()
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_destination_arg(parser)
    args = parser.parse_args()
    out = testdata_dir(args.loops_go, "stores")

    a_ab, b_ab = out / "_merge_a_ab.db", out / "_merge_b_ab.db"
    a_ba, b_ba = out / "_merge_a_ba.db", out / "_merge_b_ba.db"

    _emit(a_ab, A_FACTS, 0)
    _emit(b_ab, B_FACTS, 1)
    _emit(a_ba, A_FACTS, 0)
    _emit(b_ba, B_FACTS, 1)

    merge_store(a_ab, b_ab)  # ab.db  = A <- B
    merge_store(b_ba, a_ba)  # ba.db  = B <- A

    ab = out / "merge_ab.db"
    ba = out / "merge_ba.db"
    for src, dst in ((a_ab, ab), (b_ba, ba)):
        unlink_store(dst)
        Path(src).rename(dst)
    # clean leftover source dbs
    for p in (b_ab, a_ba):
        unlink_store(p)

    # state_fields seed the container identities (§6.1) — the incumbent's
    # Collect/Upsert raise KeyError on an unseeded target (FINDINGS R4); the Go
    # impl is nil-safe and seeds from STATE_FIELDS too, so parity holds.
    state_fields = (Field(name="log", kind="list"),
                    Field(name="tags", kind="list"),
                    Field(name="entities", kind="dict"))
    spec = Spec(name="merge", state_fields=state_fields,
                folds=tuple(build_fold(f) for f in FOLDS))
    payloads_ab = _replay_payloads(ab)
    payloads_ba = _replay_payloads(ba)
    expected = spec.replay(payloads_ab)
    expected_ba = spec.replay(payloads_ba)
    assert expected == expected_ba, (
        f"merge not commutative even in Python: {expected} != {expected_ba}")

    meta = {
        "python_commit": loops_commit(),
        "generated_by": GENERATED_BY,
        "dbs": ["merge_ab.db", "merge_ba.db"],
        "kind": KIND,
        "note": "merge(A,B) and merge(B,A) re-fold identically under (ts,id) replay (SPEC §6.2).",
        "folds": FOLDS,
        "state_fields": [{"name": f.name, "kind": f.kind} for f in state_fields],
        "expected": expected,
    }
    (out / "merge.expected.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote merge_ab.db, merge_ba.db + merge.expected.json @ {meta['python_commit'][:9]}")
    print("expected:", json.dumps(expected, ensure_ascii=False))


if __name__ == "__main__":
    main()
