"""Same probe with _ALLOWED EMPTIED — the raw detector verdict, so the
allowlist entry cannot mask whether the conflict is real."""
import sys
sys.path.insert(0, ".")
import tests.architecture.test_rule_18_arrival_vocabulary_denylist as R
R._ALLOWED = set()
REL = "libs/store/src/store/merge.py"

cases = {
  "named import + named raise (what the cut needs)":
    "from engine import jsonl_store\ndef f():\n    raise jsonl_store.JsonlCanonicalUnsupported('x')\n",
  "ALIASED (the evasion the impl rejected)":
    "from engine.jsonl_store import JsonlCanonicalUnsupported as _Refusal\ndef f():\n    raise _Refusal('x')\n",
}
for label, src in cases.items():
    print(f"{label!r:50} -> {R._faults(src, REL) or 'CLEAN'}")

print("\n-- the REAL merge.py at HEAD, allowlist EMPTIED --")
raw = R._faults(open(REL).read(), REL)
print(f"   raw faults: {raw or 'CLEAN'}")
print("\n-- the REAL merge.py at HEAD, allowlist AS SHIPPED --")
import importlib
importlib.reload(R)
print(f"   faults: {R._faults(open(REL).read(), REL) or 'CLEAN'}")
