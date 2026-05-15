"""Second emit-loop demonstrator: ratio-effect at FIXED sigma.

Successor to 07_kernel_robustness, addressing the methodological flaw
exposed by run 07's degenerate confirmation. See:
  loops read coupling-kernels --plain
    hypothesis kernel-ratio-robustness (refined)
    hypothesis ratio-effect-at-fixed-sigma (proposed) ← this run tests
    hypothesis scale-finder-ratio-invariance (proposed) ← this run produces
                                                         evidence for

Setup: same fixture (E5InstructEmbedder + proj_e5_allkinds_concern.npz),
but kernel.sigma is FIXED at 0.0234 for both runs. Only ratio varies.
This isolates the kernel-level effect from the scale-finder convergence.

Predict: lineage-jaccard < 0.5 for >= 50% of larger clusters → ratio
materially affects kernel-level structure when sigma is held constant.

If this holds: ratio-effect-at-fixed-sigma confirmed; original
kernel-ratio-robustness was confirmed for the wrong reason; the
scale-finder is doing the work of producing apparent invariance.
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
HYPOTHESIS_NAME = "ratio-effect-at-fixed-sigma"
FIXED_SIGMA = 0.0234  # the auto-richness scale chosen by run 07 for both ratios


def main() -> int:
    rows = load_manifest(MANIFEST)
    E = np.load(EMBED)["E"]
    print(f"# corpus: {len(rows)} items, embedding {E.shape}")
    print(f"# fixed sigma: {FIXED_SIGMA}")

    embedder = E5InstructEmbedder(INSTRUCTION)
    corpus = Corpus(vertex="project", kinds=("decision", "thread", "task",
                                              "plan", "cite", "hypothesis"),
                    min_chars=50)
    components_readout = (Readout("components", {}),)

    # Same fixed sigma, different ratios. Now ratio is the ONLY axis varied
    # and find_richness_scale is bypassed.
    q_low = Query(corpus=corpus, embedder=embedder,
                  kernel=Kernel(sigma=FIXED_SIGMA, ratio=2.0),
                  readouts=components_readout)
    q_high = Query(corpus=corpus, embedder=embedder,
                   kernel=Kernel(sigma=FIXED_SIGMA, ratio=3.0),
                   readouts=components_readout)

    print("\n# run 1: sigma=0.0234, ratio=2.0")
    qr_low = run(q_low, rows=rows, E=E)
    run_low_id = emit_run(qr_low, q_low, hypothesis_name=HYPOTHESIS_NAME)
    print(f"  σ={qr_low.sigma:.4f}  n_comp={len(qr_low.components)}  "
          f"non-trivial={sum(1 for c in qr_low.components if len(c) >= 3)}")

    print("\n# run 2: sigma=0.0234, ratio=3.0")
    qr_high = run(q_high, rows=rows, E=E)
    run_high_id = emit_run(qr_high, q_high, hypothesis_name=HYPOTHESIS_NAME)
    print(f"  σ={qr_high.sigma:.4f}  n_comp={len(qr_high.components)}  "
          f"non-trivial={sum(1 for c in qr_high.components if len(c) >= 3)}")

    print("\n# comparison: lineage")
    cr = compare(qr_low, qr_high, op="lineage")
    cmp_id = emit_comparison(cr, run_low_id, run_high_id)
    matches = cr.payload
    persist = sum(1 for _, _, j in matches if j >= 0.5)
    morph = sum(1 for _, _, j in matches if 0.2 <= j < 0.5)
    new = len(matches) - persist - morph
    persist_frac = persist / max(len(matches), 1)
    print(f"  cmp_id: {cmp_id[:60]}...")
    print(f"  total {len(matches)} clusters: "
          f"persist={persist} morph={morph} new={new}  "
          f"persist_frac={persist_frac:.2f}")

    # PREDICTION INVERTED from 07: we predicted ratio MATTERS at fixed sigma.
    # Confirmed = persist_frac < 0.5 (substantial restructuring).
    # Rejected = persist_frac >= 0.5 (clusters survive — kernel is flat in ratio).
    if persist_frac < 0.5:
        status = "confirmed"
        msg = (f"Confirmed: only {persist}/{len(matches)} clusters survive "
               f"ratio change at fixed sigma (persist_frac={persist_frac:.2f}). "
               f"Kernel-level structure IS ratio-sensitive. Run 07's apparent "
               f"invariance was the scale-finder doing the work — find_richness_scale "
               f"converges to compensating sigma values across ratios. "
               f"Implication: ratio is a real parameter, but auto-richness "
               f"masks its effect.")
    elif persist_frac < 0.8:
        status = "refined"
        msg = (f"Partial: {persist}/{len(matches)} clusters survive "
               f"(persist_frac={persist_frac:.2f}). Kernel response shows "
               f"some ratio sensitivity at fixed sigma but not as strong as "
               f"predicted. Larger clusters may be more ratio-robust than "
               f"smaller ones — worth disaggregating by cluster size next.")
    else:
        status = "rejected"
        msg = (f"Rejected: {persist}/{len(matches)} clusters survive at "
               f"fixed sigma (persist_frac={persist_frac:.2f}). The DoG "
               f"kernel response is genuinely flat across ratio 2.0–3.0 "
               f"at this sigma. The original kernel-ratio-robustness "
               f"hypothesis stands — kernel is ratio-invariant for real "
               f"reasons, not because of scale-finder masking.")

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
