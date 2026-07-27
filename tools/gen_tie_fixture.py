#!/usr/bin/env python3
"""Generate the same-`ts` id tie-break fixture (SPEC §4.6 / §6.2) — vector
family 3 of the loops-go protocol queue.

SPEC §4.6 pre-authorized this: *"The conformance corpus contains no ties yet,
so the differential oracle does not catch it; a tie vector should be added once
§6.2 is frozen."* §6.2 froze at d865954.

WHY A STORE FIXTURE AND NOT A FOLD VECTOR. The fold-vector JSON schema is
`{name, folds, initial, payloads, expected}` — no ids, no store, no time axis;
the Go harness applies payloads in ARRAY order, so ordering is an input to
those vectors and never something they test. SPEC §6.2 says so outright: *"A
pure-atoms tie vector ... adding it to the id-less fold vectors would have no
replay-order step to exercise."* A `.db` carries ids, and the Go reader's
`ORDER BY ts, id` (`store/sqlite.go`) is the code under test. So the tie-break
is only exercisable in the store-fixture artifact class.

THE CONSTRUCTION. Every fact but one shares one `ts`, and the ULID ids run
AGAINST insertion order, so witness order (rowid) and event order `(ts, id)`
disagree on every row — the axis-discrimination M1's `proc.db` deliberately
lacks (there, ts and id both ascend with insertion, so all three orders
coincide). One row sits at a lower `ts` but the HIGHEST id and the LAST rowid,
pinning `ts` as primary and `id` as the tie-break rather than the sort key.

    rowid   id slot   ts       pid  score  tag   (ts, id) replay position
      1     0TBREAKE  1000.0    z     50   z2            5
      2     0TBREAKC  1000.0    x     50   x             4
      3     0TBREAKB  1000.0    y     50   y             3
      4     0TBREAKA  1000.0    z     50   z             2
      5     0TBREAKD   999.0    w     10   w             1

(ids shown to their ordering character; each is padded with zeros to the
26-char ULID width — see `_ID_PREFIX`.)

Four folds read that order, each failing differently under a wrong one:

* `TopN(n=2, by=score, desc)` — three keys tied at score 50. Python evicts by
  insertion order into an ordered dict under a STABLE sort, i.e. by `(ts, id)`
  arrival; an implementation tie-breaking by key string keeps `{x, y}` where
  `(ts, id)` keeps `{z, y}`. This is FINDINGS §3's "concrete fix-both", and it
  is the reason this fixture exists.
* `Upsert(key=pid)` — `z` is written twice at the SAME `ts`; last-write-wins is
  decided by `id`. Replay by rowid gives `z` the wrong payload.
* `Collect` and `Window` — order-sensitive by construction; they make a
  wrong replay order visible as a sequence, not just a set.

The fixture ships BOTH answers: `expected` (the correct `(ts, id)` replay) and
`expected_rowid_order` (what a rowid-replaying implementation produces). The Go
test asserts it matches the first and DIFFERS from the second — a negative
control, so the vector cannot quietly decay into a tautology if the fixture is
ever regenerated with an order-blind table.

Run:  uv run python tools/gen_tie_fixture.py --loops-go ~/Code/loops-go
"""

from __future__ import annotations

import argparse
import json

from _conformance import (
    add_destination_arg,
    fixture_ulid,
    loops_commit,
    testdata_dir,
    unlink_store,
)

from atoms import Collect, Fact, Field, Spec, TopN, Upsert, Window
from engine.sqlite_store import SqliteStore

GENERATED_BY = "loops:tools/gen_tie_fixture.py"

KIND = "score"

TS_TIED = 1000.0
TS_EARLY = 999.0


#: Crockford base32 excludes I, L, O and U, so "TIEBREAK" is unspellable as a
#: ULID prefix — "TBREAK" is the closest legal reading. The leading "0" keeps
#: the 48-bit millisecond timestamp in range (a "T…" prefix overflows it).
#: `fixture_ulid` enforces both constraints; see its docstring for why this
#: matters even though nothing in the current corpus validates ids.
_ID_PREFIX = "0TBREAK"


def _fid(slot: str) -> str:
    """A 26-char deterministic ULID whose lexicographic rank is `slot`.

    Ids are TEXT and both implementations order them as strings, so a single
    ordering letter is the whole tie-break signal — the rest is padding to the
    ULID width.
    """
    return fixture_ulid(_ID_PREFIX, slot)


# In ROWID (insertion) order. The `slot` letter fixes (ts, id) order; note it
# runs backwards relative to this list, which is the point.
ROWS = [
    ("E", TS_TIED, {"pid": "z", "score": 50, "tag": "z2", "note": "later"}),
    ("C", TS_TIED, {"pid": "x", "score": 50, "tag": "x"}),
    ("B", TS_TIED, {"pid": "y", "score": 50, "tag": "y"}),
    ("A", TS_TIED, {"pid": "z", "score": 50, "tag": "z", "note": "first"}),
    ("D", TS_EARLY, {"pid": "w", "score": 10, "tag": "w"}),
]

FOLDS = [
    dict(op="topn", target="top", key="pid", by="score", n=2, desc=True),
    dict(op="upsert", target="entities", key="pid"),
    dict(op="collect", target="log"),
    dict(op="window", target="tags", field="tag", size=3),
]

STATE_FIELDS = [
    ("top", "dict"), ("entities", "dict"), ("log", "list"), ("tags", "list"),
]


def build_fold(d):
    op = d["op"]
    if op == "topn":    return TopN(target=d["target"], key=d["key"], by=d["by"], n=d["n"], desc=d.get("desc", True))
    if op == "upsert":  return Upsert(target=d["target"], key=d["key"])
    if op == "collect": return Collect(target=d["target"], max=d.get("max", 0))
    if op == "window":  return Window(target=d["target"], field=d["field"], size=d["size"])
    raise ValueError(op)


def _payload(slot: str, ts: float, body: dict) -> dict:
    """The stored payload, with `_ts` carried the way the read path injects it."""
    return {**body, "_ts": ts}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_destination_arg(parser)
    args = parser.parse_args()
    out = testdata_dir(args.loops_go, "stores")

    db_path = out / "tie.db"
    unlink_store(db_path)

    spec = Spec(
        name="tie_break",
        state_fields=tuple(Field(name=n, kind=k) for n, k in STATE_FIELDS),
        folds=tuple(build_fold(f) for f in FOLDS),
    )

    store = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
    for slot, ts, body in ROWS:
        payload = _payload(slot, ts, body)
        store.append(Fact(kind=KIND, ts=ts, payload=payload, observer="fixture"),
                     id_override=_fid(slot))
    store.close()

    by_rowid = [_payload(slot, ts, body) for slot, ts, body in ROWS]
    by_event = [_payload(slot, ts, body)
                for slot, ts, body in sorted(ROWS, key=lambda r: (r[1], _fid(r[0])))]

    # The whole fixture is worthless if the two orders coincide.
    assert by_rowid != by_event, "fixture does not discriminate rowid from (ts, id)"

    # Read-back: the production replay path must hand back `by_event`. This is
    # what the Go reader's `ORDER BY ts, id` has to reproduce, so if this
    # assertion ever fails the fixture is pinning the wrong order, not the Go
    # side failing to meet it.
    rb = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
    read_back = [p for _, p in rb.since_raw(0)]
    rb.close()
    assert read_back == by_event, (
        f"since_raw is not in (ts, id) order:\n{read_back}\n{by_event}")

    expected = spec.replay(by_event)
    expected_rowid = spec.replay(by_rowid)
    assert expected != expected_rowid, (
        "the trap does not spring: rowid replay agrees with (ts, id) replay")

    # State the §4.6 tie-break outcome as its own assertion, so a future edit
    # that keeps the states distinct but stops exercising the TopN tie is
    # caught here rather than silently weakening the vector.
    assert set(expected["top"]) == {"z", "y"}, expected["top"]
    assert set(expected_rowid["top"]) == {"z", "x"}, expected_rowid["top"]
    assert expected["entities"]["z"]["tag"] == "z2", expected["entities"]["z"]

    meta = {
        "python_commit": loops_commit(),
        "generated_by": GENERATED_BY,
        "db": "tie.db",
        "kind": KIND,
        "spec_ref": "SPEC §4.6 (TopN tie-break) resolved by §6.2 ((ts, id) replay order)",
        "note": (
            "Same-ts id tie-break. Ids run against rowid order, so replaying by "
            "rowid — or tie-breaking TopN by key string, or sorting unstably — "
            "yields expected_rowid_order instead of expected."
        ),
        "rowid_order": [_fid(slot) for slot, _, _ in ROWS],
        "event_order": [_fid(slot) for slot, _, _ in sorted(ROWS, key=lambda r: (r[1], _fid(r[0])))],
        "folds": FOLDS,
        "state_fields": [{"name": n, "kind": k} for n, k in STATE_FIELDS],
        "expected": expected,
        "expected_rowid_order": expected_rowid,
    }
    (out / "tie.expected.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote tie.db ({len(ROWS)} facts) + tie.expected.json @ {meta['python_commit'][:9]}")
    print("expected      :", json.dumps(expected, ensure_ascii=False))
    print("rowid-order   :", json.dumps(expected_rowid, ensure_ascii=False))


if __name__ == "__main__":
    main()
