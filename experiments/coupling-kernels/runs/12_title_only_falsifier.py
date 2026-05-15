"""Falsifier for cliff-correlates-with-verdict-locus interpretation.

Tests the hypothesis title-only-clustering-preserves-survivors (project store):
if the cluster-survival signature at the B=1120→560 cliff is driven by
verdict-in-name (vs verdict-in-body), then clustering with topic-names alone
should preserve the SURVIVOR clusters specifically — not the FAILURE clusters,
and not all 16 uniformly.

Setup: same fixture corpus, MiniLM + cached embedder (parity with runs 09–11).
Three runs:
  1. baseline:   full message text (re-run of run 09's ∞-baseline)
  2. cliff:      truncated to B=560 (re-run of run 09's cliff)
  3. title-only: message replaced with topic-name only (or key for non-topic kinds)

Two lineage comparisons against baseline:
  - cliff vs baseline:      gives survivor/failure classification per baseline cluster
  - title-only vs baseline: gives title-preservation per baseline cluster

Cross-reference: among CLIFF-survivors, how many are TITLE-preserved?
                 among CLIFF-failures, how many are TITLE-preserved?

Decision:
  confirmed: title-preservation rate among cliff-survivors > rate among
             cliff-failures by margin >= 0.3 (clear correlation)
  refined:   margin 0.1–0.3 (weak correlation; interpretation has partial
             support but the cliff is not purely verdict-locus driven)
  rejected:  margin < 0.1 OR title-preservation is uniformly high/low
             (interpretation is overfit; cliff has another driver)

Methodological caveat: with only 16 non-trivial baseline clusters and 7 cliff-
failures + 9 cliff-survivors, sample size for the margin is small. Result
should be read as direction-of-evidence, not statistically significant.
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
HYPOTHESIS_NAME = "title-only-clustering-preserves-survivors"


def _title_only_rows(rows: list[dict]) -> list[dict]:
    """Replace message with topic (or key if no topic) — title-only encoding."""
    return [
        {**r, "message": r.get("topic") or r.get("key") or ""}
        for r in rows
    ]


def _cliff_rows(rows: list[dict], budget: int = 560) -> list[dict]:
    return [{**r, "message": (r.get("message") or "")[:budget]} for r in rows]


def _run_query(label: str, rows_in: list[dict], embedder, corpus, kernel):
    texts = [r["message"] for r in rows_in]
    E = embedder.embed(texts)
    avg_len = sum(len(t) for t in texts) / max(len(texts), 1)
    print(f"  embedded {E.shape[0]} items (cache miss: "
          f"{embedder.last_invocation_count}, avg_len={avg_len:.0f})")
    q = Query(corpus=corpus, embedder=embedder, kernel=kernel,
              readouts=(Readout("components", {}),))
    qr = run(q, rows=rows_in, E=E)
    run_id = emit_run(qr, q, hypothesis_name=HYPOTHESIS_NAME)
    n_nontriv = sum(1 for c in qr.components if len(c) >= 3)
    print(f"  σ={qr.sigma:.4f}  n_comp={len(qr.components)}  "
          f"non-trivial={n_nontriv}  run_id={run_id}")
    return run_id, qr


def main() -> int:
    rows = load_manifest(MANIFEST)
    print(f"# corpus: {len(rows)} items")

    emit_hypothesis(
        name=HYPOTHESIS_NAME,
        message=(
            "Predict: clustering with topic-names alone preserves cliff-survivor "
            "clusters (j>=0.5) but not cliff-failure clusters. If preservation "
            "rate among survivors exceeds rate among failures by margin >= 0.3, "
            "the verdict-in-name interpretation earns support."
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
    kernel = Kernel()

    print("\n# run 1: baseline (full message)")
    base_id, base_qr = _run_query("baseline", rows, embedder, corpus, kernel)

    print("\n# run 2: cliff (B=560)")
    cliff_id, cliff_qr = _run_query(
        "cliff", _cliff_rows(rows, 560), embedder, corpus, kernel)

    print("\n# run 3: title-only")
    title_id, title_qr = _run_query(
        "title-only", _title_only_rows(rows), embedder, corpus, kernel)

    # Comparisons against baseline
    print("\n# comparison 1: cliff vs baseline (lineage)")
    cliff_cmp = compare(base_qr, cliff_qr, op="lineage")
    cliff_cmp_id = emit_comparison(cliff_cmp, base_id, cliff_id)
    cliff_matches = cliff_cmp.payload
    print(f"  cmp_id: {cliff_cmp_id[:48]}...")

    print("\n# comparison 2: title-only vs baseline (lineage)")
    title_cmp = compare(base_qr, title_qr, op="lineage")
    title_cmp_id = emit_comparison(title_cmp, base_id, title_id)
    title_matches = title_cmp.payload
    print(f"  cmp_id: {title_cmp_id[:48]}...")

    # Both lineages are indexed by big_baseline cluster — same order, same indices.
    # Cross-reference per baseline cluster.
    big_baseline = sorted(
        [c for c in base_qr.components if len(c) >= 3], key=len, reverse=True
    )

    print(f"\n# cross-reference ({len(big_baseline)} baseline clusters):")
    print(f"  {'idx':>3}  {'size':>4}  {'cliff_j':>7}  {'title_j':>7}  "
          f"{'cliff':>9}  {'title':>9}  preview")

    survivors_title_preserved = 0
    survivors_total = 0
    failures_title_preserved = 0
    failures_total = 0

    for i, ((_, _, cj), (_, _, tj)) in enumerate(zip(cliff_matches, title_matches)):
        cluster = big_baseline[i]
        cliff_surv = cj >= 0.5
        title_pres = tj >= 0.5
        if cliff_surv:
            survivors_total += 1
            if title_pres:
                survivors_title_preserved += 1
        else:
            failures_total += 1
            if title_pres:
                failures_title_preserved += 1
        # Preview: peek at the first row's topic/key
        row0 = (rows[cluster[0]].get("topic") or rows[cluster[0]].get("key", "?"))
        marker_c = "SURV" if cliff_surv else "FAIL"
        marker_t = "PRES" if title_pres else "lost"
        print(f"  {i:>3}  {len(cluster):>4}  {cj:>7.2f}  {tj:>7.2f}  "
              f"{marker_c:>9}  {marker_t:>9}  {row0[:40]}")

    s_rate = (survivors_title_preserved / survivors_total) if survivors_total else 0
    f_rate = (failures_title_preserved / failures_total) if failures_total else 0
    margin = s_rate - f_rate

    print(f"\n# preservation rates:")
    print(f"  cliff-survivors (n={survivors_total}): title-preserved = "
          f"{survivors_title_preserved}/{survivors_total} = {s_rate:.2f}")
    print(f"  cliff-failures  (n={failures_total}): title-preserved = "
          f"{failures_title_preserved}/{failures_total} = {f_rate:.2f}")
    print(f"  margin (s - f): {margin:+.2f}")

    if margin >= 0.3:
        status = "confirmed"
        msg = (
            f"Confirmed: title-only clustering preserves cliff-survivors at "
            f"{s_rate:.2f} rate vs cliff-failures at {f_rate:.2f} (margin "
            f"{margin:+.2f}). Verdict-in-name interpretation earns empirical "
            f"support — clusters with verdict-bearing topic-names cluster "
            f"robustly from titles alone, clusters with body-bearing substance "
            f"do not. read-path-author-side discipline validated."
        )
    elif margin >= 0.1:
        status = "refined"
        msg = (
            f"Refined: survivors preserved at {s_rate:.2f}, failures at "
            f"{f_rate:.2f}, margin {margin:+.2f}. Direction supports verdict-"
            f"in-name interpretation but signal is weak — small sample (n="
            f"{survivors_total}+{failures_total}=16) and generalist embedder "
            f"(MiniLM) limit confidence. Worth re-running with E5 instruction-"
            f"tuned embedder before lifting status."
        )
    else:
        status = "rejected"
        msg = (
            f"Rejected: title-preservation rates similar between cliff-survivors "
            f"({s_rate:.2f}) and cliff-failures ({f_rate:.2f}), margin "
            f"{margin:+.2f}. The verdict-in-name interpretation is OVERFIT — "
            f"the cliff content signature reflects a different driver, possibly "
            f"message-length distribution or kind composition. Worth direct "
            f"regression instead of categorical interpretation."
        )

    emit_hypothesis(name=HYPOTHESIS_NAME, message=msg, status=status)
    print(f"\n  hypothesis status: {status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
