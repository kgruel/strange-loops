"""Gate spot-check: after each of the three refusals, does the target path
leave a stray .db / -wal / -shm behind? Checked BY HAND, not via the tests'
own assertions."""
import hashlib, sys, tempfile
from pathlib import Path
REPO = Path("/Users/kaygee/Code/loops-wt/arrival-projections-gate")
sys.path.insert(0, str(REPO / "libs" / "engine"))
from atoms import Fact
from engine.arrival import ArrivalLog
from engine.arrival_store import ArrivalCanonicalUnsupported, ArrivalStore
from tests.conftest import Custodian
from store import receive_store, slice_store
from store.rebirth import rebirth_store

def _ts(d): return hashlib.sha256(d.encode()).hexdigest()

def fixture(tmp):
    """A live arrival log whose .db index is ABSENT — the exact hazard state."""
    keys = Custodian(tmp, "kyle")
    log = ArrivalLog.mint(tmp/"t.arrival", observer="kyle", signer=keys.signer, key=keys.public)
    s = ArrivalStore(path=tmp/"t.db", serialize=lambda f: f.to_dict(),
                     deserialize=Fact.from_dict, fact_signer=keys.signer, tick_signer=_ts)
    try:
        s.append(Fact.of("note", "kyle", message="x"))
    finally:
        s.close()
    for p in (tmp/"t.db", tmp/"t.db-wal", tmp/"t.db-shm"):
        p.unlink(missing_ok=True)
    assert (tmp/"t.arrival").is_file() and not (tmp/"t.db").exists()
    # a plain sqlite source to feed the create arms
    src = tmp/"src.db"
    from engine.sqlite_store import SqliteStore
    ss = SqliteStore(path=src, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    ss.append(Fact.of("note", "kyle", message="s"))
    ss.close()
    return log, src

def strays(tmp):
    return sorted(p.name for p in tmp.iterdir()
                  if p.name.startswith("t.db"))

ok = True
for label, call in [
    ("receive_store", lambda tmp, src: receive_store(tmp/"t.db", src)),
    ("slice_store",   lambda tmp, src: slice_store(src, tmp/"t.db")),
    ("rebirth_store", lambda tmp, src: rebirth_store(src, tmp/"t.db", observer="kyle")),
]:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _log, src = fixture(tmp)
        try:
            call(tmp, src)
            print(f"{label:15} -> NO REFUSAL (!!)"); ok = False; continue
        except ArrivalCanonicalUnsupported as e:
            left = strays(tmp)
            good = not left
            ok = ok and good
            print(f"{label:15} -> REFUSED; stray t.db* files: {left or 'NONE'} -> {'PASS' if good else 'FAIL'}")
            print(f"                  msg: {str(e)[:110]}...")
print("\nSTRAY-FILE SPOT-CHECK:", "PASS — every refusal leaves the directory clean" if ok else "FAIL")
