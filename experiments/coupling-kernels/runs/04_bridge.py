"""Bridge clusters — cross-kind cluster detection under concern instruction.

Schema demonstration + gate 5 verification (bridge count = 6 under concern).
Loads from fixtures/ for reproducibility against the pinned manifest.
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (                                          # noqa: E402
    Corpus, E5InstructEmbedder, Kernel, Query, Readout, run,
)
from core.corpus import load_manifest                       # noqa: E402

INSTRUCTIONS = {
    "mechanism": "Group these items by the underlying mechanism or "
                 "primitive they describe.",
    "concern": "Group these items by the design concern or area of work "
               "each item participates in.",
}

FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
EMBED_CONCERN = FIXTURES / "proj_e5_allkinds_concern.npz"


def render_clustering(qr, label):
    """Match bridge.py's report format."""
    rows = qr.rows
    s = qr.sigma
    comps = qr.components
    non_trivial = [c for c in comps if len(c) >= 3]
    print(f"\n## {label}  (auto-scale σ={s:.4f})")
    print(f"  N={len(rows)}  components={len(comps)}  "
          f"non_trivial≥3={len(non_trivial)}")

    bro = qr.readout_outputs["bridges"]
    pd = bro["purity_distribution"]
    print(f"  kind-purity: pure≥0.9: {pd['pure_ge_0.9']}  "
          f"dominant 0.7-0.9: {pd['dominant_0.7_to_0.9']}  "
          f"mixed<0.7: {pd['mixed_lt_0.7']}")
    print(f"  mean purity: {bro['mean_purity']:.2f}  "
          f"median: {bro['median_purity']:.2f}")
    print(f"  cross-kind clusters (≥2 kinds ×≥2 members): {bro['n_cross_kind']}")

    print(f"\n  ## strongest bridges (concern instruction)")
    for b in bro["bridges"]:
        kd_str = " ".join(f"{k}:{v}" for k, v in b["kinds"].items())
        print(f"  {b['id']}  size={b['size']:<3}  purity={b['purity']:.2f}  "
              f"kinds=[{kd_str}]")


def main():
    rows = load_manifest(MANIFEST)
    E_concern = np.load(EMBED_CONCERN)["E"]
    print(f"# loaded {len(rows)} substantive items across kinds:")
    kc = Counter(r["kind"] for r in rows)
    for k, v in kc.most_common():
        print(f"    {k:<13}  {v}")

    # Schema demo: this is what a Query value looks like. The embedder
    # would compute embeddings from texts; we inject the cached fixture
    # embedding via run(rows=, E=) for byte-stable verification.
    q = Query(
        corpus=Corpus(vertex="project",
                      kinds=("decision", "thread", "task", "plan",
                             "observation", "hypothesis", "cite", "handoff"),
                      min_chars=50),
        embedder=E5InstructEmbedder(instruction=INSTRUCTIONS["concern"]),
        kernel=Kernel(),
        readouts=(Readout(name="bridges", params={}),),
    )
    qr = run(q, rows=rows, E=E_concern)
    render_clustering(qr, "CONCERN instruction")

    # Gate 5 anchor:
    n_bridges = len(qr.readout_outputs["bridges"]["bridges"])
    print(f"\n# n_bridges_concern: {n_bridges}")


if __name__ == "__main__":
    main()
