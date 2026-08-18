"""G4 probe: is the reported engine failure reachable at the UNMODIFIED base,
by mechanism (a raw _decl.genesis fact through store.append), independent of
any saved hypothesis example?"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "libs/engine")
from atoms import Fact
from engine.sqlite_store import SqliteStore
from engine.vertex_reader import vertex_fold
from lang.document import DECL_GENESIS

sys.path.insert(0, "libs/engine/tests")
from test_properties_replay import _scaffold_vertex, _init_store

print("DECL_GENESIS =", DECL_GENESIS)
with tempfile.TemporaryDirectory() as d:
    sub = Path(d) / "trial"; sub.mkdir()
    vpath, store_path = _scaffold_vertex(sub)
    _init_store(store_path)
    s = SqliteStore(path=store_path,
                    serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
                    deserialize=Fact.from_dict)
    # exactly the shape the report names: a raw _decl.genesis fact, emitted
    # through store.append rather than the absorb ceremony.
    s.append(Fact(kind=DECL_GENESIS, ts=1.0, observer="kyle", origin="test",
                  payload={"lineage": "probe"}), id_override="probe-genesis")
    s.close()
    try:
        vertex_fold(vpath)
    except Exception as e:
        print("RAISED:", type(e).__module__ + "." + type(e).__name__)
        print("MESSAGE:", e)
    else:
        print("NO RAISE — fold succeeded")
