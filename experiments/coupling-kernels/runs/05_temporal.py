"""Temporal stratification — byte-equivalence verification anchor.

Pinned against fixtures/results_temporal.txt. Loads manifest + concern
embedding from fixtures/, exercises the harness (Corpus.load_manifest +
core.kernel + Query/run via injected rows+E), and renders identically
to the original temporal.py output.

Cumulative time-windows over 70 days. For each window: re-cluster the
subset active by that date, report cluster count + kind-mix + lineage
versus the previous window.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from collections import Counter

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core.corpus import load_manifest                       # noqa: E402
from core.kernel import cosine_dist, find_richness_scale    # noqa: E402
from core.compare import lineage_match                      # noqa: E402


FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
EMBED = FIXTURES / "proj_e5_allkinds_concern.npz"

APPARATUS_MATURE_TS = 1777176000.0  # 2026-04-25

WINDOW_LABELS = [
    "T1 (Mar 14, +14d)",
    "T2 (Mar 28, +28d)",
    "T3 (Apr 11, +42d)",
    "T4 (Apr 25, +56d, apparatus-mature)",
    "T5 (May 9, +70d, today)",
]


def load_corpus():
    rows = load_manifest(MANIFEST)
    E = np.load(EMBED)["E"]
    assert len(rows) == E.shape[0], (
        f"manifest n={len(rows)} but embeddings n={E.shape[0]}"
    )
    return rows, E


def window_cutoffs(rows):
    ts = [r["ts"] for r in rows]
    t0 = min(ts)
    return [t0 + d * 86400 for d in (14, 28, 42, 56, 70 + 1)]


def subset_by_ts(rows, E, t_max):
    keep = [i for i, r in enumerate(rows) if r["ts"] <= t_max]
    return keep, E[keep]


def kind_mix(comp, rows):
    return Counter(rows[i]["kind"] for i in comp)


def kind_purity(comp, rows):
    km = kind_mix(comp, rows)
    return km.most_common(1)[0][1] / len(comp) if comp else 0.0


def is_cross_kind(comp, rows, min_kinds=2, min_per_kind=2):
    km = kind_mix(comp, rows)
    return sum(1 for c in km.values() if c >= min_per_kind) >= min_kinds


def cluster_label(comp, rows):
    topics = [rows[i].get("topic") or rows[i].get("key", "") for i in comp]
    namespaces = [t.split("/", 1)[0] for t in topics if t]
    if namespaces:
        ns_count = Counter(namespaces)
        return ", ".join(k for k, _ in ns_count.most_common(2))
    return "?"


def render_window(label, rows, comps_global, scale, prev_comps, ts_max):
    non_trivial = [c for c in comps_global if len(c) >= 3]
    n_kept = len({i for c in comps_global for i in c}) if comps_global else 0
    print(f"\n## {label}  σ={scale:.4f}  n_items={n_kept}  "
          f"non_trivial≥3={len(non_trivial)}")

    items_in_window = {i for c in comps_global for i in c}
    kind_counts = Counter(rows[i]["kind"] for i in items_in_window)
    kc_str = " ".join(f"{k}:{v}" for k, v in kind_counts.most_common())
    print(f"   kinds: {kc_str}")

    has_plan = bool(kind_counts.get("plan", 0))
    has_cite = bool(kind_counts.get("cite", 0))
    has_hyp = bool(kind_counts.get("hypothesis", 0))
    arrival = []
    if has_plan: arrival.append("plan")
    if has_cite: arrival.append("cite")
    if has_hyp: arrival.append("hypothesis")
    print(f"   apparatus present: {', '.join(arrival) or '(only base kinds)'}")

    cross = [c for c in non_trivial if is_cross_kind(c, rows)]
    purities = [kind_purity(c, rows) for c in non_trivial]
    if purities:
        print(f"   bridges (≥2 kinds × ≥2 members): {len(cross)}  "
              f"mean_purity: {np.mean(purities):.2f}")

    sorted_now = sorted(non_trivial, key=len, reverse=True)
    if prev_comps is not None and prev_comps:
        prev_non_trivial = [c for c in prev_comps if len(c) >= 3]
        sorted_prev = sorted(prev_non_trivial, key=len, reverse=True)
        matches = lineage_match(sorted_now, sorted_prev)
        n_persist = sum(1 for _, _, j in matches if j >= 0.5)
        n_emerging = sum(1 for _, _, j in matches if j < 0.2)
        n_morphing = len(matches) - n_persist - n_emerging
        print(f"   lineage vs prev: persistent({n_persist})  "
              f"morphing({n_morphing})  emerging/new({n_emerging})")
    else:
        matches = [(i, -1, 0.0) for i in range(len(sorted_now))]

    print(f"\n   top clusters")
    sorted_prev = (sorted([c for c in prev_comps if len(c) >= 3],
                          key=len, reverse=True)
                   if prev_comps else [])
    for ni, prev_i, j in matches[:8]:
        comp = sorted_now[ni]
        km = kind_mix(comp, rows)
        kd_str = " ".join(f"{k}:{v}" for k, v in km.most_common())
        cross_marker = "★" if is_cross_kind(comp, rows) else " "
        lab = cluster_label(comp, rows)
        if prev_i == -1:
            lineage = "new"
        elif j >= 0.5:
            prev_size = len(sorted_prev[prev_i])
            lineage = f"⟸C{prev_i+1}({prev_size}) j={j:.2f}"
        elif j >= 0.2:
            lineage = f"morph⟸C{prev_i+1} j={j:.2f}"
        else:
            lineage = f"new (best j={j:.2f})"
        print(f"   {cross_marker} C{ni+1} n={len(comp):<3} {lab:<24} "
              f"[{kd_str:<32}]  {lineage}")

    return {
        "label": label,
        "n_items": n_kept,
        "n_non_trivial": len(non_trivial),
        "n_bridges": len(cross),
        "mean_purity": float(np.mean(purities)) if purities else 0.0,
        "kind_counts": dict(kind_counts),
        "comps_global": comps_global,
    }


def overall_summary(window_results):
    print("\n" + "=" * 72)
    print("# Overall trajectory")
    print(f"  {'window':<38} {'n':>4} {'comp':>5} {'br':>3} {'pur':>5}")
    for w in window_results:
        print(f"  {w['label']:<38} {w['n_items']:>4} "
              f"{w['n_non_trivial']:>5} {w['n_bridges']:>3} "
              f"{w['mean_purity']:>5.2f}")

    print(f"\n  bridge-count trajectory:",
          " → ".join(str(w["n_bridges"]) for w in window_results))
    print(f"  item-count trajectory:   ",
          " → ".join(str(w["n_items"]) for w in window_results))


def main():
    rows, E = load_corpus()
    cuts = window_cutoffs(rows)
    print(f"# corpus: {len(rows)} items, "
          f"first={time.strftime('%Y-%m-%d', time.localtime(min(r['ts'] for r in rows)))}, "
          f"last={time.strftime('%Y-%m-%d', time.localtime(max(r['ts'] for r in rows)))}")
    print(f"# windows (cumulative, +14d each):")
    for c, lab in zip(cuts, WINDOW_LABELS):
        n = sum(1 for r in rows if r["ts"] <= c)
        date = time.strftime("%Y-%m-%d", time.localtime(c))
        marker = " ◀── apparatus-mature" if abs(c - APPARATUS_MATURE_TS) < 86400 * 7 else ""
        print(f"    {lab:<40} cutoff={date}  n_active={n}{marker}")

    window_results = []
    prev_comps_global = None

    for cutoff, label in zip(cuts, WINDOW_LABELS):
        keep, E_sub = subset_by_ts(rows, E, cutoff)
        if E_sub.shape[0] < 5:
            print(f"\n## {label}  (skipped, n<5)")
            continue
        D = cosine_dist(E_sub)
        s, comps_local = find_richness_scale(D)
        comps_global = [[keep[li] for li in c] for c in comps_local]
        result = render_window(label, rows, comps_global, s,
                               prev_comps_global, cutoff)
        window_results.append(result)
        prev_comps_global = comps_global

    overall_summary(window_results)


if __name__ == "__main__":
    main()
