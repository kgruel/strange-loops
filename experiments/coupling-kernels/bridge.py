"""Bridge clusters experiment — does cross-kind structure-reveal find
implicit category-bridges that the kind-taxonomy hides?

Pulls fold-deduped substantive items across {decision, thread, task, cite,
plan, observation, hypothesis, handoff} from the project store. Embeds
under TWO E5 instructions:

  mechanism: "Group these items by the underlying mechanism or primitive
              they describe."  (decision-vocabulary)
  concern:   "Group these items by the design concern or area of work each
              item participates in."  (cross-kind-vocabulary)

Then for each clustering, reports:
  - kind-purity distribution per cluster (rhetorical-mode confound check)
  - count of cross-kind components (≥2 distinct kinds with ≥2 items)
  - top mixed clusters with members tagged by kind
  - per-cluster knowledge-lifecycle profile (which kinds present)

The hypothesis: under the right instruction, decisions+threads+tasks+cites
that share a concern cluster together — revealing concepts whose knowledge
is distributed across kinds. Decision-only clusters = frozen. Thread-only =
in-flight. Task-only = shape without justification. Mixed = healthy.
"""
from __future__ import annotations
import sqlite3
import json
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "experiments" / "coupling-kernels" / "cache"
DB = REPO / ".loops" / "data" / "project.db"

KINDS_UPSERT = {"decision", "thread", "task", "plan", "observation", "hypothesis"}
KINDS_COLLECT = {"cite", "handoff"}
KINDS_ALL = KINDS_UPSERT | KINDS_COLLECT

INSTRUCTIONS = {
    "mechanism": "Group these items by the underlying mechanism or "
                 "primitive they describe.",
    "concern": "Group these items by the design concern or area of work "
               "each item participates in.",
}


def load_all_kinds(min_chars: int = 50) -> list[dict]:
    """Fold-deduped substantive items across all substantive kinds.

    For upsert kinds (decision, thread, task, plan, observation,
    hypothesis): keep latest fact per (kind, key) where key is topic or
    name. For collect kinds (cite, handoff): keep every fact as a distinct
    row. Filter to message length ≥ min_chars.
    """
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = []

    # Upsert kinds: latest fact per (kind, key)
    upsert_kinds_sql = ",".join(f"'{k}'" for k in KINDS_UPSERT)
    cur = conn.execute(f"""
        SELECT kind, payload, ts, id FROM facts
        WHERE kind IN ({upsert_kinds_sql})
          AND length(coalesce(json_extract(payload,'$.message'),'')) >= ?
        ORDER BY ts DESC
    """, (min_chars,))
    seen = set()
    for r in cur:
        payload = json.loads(r["payload"])
        key = payload.get("topic") or payload.get("name")
        if not key:
            continue
        ck = (r["kind"], key)
        if ck in seen:
            continue
        seen.add(ck)
        rows.append({
            "kind": r["kind"],
            "key": key,
            "topic": key,  # legacy field name used by some helpers
            "message": payload.get("message", ""),
            "status": payload.get("status", ""),
            "ts": r["ts"],
            "id": r["id"],
        })

    # Collect kinds: every fact distinct
    collect_kinds_sql = ",".join(f"'{k}'" for k in KINDS_COLLECT)
    cur = conn.execute(f"""
        SELECT kind, payload, ts, id FROM facts
        WHERE kind IN ({collect_kinds_sql})
          AND length(coalesce(json_extract(payload,'$.message'),'')) >= ?
        ORDER BY ts DESC
    """, (min_chars,))
    for r in cur:
        payload = json.loads(r["payload"])
        rows.append({
            "kind": r["kind"],
            "key": r["id"][:8],
            "topic": payload.get("ref", "") or r["id"][:8],
            "message": payload.get("message", ""),
            "status": payload.get("status", ""),
            "ts": r["ts"],
            "id": r["id"],
        })

    conn.close()
    return rows


def format_e5(task: str, text: str) -> str:
    return f"Instruct: {task}\nQuery: {text}"


def embed_e5(texts: list[str], task_label: str) -> np.ndarray:
    cache_path = CACHE / f"proj_e5_allkinds_{task_label}.npz"
    if cache_path.exists():
        E = np.load(cache_path)["E"]
        if E.shape[0] == len(texts):
            print(f"  cache hit: {cache_path.name}  shape={E.shape}", flush=True)
            return E
        print(f"  cache stale (n={E.shape[0]} vs {len(texts)}), regenerating", flush=True)
    from sentence_transformers import SentenceTransformer
    print(f"  loading multilingual-e5-large-instruct...", flush=True)
    model = SentenceTransformer("intfloat/multilingual-e5-large-instruct")
    task = INSTRUCTIONS[task_label]
    inputs = [format_e5(task, t) for t in texts]
    print(f"  encoding {len(inputs)} items under '{task_label}'...", flush=True)
    E = np.array(model.encode(
        inputs, normalize_embeddings=True, show_progress_bar=True,
        batch_size=8,
    ))
    np.savez(cache_path, E=E)
    print(f"  saved: {cache_path.name}", flush=True)
    return E


def cosine_dist(E: np.ndarray) -> np.ndarray:
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    return 1.0 - (norm @ norm.T)


def dog_kernel(D: np.ndarray, sigma_e: float, ratio: float = 2.0) -> np.ndarray:
    sigma_i = ratio * sigma_e
    return (np.exp(-(D**2) / (2 * sigma_e**2))
            - (sigma_e / sigma_i) * np.exp(-(D**2) / (2 * sigma_i**2)))


def positive_components(K: np.ndarray) -> list[list[int]]:
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


def find_richness_scale(D: np.ndarray) -> tuple[float, list[list[int]]]:
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5]
    best_s, best_richness, best_comps = None, -1, None
    for p in pcts:
        s = float(np.percentile(off, p))
        K = dog_kernel(D, s)
        comps = positive_components(K)
        non_trivial = [c for c in comps if len(c) >= 3]
        if len(non_trivial) > best_richness:
            best_richness = len(non_trivial)
            best_s = s
            best_comps = comps
    return best_s, best_comps


def kind_distribution(comp: list[int], rows: list[dict]) -> Counter:
    return Counter(rows[i]["kind"] for i in comp)


def kind_purity(comp: list[int], rows: list[dict]) -> float:
    """Fraction of cluster from the dominant kind. 1.0 = single kind."""
    kd = kind_distribution(comp, rows)
    return kd.most_common(1)[0][1] / len(comp)


def is_cross_kind(comp: list[int], rows: list[dict],
                  min_kinds: int = 2, min_per_kind: int = 2) -> bool:
    """A cluster is cross-kind if ≥ min_kinds kinds each have ≥ min_per_kind members."""
    kd = kind_distribution(comp, rows)
    n_qualifying = sum(1 for c in kd.values() if c >= min_per_kind)
    return n_qualifying >= min_kinds


def report_clustering(D: np.ndarray, rows: list[dict], label: str) -> None:
    s, comps = find_richness_scale(D)
    non_trivial = [c for c in comps if len(c) >= 3]
    print(f"\n## {label}  (auto-scale σ={s:.4f})")
    print(f"  N={len(rows)}  components={len(comps)}  non_trivial≥3={len(non_trivial)}")

    # Kind-purity distribution
    purities = [kind_purity(c, rows) for c in non_trivial]
    if purities:
        n_pure = sum(1 for p in purities if p >= 0.9)
        n_dom = sum(1 for p in purities if 0.7 <= p < 0.9)
        n_mixed = sum(1 for p in purities if p < 0.7)
        print(f"  kind-purity: pure≥0.9: {n_pure}  dominant 0.7-0.9: {n_dom}  "
              f"mixed<0.7: {n_mixed}")
        print(f"  mean purity: {np.mean(purities):.2f}  median: "
              f"{np.median(purities):.2f}")

    # Cross-kind clusters (≥2 kinds × ≥2 members)
    cross = [c for c in non_trivial if is_cross_kind(c, rows)]
    print(f"  cross-kind clusters (≥2 kinds ×≥2 members): {len(cross)}")

    # Top components by size
    print(f"\n  ## top non-trivial components")
    for ci, comp in enumerate(sorted(non_trivial, key=len, reverse=True)[:12], 1):
        kd = kind_distribution(comp, rows)
        kd_str = " ".join(f"{k}:{v}" for k, v in kd.most_common())
        purity = kind_purity(comp, rows)
        cross_marker = " ★" if is_cross_kind(comp, rows) else ""
        print(f"\n  C{ci}  size={len(comp):<3}  purity={purity:.2f}  "
              f"kinds=[{kd_str}]{cross_marker}")
        # 6 sample items, sorted by message length
        sample = sorted(comp, key=lambda i: -len(rows[i]["message"]))[:6]
        for i in sample:
            r = rows[i]
            kind_tag = f"[{r['kind']:<11}]"
            label_str = r["topic"] if r["topic"] else r["key"]
            status = f" ({r['status']})" if r["status"] else ""
            print(f"    {kind_tag} {label_str}{status}")

    # Highlight pure cross-kind bridges (low purity, multiple kinds)
    print(f"\n  ## strongest bridges (lowest kind-purity, ≥2 kinds × ≥2 members)")
    bridges = sorted(
        [c for c in non_trivial if is_cross_kind(c, rows)],
        key=lambda c: kind_purity(c, rows),
    )[:6]
    for ci, comp in enumerate(bridges, 1):
        kd = kind_distribution(comp, rows)
        kd_str = " ".join(f"{k}:{v}" for k, v in kd.most_common())
        purity = kind_purity(comp, rows)
        print(f"\n  B{ci}  size={len(comp):<3}  purity={purity:.2f}  "
              f"kinds=[{kd_str}]")
        # all members for bridges (they're the interesting ones)
        sample = sorted(comp, key=lambda i: (rows[i]["kind"], -len(rows[i]["message"])))
        for i in sample[:10]:
            r = rows[i]
            kind_tag = f"[{r['kind']:<11}]"
            print(f"    {kind_tag} {r['topic']}")
        if len(comp) > 10:
            print(f"    ... and {len(comp)-10} more")


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def compare_instructions(comps_a: list[list[int]], comps_b: list[list[int]],
                          rows: list[dict], label_a: str, label_b: str) -> None:
    print(f"\n## reshuffle: {label_a} → {label_b}")
    a_big = sorted([c for c in comps_a if len(c) >= 3], key=len, reverse=True)
    b_big = sorted([c for c in comps_b if len(c) >= 3], key=len, reverse=True)
    if not a_big or not b_big:
        print("  (no comparable clusters)")
        return
    print(f"  {'A-cluster':<24} {'best-B':<24} {'jaccard':>7}  composition")
    for ai, ac in enumerate(a_big[:10]):
        best_b, best_j = -1, -1.0
        for bi, bc in enumerate(b_big):
            j = jaccard(ac, bc)
            if j > best_j:
                best_j = j
                best_b = bi
        a_kd = kind_distribution(ac, rows).most_common()
        a_kd_str = "/".join(f"{k}:{v}" for k, v in a_kd[:3])
        a_label = f"A-C{ai+1}(n={len(ac)},{a_kd_str})"
        b_label = (f"B-C{best_b+1}(n={len(b_big[best_b])})"
                   if best_b >= 0 else "(none)")
        print(f"  {a_label:<24} {b_label:<24} {best_j:>6.2f}")


def main():
    rows = load_all_kinds(min_chars=50)
    print(f"# loaded {len(rows)} substantive items across kinds:")
    kc = Counter(r["kind"] for r in rows)
    for k, v in kc.most_common():
        print(f"    {k:<13}  {v}")

    # Save manifest for reproducibility
    manifest = CACHE / "project_all_kinds_manifest.json"
    json.dump([{k: v for k, v in r.items() if k != "id"} for r in rows],
              open(manifest, "w"), indent=2)
    print(f"  manifest saved: {manifest.name}")

    texts = [r["message"] for r in rows]

    print("\n# embedding under both instructions")
    E_mech = embed_e5(texts, "mechanism")
    E_con = embed_e5(texts, "concern")

    D_mech = cosine_dist(E_mech)
    D_con = cosine_dist(E_con)

    report_clustering(D_mech, rows, "MECHANISM instruction")
    report_clustering(D_con, rows, "CONCERN instruction")

    # Reshuffle: do the two instructions agree on cluster boundaries?
    _, comps_mech = find_richness_scale(D_mech)
    _, comps_con = find_richness_scale(D_con)
    compare_instructions(comps_mech, comps_con, rows, "mechanism", "concern")
    compare_instructions(comps_con, comps_mech, rows, "concern", "mechanism")


if __name__ == "__main__":
    main()
