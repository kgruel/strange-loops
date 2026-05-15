"""Truncation cliff E5 replication — content-structural vs instrument-artifact test.

Replicates run 09 (truncation-as-coupling-function) with E5InstructEmbedder
instead of MiniLM (STEmbedder). The question: does the truncation cliff shape
that runs 09 + 10 confirmed at depth=9 each (7 query-runs apiece) reproduce
under a different, higher-fidelity embedder?

Hypothesis space:
  - REPLICATES (cliff shape with cliff_amplitude >= 0.3): cliff is
    content-structural. The discriminating-content-cut-at-medium-budget
    phenomenon is a property of the corpus, not of MiniLM's specific
    representational geometry. Strengthens truncation-as-coupling-function
    as a general claim about how budget interacts with content topology.
  - DOES NOT REPLICATE (flat or wildly different shape): cliff is an
    instrument-artifact specific to MiniLM. The original confirmations are
    still valid for MiniLM but the topology claim narrows to "MiniLM-class
    embedders produce a cliff under truncation." Either result is informative.
  - REPLICATES WITH DIFFERENT CLIFF LOCATION (cliff shifts to different
    budget tier): both embedders see a cliff but at different budgets,
    meaning each embedder has its own truncation-coupling regime. Strengthens
    the framing but disqualifies any specific budget threshold as "the
    discriminating content boundary."

Why this matters: tonight named measurement-fidelity-discipline as a pattern.
This run tests whether the most cited current finding (truncation-as-coupling
with 7-run replication) is robust to embedder choice — that's the highest-fidelity
test of an experimental finding available to us. Same shape as the
'suspicious-cleanness as overfit-check' principle, applied at the embedder layer.

Corpus + sweep: identical to run 09 — same fixture manifest, same BUDGETS,
                same truncation function, same kernel parameters. Only the
                embedder differs.

Instruction for E5: same as runs 07 + 08 ("Group these items by the design
                    concern or area of work each item participates in"). Keeps
                    the embedding regime aligned with the existing fixture
                    cache (though truncated texts won't hit the cache).

Expected wall time: ~3-10 minutes for 7 × ~200 = ~1400 E5 embeddings at
                    batch_size=8 on CPU. Slower than MiniLM (run 09 was
                    near-instant). If too slow, park mid-run — receipts
                    already capture per-budget runs as they complete.

Receipts emitted:
  - 1 hypothesis fact (proposed) at start
  - up to 7 query-run facts (one per budget completed)
  - up to 6 query-comparison facts (each truncated budget vs ∞-baseline)
  - 1 hypothesis fact (status updated) at end if the sweep completes
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
    Corpus, E5InstructEmbedder, CachedEmbedder, Kernel, Query, Readout, run, compare,
)
from core.corpus import load_manifest                                   # noqa: E402
from core.emit import emit_hypothesis, emit_run, emit_comparison        # noqa: E402

FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
CACHE_DIR = ROOT / "cache"
HYPOTHESIS_NAME = "truncation-cliff-e5-replication"

# Matches runs 07 + 08 — keeps the embedding regime aligned with existing
# E5 fixture (proj_e5_allkinds_concern.npz). Truncated texts don't hit that
# cache, but unmodified ∞-baseline rows do match prior fixture inputs.
INSTRUCTION = (
    "Group these items by the design concern or area of work "
    "each item participates in."
)

# Same as run 09 for direct curve-shape comparability.
BUDGETS: list[int | None] = [None, 1120, 560, 280, 140, 95, 60]


def _truncate_rows(rows: list[dict], budget: int | None) -> list[dict]:
    """Return new rows with message truncated to `budget` chars (None = no-op).

    Row order, ids, and other fields are preserved so cluster-lineage compare
    aligns rows index-by-index across runs. Identical to run 09's helper.
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
    print(f"# embedder: E5InstructEmbedder (multilingual-e5-large-instruct)")

    emit_hypothesis(
        name=HYPOTHESIS_NAME,
        message=(
            "The truncation cliff (run 09: cliff_amplitude=0.44, monotonic; "
            "run 10: cliff_amplitude=0.44 at fixed σ) replicates under E5Instruct "
            "embedding with cliff_amplitude >= 0.3 and monotonic shape. Tests "
            "whether the cliff is content-structural (replicates) or "
            "instrument-artifact specific to MiniLM-class embedders (does not "
            "replicate). Same BUDGETS, same kernel, same corpus — only embedder differs."
        ),
        status="proposed",
    )
    print(f"  hypothesis: {HYPOTHESIS_NAME} (proposed)")

    inner = E5InstructEmbedder(INSTRUCTION)
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

    baseline_id, baseline_qr = results[None]
    persist_curve: list[tuple[int | None, float, int, int]] = []

    print("\n# comparisons: each truncated budget vs ∞-baseline")
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

    print(f"\n# E5 curve summary:")
    for budget, frac, p, t in ordered:
        bar = "█" * int(frac * 40)
        print(f"  B={_budget_label(budget):>4}  persist_frac={frac:.2f}  {bar}")
    print(f"\n  cliff_amplitude (max adjacent drop): {cliff_amplitude:.2f}")
    print(f"  monotonic (within ±0.05): {monotonic}")
    print(f"  range: [{min_frac:.2f}, {max_frac:.2f}]")
    print(f"  MiniLM (run 09) reference: cliff_amplitude=0.44, monotonic, range [0.06, 1.00]")

    # Status decision — replication criterion is more permissive than the
    # original confirm threshold. Replication holds if a cliff of amplitude
    # >= 0.3 appears with monotonic shape — direction-matches the MiniLM result
    # even if the precise cliff height differs.
    if cliff_amplitude >= 0.3 and monotonic and min_frac <= 0.5:
        status = "confirmed"
        msg = (
            f"Confirmed: E5 replication produces cliff_amplitude="
            f"{cliff_amplitude:.2f}, monotonic, range [{min_frac:.2f}, "
            f"{max_frac:.2f}]. Truncation cliff is content-structural — the "
            f"phenomenon survives a different embedder regime. The "
            f"truncation-as-coupling-function topology claim is robust to "
            f"embedder choice, strengthening its generalization. "
            f"Reference: MiniLM (run 09) cliff_amplitude=0.44."
        )
    elif monotonic and (max_frac - min_frac) >= 0.2:
        status = "refined"
        msg = (
            f"Refined: E5 sees a graded effect but not a sharp cliff "
            f"(cliff_amplitude={cliff_amplitude:.2f} below 0.3 threshold; "
            f"range [{min_frac:.2f}, {max_frac:.2f}], monotonic). The "
            f"truncation effect is present at E5 fidelity but smoother — "
            f"either E5 captures intermediate content that MiniLM was already "
            f"averaging out, or the cliff is a representational regime, not "
            f"a content-structural property."
        )
    else:
        status = "rejected"
        msg = (
            f"Rejected: E5 replication does NOT show truncation cliff "
            f"(cliff_amplitude={cliff_amplitude:.2f}, range [{min_frac:.2f}, "
            f"{max_frac:.2f}], monotonic={monotonic}). The MiniLM cliff is "
            f"instrument-specific. truncation-as-coupling-function narrows: "
            f"holds for MiniLM-class embedders, not a general topology of "
            f"truncation. The original 7-run replication of the cliff was "
            f"replicating within the same instrument, not across instruments."
        )

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
