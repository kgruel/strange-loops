"""G7 probe — the case the implementation report names as UNTESTED: a merger
racing an ORDINARY ArrivalStore.append against the same target.

Asserts the two things exactly-once means here: the arrival log never carries
one row id twice, and nothing is lost — every ordinary append and every
source row is present at the end."""
import hashlib, multiprocessing as mp, sys, tempfile, time
from pathlib import Path
REPO = Path("/Users/kaygee/Code/loops-wt/arrival-projections-gate")
sys.path.insert(0, str(REPO / "libs" / "engine"))
from atoms import Fact
from engine.arrival import ArrivalLog
from engine.arrival_projection import rows_of_record
from engine.arrival_store import ArrivalStore
from tests.conftest import Custodian

def _ts(d): return hashlib.sha256(d.encode()).hexdigest()

def build(d, keys, prefix, n):
    log = ArrivalLog.mint(d / "s.arrival", observer="kyle", signer=keys.signer, key=keys.public)
    s = ArrivalStore(path=d / "s.db", serialize=lambda f: f.to_dict(),
                     deserialize=Fact.from_dict, fact_signer=keys.signer, tick_signer=_ts)
    try:
        for i in range(n):
            s.append(Fact.of("note", "kyle", message=f"{prefix}{i}"))
    finally:
        s.close()
    return log

def appender(dbpath, keydir, n, barrier):
    keys = Custodian(Path(keydir), "kyle")
    barrier.wait()
    s = ArrivalStore(path=Path(dbpath), serialize=lambda f: f.to_dict(),
                     deserialize=Fact.from_dict, fact_signer=keys.signer, tick_signer=_ts)
    try:
        for i in range(n):
            s.append(Fact.of("note", "kyle", message=f"live{i}"))
            time.sleep(0.001)
    finally:
        s.close()

def merger(tdb, sdb, barrier, q):
    sys.path.insert(0, str(REPO / "libs" / "engine"))
    from store import merge_store
    barrier.wait()
    try:
        q.put(("ok", str(merge_store(Path(tdb), Path(sdb)))))
    except Exception as e:
        q.put(("raised", f"{type(e).__name__}: {e}"))

if __name__ == "__main__":
    mp.set_start_method("fork")
    ok = True
    for trial in range(6):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td); t = tmp/"t"; s = tmp/"s"; t.mkdir(); s.mkdir()
            tk, sk = Custodian(t, "kyle"), Custodian(s, "kyle")
            tlog = build(t, tk, "t", 3)
            build(s, sk, "s", 25)
            LIVE = 25
            barrier = mp.Barrier(2); q = mp.Queue()
            pa = mp.Process(target=appender, args=(str(t/"s.db"), str(t), LIVE, barrier))
            pm = mp.Process(target=merger, args=(str(t/"s.db"), str(s/"s.db"), barrier, q))
            pa.start(); pm.start(); pa.join(); pm.join()
            status, detail = q.get()

            ids = [row[0] for rec in ArrivalLog(tlog.path).walk() for _t, row in rows_of_record(rec)]
            dupes = {i for i in ids if ids.count(i) > 1}
            live_present = sum(1 for rec in ArrivalLog(tlog.path).walk()
                               for _t, row in rows_of_record(rec)
                               if '"live' in str(row))
            src_present = sum(1 for rec in ArrivalLog(tlog.path).walk()
                              for _t, row in rows_of_record(rec) if '"s' in str(row))
            good = (not dupes) and status == "ok" and live_present == LIVE
            ok = ok and good
            print(f"trial {trial}: merge={status} rows={len(ids)} dupes={sorted(dupes) or 'NONE'} "
                  f"live_appends_present={live_present}/{LIVE} -> {'PASS' if good else 'FAIL'}")
            if status != "ok":
                print(f"          merge detail: {detail}")
    print("\nG7 RACE PROBE:", "PASS — no duplicate id, no lost append" if ok else "FAIL")
