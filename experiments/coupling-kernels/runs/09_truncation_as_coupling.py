"""Third emit-loop demonstrator: truncation-as-coupling-function.

Test alcove's topology claim (project hypothesis truncation-as-coupling-function):
the lens truncation budget and a DMT-like kernel are the same topology at two sites.
Short-range coupling preserved (titles survive), medium-range suppressed
(discriminating content cut), long-range requires drill-down.

Corpus: project facts via fixture manifest (same row-set as 07/08 — apples-to-apples
        cluster lineage compared across budgets).
Sweep:  message truncation budget B ∈ {60, 95, 140, 280, 560, 1120, ∞} chars.
        Descending budget = increasing coupling pressure.
Measurement:
        - At each B, truncate each row's message to B chars, embed, cluster.
        - Compare each truncated run vs the ∞-baseline run with op=lineage.
        - persist_frac(B) = fraction of clusters surviving truncation with j>=0.5.
        - cliff_amplitude = max(persist_frac[i] - persist_frac[i+1]) over adjacent B.
Expected shape if confirmed:
        Sigmoid / cliff curve. Plateau near 1.0 at high B (within coupling range),
        cliff in the middle (discriminating content lost), plateau near 0 at low B
        (only title-driven clusters survive). cliff_amplitude > 0.4 over adjacent
        budget steps → confirmed. Monotonic but smooth (no cliff) → refined.
        Flat or non-monotonic → rejected.

Methodological caveat:
        Uses auto-sigma per run (like 07). If truncation-as-coupling-function is
        confirmed here, follow up with fixed-sigma like 08 to rule out the
        scale-finder masking the effect.

Embedder: MiniLM (STEmbedder) wrapped in CachedEmbedder — different from 07/08's
          E5InstructEmbedder. Topology claim is shape-of-curve, not absolute-value;
          embedder choice trades fidelity for speed across 7 × ~200 embeddings.

Receipts emitted to: experiments/coupling-kernels/data/coupling-kernels.db
  - 1 hypothesis fact (proposed) at start (vertex-local mirror; primary lives in project store)
  - 7 query-run facts (one per budget, including ∞-baseline)
  - 6 query-comparison facts (each truncated budget vs ∞-baseline, op=lineage)
  - 1 hypothesis fact (status updated: confirmed | refined | rejected)
"""
from __future__ import annotations
import math
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
HYPOTHESIS_NAME = "truncation-as-coupling-function"

# Descending budgets — increasing coupling pressure. None = no truncation (baseline).
BUDGETS: list[int | None] = [None, 1120, 560, 280, 140, 95, 60]


def _truncate_rows(rows: list[dict], budget: int | None) -> list[dict]:
    """Return new rows with message truncated to `budget` chars (None = no-op).

    Row order, ids, and other fields are preserved so cluster-lineage compare
    aligns rows index-by-index across runs.
    """
    if budget is None:
        return rows
    return [{**r, "message": (r.get("message") or "")[:budget]} for r in rows]


def _budget_label(budget: int | None) -> str:
    return "∞" if budget is None else str(budget)


def main() -> int:
    rows = load_manifest(MANIFEST)
    print(f"# corpus: {len(rows)} items (fixture manifest)")
    print(f"# budgets: {[_budget_label(b) for b in BUDGETS]}")

    # Emit the hypothesis intent (vertex-local mirror of project-store entry).
    emit_hypothesis(
        name=HYPOTHESIS_NAME,
        message=(
            "Truncation budget acts as a coupling function: short-range "
            "preserved (titles survive low budgets), medium-range suppressed "
            "(discriminating content cut at middle budgets), long-range requires "
            "drill-down (full body only at high budgets). Predict cliff-shaped "
            "persist_frac curve as budget sweeps low-to-high, cliff_amplitude > 0.4."
        ),
        status="proposed",
    )
    print(f"  hypothesis: {HYPOTHESIS_NAME} (proposed)")

    # One cached embedder reused across all budget runs.
    inner = STEmbedder()  # all-MiniLM-L6-v2 by default
    embedder = CachedEmbedder(inner, cache_dir=CACHE_DIR)

    corpus = Corpus(
        vertex="project",
        kinds=("decision", "thread", "task", "plan", "cite", "hypothesis"),
        min_chars=50,
    )
    components_readout = (Readout("components", {}),)

    # Run each budget, embedder fresh per truncation (cache handles dedup).
    results: dict[int | None, tuple[str, object]] = {}  # budget -> (run_id, qr)

    for budget in BUDGETS:
        label = _budget_label(budget)
        rows_b = _truncate_rows(rows, budget)
        texts = [r["message"] for r in rows_b]
        print(f"\n# run budget={label} chars")
        E_b = embedder.embed(texts)
        print(f"  embedded {E_b.shape[0]} items "
              f"(cache miss: {embedder.last_invocation_count})")

        q = Query(corpus=corpus, embedder=embedder,
                  kernel=Kernel(), readouts=components_readout)
        qr = run(q, rows=rows_b, E=E_b)
        run_id = emit_run(qr, q, hypothesis_name=HYPOTHESIS_NAME)
        n_nontriv = sum(1 for c in qr.components if len(c) >= 3)
        print(f"  σ={qr.sigma:.4f}  n_comp={len(qr.components)}  "
              f"non-trivial={n_nontriv}")
        print(f"  run_id: {run_id}")
        results[budget] = (run_id, qr)

    # Compare each truncated budget vs the ∞-baseline.
    baseline_id, baseline_qr = results[None]
    persist_curve: list[tuple[int | None, float, int, int]] = []  # (budget, persist_frac, persist, total)

    print("\n# comparisons: each truncated budget vs ∞-baseline")
    for budget in BUDGETS:
        if budget is None:
            persist_curve.append((None, 1.0, 0, 0))  # self-compare placeholder
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

    # Curve shape analysis — adjacent-step amplitude over high-to-low traversal.
    # Order curve by budget descending (None = ∞ first, then 1120, ..., 60).
    ordered = persist_curve  # already in BUDGETS order (None first)
    fracs = [p[1] for p in ordered]
    drops = [fracs[i] - fracs[i + 1] for i in range(len(fracs) - 1)]
    cliff_amplitude = max(drops) if drops else 0.0
    min_frac = min(fracs)
    max_frac = max(fracs)
    monotonic = all(drops[i] >= -0.05 for i in range(len(drops)))  # tolerate small noise

    print(f"\n# curve summary:")
    for budget, frac, p, t in ordered:
        bar = "█" * int(frac * 40)
        print(f"  B={_budget_label(budget):>4}  persist_frac={frac:.2f}  {bar}")
    print(f"\n  cliff_amplitude (max adjacent drop): {cliff_amplitude:.2f}")
    print(f"  monotonic (within ±0.05): {monotonic}")
    print(f"  range: [{min_frac:.2f}, {max_frac:.2f}]")

    # Status decision
    if cliff_amplitude >= 0.4 and monotonic and min_frac <= 0.4:
        status = "confirmed"
        msg = (
            f"Confirmed: persist_frac curve shows cliff-shape "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range [{min_frac:.2f}, "
            f"{max_frac:.2f}], monotonic). Truncation budget acts as a coupling "
            f"function — discriminating content cut at a specific budget tier "
            f"produces structural cluster reorganization. Read-path-depth-gap "
            f"and kernel-ratio work share topology. Next: replicate with "
            f"fixed-sigma (08-style) to rule out scale-finder masking."
        )
    elif monotonic and (max_frac - min_frac) >= 0.3:
        status = "refined"
        msg = (
            f"Refined: persist_frac monotonic but smooth — cliff_amplitude="
            f"{cliff_amplitude:.2f} below 0.4 threshold, range "
            f"[{min_frac:.2f}, {max_frac:.2f}]. Truncation has graded effect, "
            f"not a sharp coupling-function shape. Either (a) the budgets "
            f"sampled missed the cliff zone, (b) the embedder smooths what "
            f"would be sharper at higher fidelity, or (c) truncation is a "
            f"smooth filter, not a topology-equivalent kernel."
        )
    else:
        status = "rejected"
        msg = (
            f"Rejected: persist_frac curve is flat or non-monotonic "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range "
            f"[{min_frac:.2f}, {max_frac:.2f}], monotonic={monotonic}). "
            f"Truncation budget does not show coupling-function topology "
            f"at this corpus + embedder. The read-path-depth-gap principle "
            f"may need a different framing — perhaps coupling-by-content-density "
            f"rather than coupling-by-char-budget."
        )

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
