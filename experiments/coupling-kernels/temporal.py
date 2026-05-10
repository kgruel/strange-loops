"""Temporal stratification of the cross-kind corpus.

Cumulative time-windows over 70 days of project history. For each window,
re-cluster the subset of items active by that date and report:
  - cluster count at richness scale
  - mean kind-purity / cross-kind bridge count
  - cluster lineage: jaccard match against previous window
    (persistent / emerging / fragmenting / dissolving)
  - kind-mix evolution (when did each kind become practice?)

The point: make the project's intellectual history visible as a topology
trajectory, not a snapshot. Confirms or disconfirms hypothesis
concept-drift-temporal. Also addresses the pre-apparatus-vs-stale
ambiguity from the triage diagnostic — by *seeing* when each cluster
formed, we know whether decision-only-ness predates the apparatus or
postdates it.

Reuses the cached E5/concern embeddings from bridge.py — no new
embedding work, just subset-and-recluster.
"""
from __future__ import annotations
import json
import time
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "experiments" / "coupling-kernels" / "cache"
MANIFEST = CACHE / "project_all_kinds_manifest.json"
EMBED = CACHE / "proj_e5_allkinds_concern.npz"

# Apparatus-maturity ts from triage.py
APPARATUS_MATURE_TS = 1777176000.0  # 2026-04-25

# Cumulative windows: 5 cuts at 14-day intervals over 70-day span.
WINDOW_LABELS = [
    "T1 (Mar 14, +14d)",
    "T2 (Mar 28, +28d)",
    "T3 (Apr 11, +42d)",
    "T4 (Apr 25, +56d, apparatus-mature)",
    "T5 (May 9, +70d, today)",
]


def load_corpus():
    rows = json.load(open(MANIFEST))
    E = np.load(EMBED)["E"]
    assert len(rows) == E.shape[0], (
        f"manifest n={len(rows)} but embeddings n={E.shape[0]}"
    )
    return rows, E


def window_cutoffs(rows: list[dict]) -> list[float]:
    ts = [r["ts"] for r in rows]
    t0 = min(ts)
    return [t0 + d * 86400 for d in (14, 28, 42, 56, 70 + 1)]


def subset_by_ts(rows: list[dict], E: np.ndarray, t_max: float):
    keep = [i for i, r in enumerate(rows) if r["ts"] <= t_max]
    return keep, E[keep]


def cosine_dist(E):
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    return 1.0 - (norm @ norm.T)


def dog_kernel(D, sigma_e, ratio=2.0):
    sigma_i = ratio * sigma_e
    return (np.exp(-(D**2) / (2 * sigma_e**2))
            - (sigma_e / sigma_i) * np.exp(-(D**2) / (2 * sigma_i**2)))


def positive_components(K):
    n = K.shape[0]
    K = K.copy()
    np.fill_diagonal(K, 0)
    visited = [False] * n
    comps = []
    for start in range(n):
        if visited[start]:
            continue
        stack, comp = [start], []
        while stack:
            v = stack.pop()
            if visited[v]:
                continue
            visited[v] = True
            comp.append(v)
            for u in range(n):
                if not visited[u] and K[v, u] > 0:
                    stack.append(u)
        comps.append(sorted(comp))
    return comps


def find_richness_scale(D):
    if D.shape[0] < 5:
        return 0.0, []
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5]
    best_s, best_richness, best_comps = None, -1, None
    for p in pcts:
        s = float(np.percentile(off, p))
        if s == 0:
            continue
        K = dog_kernel(D, s)
        comps = positive_components(K)
        non_trivial = [c for c in comps if len(c) >= 3]
        if len(non_trivial) > best_richness:
            best_richness = len(non_trivial)
            best_s = s
            best_comps = comps
    return best_s, best_comps if best_comps else []


def kind_mix(comp_global: list[int], rows: list[dict]) -> Counter:
    return Counter(rows[i]["kind"] for i in comp_global)


def kind_purity(comp_global: list[int], rows: list[dict]) -> float:
    km = kind_mix(comp_global, rows)
    return km.most_common(1)[0][1] / len(comp_global) if comp_global else 0.0


def is_cross_kind(comp_global: list[int], rows: list[dict],
                  min_kinds: int = 2, min_per_kind: int = 2) -> bool:
    km = kind_mix(comp_global, rows)
    return sum(1 for c in km.values() if c >= min_per_kind) >= min_kinds


def cluster_label(comp_global: list[int], rows: list[dict]) -> str:
    """Short readable label for a cluster (top 2 namespaces or topic stems)."""
    topics = [rows[i].get("topic") or rows[i].get("key", "") for i in comp_global]
    namespaces = [t.split("/", 1)[0] for t in topics if t]
    if namespaces:
        ns_count = Counter(namespaces)
        return ", ".join(k for k, _ in ns_count.most_common(2))
    return "?"


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def lineage_match(comps_now: list[list[int]],
                  comps_prev: list[list[int]]) -> list[tuple[int, int, float]]:
    """For each cluster in comps_now, find best-matching prev cluster.
    Returns (now_idx, prev_idx_or_-1, jaccard). Operates on global indices.
    """
    out = []
    for ni, nc in enumerate(comps_now):
        if not comps_prev:
            out.append((ni, -1, 0.0))
            continue
        best_p, best_j = -1, -1.0
        for pi, pc in enumerate(comps_prev):
            j = jaccard(nc, pc)
            if j > best_j:
                best_j = j
                best_p = pi
        out.append((ni, best_p, best_j))
    return out


def render_window(label: str, rows: list[dict], comps_global: list[list[int]],
                  scale: float, prev_comps: list[list[int]] | None,
                  ts_max: float) -> dict:
    non_trivial = [c for c in comps_global if len(c) >= 3]
    n_kept = len({i for c in comps_global for i in c}) if comps_global else 0
    print(f"\n## {label}  σ={scale:.4f}  n_items={n_kept}  "
          f"non_trivial≥3={len(non_trivial)}")

    # Kind counts in window
    items_in_window = {i for c in comps_global for i in c}
    kind_counts = Counter(rows[i]["kind"] for i in items_in_window)
    kc_str = " ".join(f"{k}:{v}" for k, v in kind_counts.most_common())
    print(f"   kinds: {kc_str}")

    # Has the engagement-apparatus arrived in this window?
    has_plan = bool(kind_counts.get("plan", 0))
    has_cite = bool(kind_counts.get("cite", 0))
    has_hyp = bool(kind_counts.get("hypothesis", 0))
    arrival = []
    if has_plan: arrival.append("plan")
    if has_cite: arrival.append("cite")
    if has_hyp: arrival.append("hypothesis")
    print(f"   apparatus present: {', '.join(arrival) or '(only base kinds)'}")

    # Cross-kind / purity stats
    cross = [c for c in non_trivial if is_cross_kind(c, rows)]
    purities = [kind_purity(c, rows) for c in non_trivial]
    if purities:
        print(f"   bridges (≥2 kinds × ≥2 members): {len(cross)}  "
              f"mean_purity: {np.mean(purities):.2f}")

    # Lineage tracking
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

    # Top 8 clusters with lineage
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


def overall_summary(window_results: list[dict]):
    print("\n" + "=" * 72)
    print("# Overall trajectory")
    print(f"  {'window':<38} {'n':>4} {'comp':>5} {'br':>3} {'pur':>5}")
    for w in window_results:
        print(f"  {w['label']:<38} {w['n_items']:>4} "
              f"{w['n_non_trivial']:>5} {w['n_bridges']:>3} "
              f"{w['mean_purity']:>5.2f}")

    # Bridge-count growth
    print(f"\n  bridge-count trajectory:",
          " → ".join(str(w["n_bridges"]) for w in window_results))
    # Item growth
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
        # Translate local indices back to global
        comps_global = [[keep[li] for li in c] for c in comps_local]
        result = render_window(label, rows, comps_global, s,
                                prev_comps_global, cutoff)
        window_results.append(result)
        prev_comps_global = comps_global

    overall_summary(window_results)


if __name__ == "__main__":
    main()
