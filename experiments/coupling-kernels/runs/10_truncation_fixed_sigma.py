"""Fourth emit-loop demonstrator: truncation-effect at FIXED sigma.

Successor to 09_truncation_as_coupling, addressing the methodological flaw
exposed by run 09's auto-sigma drift (0.28→0.37 across budgets). This is
the truncation-side analog of what 08 did for 07.

Setup: same fixture corpus, same STEmbedder + cache, same budget sweep,
       but kernel.sigma is FIXED at 0.2798 (the auto-sigma from run 09's
       ∞-baseline). Only the truncation budget varies.

This isolates the kernel-level effect from the scale-finder convergence.
If run 09's cliff was the scale-finder doing work, this run will show a
flat / weak curve. If the cliff is real at the kernel level, this run
will reproduce it (or sharpen it).

Hypothesis (predictive):
  truncation-effect-at-fixed-sigma — Truncation budget produces structural
  cluster reorganization at fixed kernel sigma. Predict cliff-shaped
  persist_frac curve survives at fixed sigma, cliff_amplitude >= 0.3
  (allowing the cliff to be less sharp than auto-sigma case).

If this confirms:
  truncation-as-coupling-function (project) → confirmed
  scale-finder was NOT the source of run 09's cliff
  read-path-depth-gap and kernel-ratio share topology at the kernel level

If this rejects:
  truncation-as-coupling-function (project) → refined or rejected
  run 09's cliff was a scale-finder artifact, parallel to run 07
  read-path-depth-gap may need a different framing

Receipts emitted to: experiments/coupling-kernels/data/coupling-kernels.db
  - 1 hypothesis fact (proposed)
  - 7 query-run facts (one per budget, fixed sigma)
  - 6 query-comparison facts (each truncated budget vs ∞-baseline)
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
    Corpus, STEmbedder, CachedEmbedder, Kernel, Query, Readout, run, compare,
)
from core.corpus import load_manifest                                   # noqa: E402
from core.emit import emit_hypothesis, emit_run, emit_comparison        # noqa: E402

FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
CACHE_DIR = ROOT / "cache"
HYPOTHESIS_NAME = "truncation-effect-at-fixed-sigma"
FIXED_SIGMA = 0.2798  # ∞-baseline auto-sigma from run 09

BUDGETS: list[int | None] = [None, 1120, 560, 280, 140, 95, 60]


def _truncate_rows(rows: list[dict], budget: int | None) -> list[dict]:
    if budget is None:
        return rows
    return [{**r, "message": (r.get("message") or "")[:budget]} for r in rows]


def _budget_label(budget: int | None) -> str:
    return "∞" if budget is None else str(budget)


def main() -> int:
    rows = load_manifest(MANIFEST)
    print(f"# corpus: {len(rows)} items")
    print(f"# fixed sigma: {FIXED_SIGMA}")
    print(f"# budgets: {[_budget_label(b) for b in BUDGETS]}")

    emit_hypothesis(
        name=HYPOTHESIS_NAME,
        message=(
            "At fixed kernel sigma=0.2798, truncation budget produces "
            "structural cluster reorganization. Predict cliff-shaped "
            "persist_frac curve survives with cliff_amplitude >= 0.3. "
            "Tests whether run 09's cliff was kernel-level or scale-finder."
        ),
        status="proposed",
    )
    print(f"  hypothesis: {HYPOTHESIS_NAME} (proposed)")

    inner = STEmbedder()
    embedder = CachedEmbedder(inner, cache_dir=CACHE_DIR)

    corpus = Corpus(
        vertex="project",
        kinds=("decision", "thread", "task", "plan", "cite", "hypothesis"),
        min_chars=50,
    )
    components_readout = (Readout("components", {}),)

    results: dict[int | None, tuple[str, object]] = {}

    for budget in BUDGETS:
        label = _budget_label(budget)
        rows_b = _truncate_rows(rows, budget)
        texts = [r["message"] for r in rows_b]
        print(f"\n# run budget={label} chars  σ_fixed={FIXED_SIGMA}")
        E_b = embedder.embed(texts)
        print(f"  embedded {E_b.shape[0]} items "
              f"(cache miss: {embedder.last_invocation_count})")

        q = Query(corpus=corpus, embedder=embedder,
                  kernel=Kernel(sigma=FIXED_SIGMA, ratio=2.0),
                  readouts=components_readout)
        qr = run(q, rows=rows_b, E=E_b)
        run_id = emit_run(qr, q, hypothesis_name=HYPOTHESIS_NAME)
        n_nontriv = sum(1 for c in qr.components if len(c) >= 3)
        print(f"  σ={qr.sigma:.4f}  n_comp={len(qr.components)}  "
              f"non-trivial={n_nontriv}")
        print(f"  run_id: {run_id}")
        results[budget] = (run_id, qr)

    baseline_id, baseline_qr = results[None]
    persist_curve: list[tuple[int | None, float, int, int]] = []

    print("\n# comparisons: each truncated budget vs ∞-baseline (fixed σ)")
    for budget in BUDGETS:
        if budget is None:
            persist_curve.append((None, 1.0, 0, 0))
            continue
        run_id, qr = results[budget]
        cr = compare(baseline_qr, qr, op="lineage")
        cmp_id = emit_comparison(cr, baseline_id, run_id)
        matches = cr.payload
        persist = sum(1 for _, _, j in matches if j >= 0.5)
        total = len(matches)
        frac = persist / max(total, 1)
        persist_curve.append((budget, frac, persist, total))
        print(f"  B={_budget_label(budget):>4}  "
              f"persist={persist}/{total}  persist_frac={frac:.2f}  "
              f"cmp_id={cmp_id[:48]}...")

    ordered = persist_curve
    fracs = [p[1] for p in ordered]
    drops = [fracs[i] - fracs[i + 1] for i in range(len(fracs) - 1)]
    cliff_amplitude = max(drops) if drops else 0.0
    min_frac = min(fracs)
    max_frac = max(fracs)
    monotonic = all(drops[i] >= -0.05 for i in range(len(drops)))

    print(f"\n# curve summary (fixed σ={FIXED_SIGMA}):")
    for budget, frac, p, t in ordered:
        bar = "█" * int(frac * 40)
        print(f"  B={_budget_label(budget):>4}  persist_frac={frac:.2f}  {bar}")
    print(f"\n  cliff_amplitude (max adjacent drop): {cliff_amplitude:.2f}")
    print(f"  monotonic (within ±0.05): {monotonic}")
    print(f"  range: [{min_frac:.2f}, {max_frac:.2f}]")

    # Status decision — threshold lowered to 0.3 since fixed sigma may produce
    # smoother curves than auto-sigma (less "richness scale" amplification).
    if cliff_amplitude >= 0.3 and monotonic and min_frac <= 0.5:
        status = "confirmed"
        msg = (
            f"Confirmed: cliff-shape survives at fixed σ={FIXED_SIGMA} "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range "
            f"[{min_frac:.2f}, {max_frac:.2f}]). Truncation produces "
            f"kernel-level cluster reorganization independent of scale-finder. "
            f"Run 09's cliff was real, not artifact. truncation-as-coupling-function "
            f"is on solid footing — read-path-depth-gap and kernel-ratio "
            f"share topology at the kernel level."
        )
    elif (max_frac - min_frac) >= 0.2 and monotonic:
        status = "refined"
        msg = (
            f"Refined: cluster structure responds to truncation at fixed σ "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range "
            f"[{min_frac:.2f}, {max_frac:.2f}]) but cliff is less pronounced "
            f"than run 09 (auto-sigma). Some of run 09's sharpness came from "
            f"scale-finder; some is genuine kernel response. The coupling-function "
            f"topology holds in smooth form, not sharp form."
        )
    else:
        status = "rejected"
        msg = (
            f"Rejected: flat curve at fixed σ "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range "
            f"[{min_frac:.2f}, {max_frac:.2f}]). Run 09's cliff was the "
            f"scale-finder doing work, not kernel-level coupling. "
            f"truncation-as-coupling-function (project) needs reframing — "
            f"truncation may be a content filter, not a topology-equivalent kernel."
        )

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
