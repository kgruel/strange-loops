"""First emit-loop demonstrator: kernel-ratio robustness.

Complete loop: hypothesis → run → run → comparison → status update.
Uses the existing fixture (E5InstructEmbedder + proj_e5_allkinds_concern.npz)
so the demo is offline, deterministic, and runs in seconds.

Hypothesis (testable, predictive):
  Project decisions clustered with two different DoG kernel inhibitory
  ratios (2.0 vs 3.0) produce substantially overlapping clusters at the
  richness scale. If the structural finding is robust to the inhibitory
  width choice, lineage-jaccard >= 0.5 should hold for >= 60% of the
  larger clusters.

Receipts emitted to: experiments/coupling-kernels/data/coupling-kernels.db
  - 1 hypothesis fact (proposed)
  - 2 query-run facts (one per ratio)
  - 1 query-comparison fact (op=lineage)
  - 1 hypothesis fact (status updated: confirmed | refined | rejected)
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (                                                      # noqa: E402
    Corpus, E5InstructEmbedder, Kernel, Query, Readout, run, compare,
)
from core.corpus import load_manifest                                   # noqa: E402
from core.emit import emit_hypothesis, emit_run, emit_comparison        # noqa: E402

FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
EMBED = FIXTURES / "proj_e5_allkinds_concern.npz"
INSTRUCTION = (
    "Group these items by the design concern or area of work "
    "each item participates in."
)
HYPOTHESIS_NAME = "kernel-ratio-robustness"


def main() -> int:
    rows = load_manifest(MANIFEST)
    E = np.load(EMBED)["E"]
    print(f"# corpus: {len(rows)} items, embedding {E.shape}")

    # Emit the hypothesis (intent first, before runs)
    emit_hypothesis(
        name=HYPOTHESIS_NAME,
        message=(
            "DoG kernel clustering of project items is robust to inhibitory "
            "ratio choice (2.0 vs 3.0). Predict lineage-jaccard >= 0.5 holds "
            "for >= 60% of the larger clusters."
        ),
        status="proposed",
    )
    print(f"  hypothesis: {HYPOTHESIS_NAME} (proposed)")

    # Two Query values differing only in kernel.ratio.
    # Embedder is constructed for spec_hash purposes; embed_raw never called
    # because we inject E= directly into run().
    embedder = E5InstructEmbedder(INSTRUCTION)
    corpus = Corpus(vertex="project", kinds=("decision", "thread", "task",
                                              "plan", "cite", "hypothesis"),
                    min_chars=50)
    components_readout = (Readout("components", {}),)

    q_low = Query(corpus=corpus, embedder=embedder,
                  kernel=Kernel(ratio=2.0), readouts=components_readout)
    q_high = Query(corpus=corpus, embedder=embedder,
                   kernel=Kernel(ratio=3.0), readouts=components_readout)

    print("\n# run 1: ratio=2.0")
    qr_low = run(q_low, rows=rows, E=E)
    run_low_id = emit_run(qr_low, q_low, hypothesis_name=HYPOTHESIS_NAME)
    print(f"  σ={qr_low.sigma:.4f}  n_comp={len(qr_low.components)}  "
          f"non-trivial={sum(1 for c in qr_low.components if len(c) >= 3)}")
    print(f"  run_id: {run_low_id}")

    print("\n# run 2: ratio=3.0")
    qr_high = run(q_high, rows=rows, E=E)
    run_high_id = emit_run(qr_high, q_high, hypothesis_name=HYPOTHESIS_NAME)
    print(f"  σ={qr_high.sigma:.4f}  n_comp={len(qr_high.components)}  "
          f"non-trivial={sum(1 for c in qr_high.components if len(c) >= 3)}")
    print(f"  run_id: {run_high_id}")

    print("\n# comparison: lineage")
    cr = compare(qr_low, qr_high, op="lineage")
    cmp_id = emit_comparison(cr, run_low_id, run_high_id)
    matches = cr.payload
    persist = sum(1 for _, _, j in matches if j >= 0.5)
    morph = sum(1 for _, _, j in matches if 0.2 <= j < 0.5)
    new = len(matches) - persist - morph
    persist_frac = persist / max(len(matches), 1)
    print(f"  cmp_id: {cmp_id}")
    print(f"  total {len(matches)} clusters: "
          f"persist={persist} morph={morph} new={new}  "
          f"persist_frac={persist_frac:.2f}")

    # Status update: predict confirmed if persist_frac >= 0.6
    if persist_frac >= 0.6:
        status = "confirmed"
        msg = (f"Confirmed: {persist}/{len(matches)} clusters survive "
               f"ratio change with j>=0.5 (persist_frac={persist_frac:.2f}). "
               f"Kernel inhibitory ratio is not a sensitive parameter at this scale.")
    elif persist_frac >= 0.3:
        status = "refined"
        msg = (f"Refined: {persist}/{len(matches)} clusters survive "
               f"(persist_frac={persist_frac:.2f}). Robustness is partial — "
               f"some structural features are ratio-dependent. The hypothesis "
               f"stands for the major clusters but not for finer-grained ones.")
    else:
        status = "rejected"
        msg = (f"Rejected: only {persist}/{len(matches)} clusters survive "
               f"with j>=0.5 (persist_frac={persist_frac:.2f}). Kernel "
               f"inhibitory ratio materially changes cluster structure; "
               f"clustering is not robust to this parameter.")

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
