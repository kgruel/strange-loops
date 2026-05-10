"""MiniLM + Gemini cross-namespace baseline (schema demonstration).

Original real_sweep.py — sweep DoG scale with two embedders, render
namespace-purity per cluster. As a Query value in the new harness:
the per-scale sweep table is custom render code, but the underlying
clustering at the richness scale is `components` readout.

This run is a schema demo, not a verification target. Requires
sentence-transformers + google-genai in env.
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import Counter

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (                                                      # noqa: E402
    Corpus, STEmbedder, GeminiEmbedder, CachedEmbedder,
    Kernel, Query, Readout, run, dog_kernel, positive_components,
)
from core.corpus import load                                            # noqa: E402

CACHE = ROOT / "cache" / "embeddings"


def sweep_table(D, label, rows):
    """The per-scale sweep — kept inline; not in core because each
    experiment may want a different scale ladder."""
    off = D[np.triu_indices(D.shape[0], k=1)]
    print(f"\n## {label}")
    print(f"  N={D.shape[0]}  distance: min={off.min():.3f}  "
          f"median={np.median(off):.3f}  max={off.max():.3f}")
    pcts = [0.1, 0.3, 0.5, 1, 2, 4, 8, 16]
    print(f"  {'pct':>4}  {'σ_e':>5}  {'#comp':>5}  {'sing':>5}")
    for pct in pcts:
        s = float(np.percentile(off, pct))
        K = dog_kernel(D, s)
        comps = positive_components(K)
        sizes = sorted([len(c) for c in comps], reverse=True)
        singletons = sum(1 for x in sizes if x == 1)
        print(f"  {int(pct):>3}%  {s:>5.3f}  {len(comps):>5}  {singletons:>5}")


def main():
    decision_corpus = Corpus(
        vertex="project", kinds=("decision",), min_chars=50,
    )
    rows = load(decision_corpus)
    print(f"# {len(rows)} decisions (filtered to msg ≥ 50 chars)")

    minilm = CachedEmbedder(STEmbedder("all-MiniLM-L6-v2"), cache_dir=CACHE)
    gemini = CachedEmbedder(
        GeminiEmbedder(progress_path=CACHE / "proj_gemini_progress.npy"),
        cache_dir=CACHE,
    )

    # The Query values — schema demonstration. Each is a 10-line declaration.
    q_minilm = Query(corpus=decision_corpus, embedder=minilm,
                     kernel=Kernel(),
                     readouts=(Readout("components", {}),))
    q_gemini = Query(corpus=decision_corpus, embedder=gemini,
                     kernel=Kernel(),
                     readouts=(Readout("components", {}),))

    qr_m = run(q_minilm, rows=rows)
    sweep_table(qr_m.D, "MiniLM (all-MiniLM-L6-v2, 384d)", rows)
    print(f"\n  detail at richness scale σ={qr_m.sigma:.3f}, "
          f"{len(qr_m.readout_outputs['components'])} non-trivial")

    qr_g = run(q_gemini, rows=rows)
    sweep_table(qr_g.D, "Gemini (gemini-embedding-001, 3072d)", rows)
    print(f"\n  detail at richness scale σ={qr_g.sigma:.3f}, "
          f"{len(qr_g.readout_outputs['components'])} non-trivial")


if __name__ == "__main__":
    main()
