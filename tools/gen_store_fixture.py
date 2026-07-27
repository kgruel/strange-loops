#!/usr/bin/env python3
"""Generate the M1 fixture: a Python-written SQLite store + the fold state that
Python's Spec.replay derives from it.

M1 proves store-read interop AND fold parity over a real store. The Go side
opens the SAME .db with the SAME query — `ORDER BY ts, id`, the §6.2 replay
order, matching `SqliteStore.since_raw` (`loops-go/store/sqlite.go`) — replays
through a Spec decoded from the SAME canonical fold encoding, and must
reproduce `expected`.

Replay semantics being certified (atoms Spec.replay): EVERY fold applies to
EVERY payload — there is no kind routing at this layer. So the fixture is a
single-kind store and the Go side must mirror the no-routing choice.

IDs are deterministic (id_override) so the .db is reproducible and row-
comparable — but note `id` is NOT part of the replayed Fact, so derived state
is ULID-independent. That is what isolates pure semantic parity at M1.

This fixture's `ts` and `id` both ascend with insertion, so witness order
(rowid) and event order `(ts, id)` COINCIDE here — M1 deliberately does not
discriminate the two axes. `gen_tie_fixture.py` is the one that does.

Run:  uv run python tools/gen_store_fixture.py --loops-go ~/Code/loops-go
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

from atoms import (
    Avg, Collect, Count, Fact, Field, Latest, Max, Min, Spec, Sum, TopN, Upsert, Window,
)
from engine.sqlite_store import SqliteStore

GENERATED_BY = "loops:tools/gen_store_fixture.py"


# Canonical fold encoding (shared with tools/gen_vectors.py and atoms/decode.go).
FOLDS = [
    dict(op="count", target="n"),
    dict(op="sum", target="total_mem", field="mem"),
    dict(op="latest", target="last_ts"),
    dict(op="avg", target="avg_cpu", field="cpu"),
    dict(op="max", target="peak_cpu", field="cpu"),
    dict(op="min", target="min_cpu", field="cpu"),
    dict(op="topn", target="top", key="pid", by="cpu", n=2),
    dict(op="upsert", target="procs", key="pid"),
    dict(op="window", target="cpu_window", field="cpu", size=3),
    dict(op="collect", target="events", max=3),
]

# State-field kinds drive initial_value(); Go's atoms.initialValue mirrors this
# exactly, so parity holds whatever we pick. Trackers (last_ts/avg/peak/min) use
# an unlisted kind -> None init, matching the unit-test scenarios (and giving
# Min correct behaviour rather than a 0-floor — see FINDINGS.md "Min init").
STATE_FIELDS = [
    ("n", "int"), ("total_mem", "float"), ("last_ts", "none"),
    ("avg_cpu", "none"), ("peak_cpu", "none"), ("min_cpu", "none"),
    ("top", "dict"), ("procs", "dict"), ("cpu_window", "list"), ("events", "list"),
]

PAYLOADS = [
    {"pid": "a", "cpu": 10.0, "mem": 1.2, "_ts": 1000.0, "ref": "host/x"},
    {"pid": "b", "cpu": 30.0, "mem": 2.0, "_ts": 1001.0},
    {"pid": "c", "cpu": 20.0, "mem": 0.5, "_ts": 1002.0, "ref": "host/y,host/z"},
    {"pid": "a", "cpu": 50.0, "mem": 1.5, "_ts": 1003.0},  # update a
    {"pid": "d", "cpu": 5.0, "mem": 3.0, "_ts": 1004.0},
]

KIND = "proc"


def build_fold(d):
    op = d["op"]
    if op == "count":   return Count(target=d["target"])
    if op == "sum":     return Sum(target=d["target"], field=d["field"])
    if op == "latest":  return Latest(target=d["target"])
    if op == "avg":     return Avg(target=d["target"], field=d["field"])
    if op == "max":     return Max(target=d["target"], field=d["field"])
    if op == "min":     return Min(target=d["target"], field=d["field"])
    if op == "topn":    return TopN(target=d["target"], key=d["key"], by=d["by"], n=d["n"], desc=d.get("desc", True))
    if op == "upsert":  return Upsert(target=d["target"], key=d["key"])
    if op == "window":  return Window(target=d["target"], field=d["field"], size=d["size"])
    if op == "collect": return Collect(target=d["target"], max=d.get("max", 0))
    raise ValueError(op)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_destination_arg(parser)
    args = parser.parse_args()
    out = testdata_dir(args.loops_go, "stores")

    db_path = out / "proc.db"
    unlink_store(db_path)  # fresh store each run, for reproducibility

    spec = Spec(
        name="proc_monitor",
        state_fields=tuple(Field(name=n, kind=k) for n, k in STATE_FIELDS),
        folds=tuple(build_fold(f) for f in FOLDS),
    )

    store = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
    for i, payload in enumerate(PAYLOADS):
        fact = Fact(kind=KIND, ts=payload["_ts"], payload=payload, observer="fixture")
        store.append(fact, id_override=f"FIXTURE{i:019d}")  # 26-char, deterministic
    store.close()

    # Read-back check: Python reading its own .db through the production replay
    # path must reproduce the in-memory payloads. This isolates store-read
    # interop from fold correctness, so a Go M1 failure points cleanly at the
    # fold path, not I/O.
    rb = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
    read_back = [p for _, p in rb.since_raw(0)]
    rb.close()
    assert read_back == PAYLOADS, f"read-back diverged from in-memory payloads:\n{read_back}\n{PAYLOADS}"

    # Derived state via the real Spec.replay. PAYLOADS is already in (ts, id)
    # order (the read-back assertion above proves it), which is exactly what
    # the Go side reads.
    expected = spec.replay(PAYLOADS)

    meta = {
        "python_commit": loops_commit(),
        "generated_by": GENERATED_BY,
        "db": "proc.db",
        "kind": KIND,
        "replay_note": "Spec.replay applies every fold to every payload; no kind routing.",
        "folds": FOLDS,
        "state_fields": [{"name": n, "kind": k} for n, k in STATE_FIELDS],
        "expected": expected,
    }
    (out / "proc.expected.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {db_path.name} ({store_total(db_path)} facts) + proc.expected.json @ {meta['python_commit'][:9]}")
    print("expected:", json.dumps(expected, ensure_ascii=False))


def store_total(db_path: Path) -> int:
    import sqlite3
    c = sqlite3.connect(str(db_path))
    n = c.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
    c.close()
    return n


if __name__ == "__main__":
    main()
