"""E5 instruction reshuffle: mechanism vs domain (schema demonstration).

Two Query values differing ONLY in embedder.instruction — what changes
in cluster boundaries reveals whether instruction is a real vocabulary
parameter or decorative.

Schema demo, not a verification target. Requires sentence-transformers.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (                                                      # noqa: E402
    Corpus, E5InstructEmbedder, CachedEmbedder,
    Kernel, Query, Readout, run, compare,
)

CACHE = ROOT / "cache" / "embeddings"

INSTRUCTIONS = {
    "mechanism": "Group these architectural decisions by the underlying "
                 "mechanism or primitive they describe.",
    "domain":    "Group these architectural decisions by the system layer "
                 "or domain area they affect.",
}


def main():
    decisions = Corpus(vertex="project", kinds=("decision",), min_chars=50)
    e_mech = CachedEmbedder(
        E5InstructEmbedder(INSTRUCTIONS["mechanism"]), CACHE,
    )
    e_dom = CachedEmbedder(
        E5InstructEmbedder(INSTRUCTIONS["domain"]), CACHE,
    )
    q_mech = Query(corpus=decisions, embedder=e_mech, kernel=Kernel(),
                   readouts=(Readout("components", {}),))
    q_dom = Query(corpus=decisions, embedder=e_dom, kernel=Kernel(),
                  readouts=(Readout("components", {}),))

    qr_mech = run(q_mech)
    qr_dom = run(q_dom)
    print(f"# E5/mechanism: σ={qr_mech.sigma:.4f}, "
          f"{len(qr_mech.readout_outputs['components'])} clusters")
    print(f"# E5/domain:    σ={qr_dom.sigma:.4f}, "
          f"{len(qr_dom.readout_outputs['components'])} clusters")

    # The reshuffle question is the Compare operator's job:
    cmp_md = compare(qr_mech, qr_dom, op="jaccard")
    cmp_dm = compare(qr_dom, qr_mech, op="jaccard")
    print(f"\n# mechanism → domain best-match jaccards:")
    for ai, bi, j in cmp_md.payload[:8]:
        print(f"   A-C{ai+1} → B-C{bi+1}  j={j:.2f}")
    print(f"\n# domain → mechanism best-match jaccards:")
    for ai, bi, j in cmp_dm.payload[:8]:
        print(f"   A-C{ai+1} → B-C{bi+1}  j={j:.2f}")


if __name__ == "__main__":
    main()
