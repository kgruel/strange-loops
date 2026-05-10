"""Instruction-tuned embedder test: same content, different user-specified
axis, different topology?

Uses intfloat/multilingual-e5-large-instruct (~1.1GB, 560M params, runs on CPU).
The model accepts a task description as instruction prefix:

    Instruct: <task>
    Query: <text>

We embed the same 296 project decisions twice, under two structurally
different instructions, and compare the cluster structure the kernel finds.

If the instruction is a real parameter (not decorative), the two clusterings
should differ in *how* they organize the corpus — not just which items end
up in big-vs-small clusters.

Test pair:
  A: "Group these architectural decisions by the underlying mechanism or
      primitive they describe."
  B: "Group these architectural decisions by the system layer or domain
      area they affect."

Mechanism-based: ULID-* + fact-by-id should cluster (all about identity);
fold-* decisions should cluster regardless of which layer renders them.

Domain-based: rendering/* should cluster together regardless of mechanism;
atoms/* should cluster together regardless of mechanism.

If the same items end up in the same clusters under both instructions →
instruction is decorative, embedder is fixed-axis.
If items reshuffle into different clusters → instruction is a real
vocabulary parameter.
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter
from itertools import combinations

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "experiments" / "coupling-kernels" / "cache"
DECISIONS = CACHE / "project_decisions.json"

INSTRUCTIONS = {
    "mechanism": "Group these architectural decisions by the underlying "
                 "mechanism or primitive they describe.",
    "domain": "Group these architectural decisions by the system layer or "
              "domain area they affect.",
}


def format_e5(task: str, text: str) -> str:
    return f"Instruct: {task}\nQuery: {text}"


def load_decisions():
    d = json.load(open(DECISIONS))
    items = []
    for sec in d["sections"]:
        if sec["kind"] == "decision":
            items.extend(sec["items"])
    rows = []
    for i in items:
        msg = i["payload"].get("message", "")
        topic = i["payload"].get("topic", "")
        if len(msg) < 50:
            continue
        rows.append({"topic": topic, "message": msg, "id": i["id"]})
    return rows


def embed_e5(texts, task_label):
    cache_path = CACHE / f"proj_e5_{task_label}.npz"
    if cache_path.exists():
        E = np.load(cache_path)["E"]
        print(f"  cache hit: {cache_path.name}  shape={E.shape}", flush=True)
        return E
    from sentence_transformers import SentenceTransformer
    print(f"  loading multilingual-e5-large-instruct (one-time download "
          f"~1.1GB)...", flush=True)
    model = SentenceTransformer("intfloat/multilingual-e5-large-instruct")
    task = INSTRUCTIONS[task_label]
    inputs = [format_e5(task, t) for t in texts]
    print(f"  encoding {len(inputs)} decisions under '{task_label}'...",
          flush=True)
    E = np.array(model.encode(
        inputs, normalize_embeddings=True, show_progress_bar=True,
        batch_size=8,
    ))
    np.savez(cache_path, E=E)
    print(f"  saved: {cache_path.name}", flush=True)
    return E


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
    """Sweep tiny percentile band, return scale with most non-trivial comps."""
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0]
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


def render_components(comps, rows, label, max_components=10):
    non_trivial = sorted([c for c in comps if len(c) >= 3], key=len, reverse=True)
    print(f"\n## {label}: {len(non_trivial)} non-trivial components ≥3")
    for ci, comp in enumerate(non_trivial[:max_components]):
        ns = Counter(rows[i]["topic"].split("/", 1)[0] for i in comp)
        ns_str = ", ".join(f"{k}:{v}" for k, v in ns.most_common(3))
        print(f"\n  C{ci+1}  size={len(comp):<3}  ns: {ns_str}")
        # 6 sample topics, sorted by message length (longer = more substantive)
        sample = sorted(comp, key=lambda i: -len(rows[i]["message"]))[:6]
        for i in sample:
            print(f"    • {rows[i]['topic']}")


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b: return 1.0
    return len(a & b) / len(a | b)


def compare_clusterings(comps_a, comps_b, rows, label_a, label_b):
    """For each big component in A, find its best-matching component in B
    and report the Jaccard overlap. Tells us how much the same items stay
    together vs reshuffle under the alternative instruction.
    """
    print(f"\n## cluster reshuffle: {label_a} → {label_b}")
    print("    (for each large {label_a} cluster, best-matching {label_b} cluster)")
    a_big = sorted([c for c in comps_a if len(c) >= 3], key=len, reverse=True)
    b_big = sorted([c for c in comps_b if len(c) >= 3], key=len, reverse=True)
    if not a_big or not b_big:
        print("    (no comparable clusters)")
        return
    print(f"  {'A-cluster':<25} {'best-B':<25} {'jaccard':>7}  example topics")
    for ai, ac in enumerate(a_big[:8]):
        # best matching B cluster
        best_b, best_j = -1, -1.0
        for bi, bc in enumerate(b_big):
            j = jaccard(ac, bc)
            if j > best_j:
                best_j = j; best_b = bi
        a_label = f"A-C{ai+1} (n={len(ac)})"
        b_label = (f"B-C{best_b+1} (n={len(b_big[best_b])})"
                   if best_b >= 0 else "(none)")
        topics = [rows[i]["topic"].split("/", 1)[1] if "/" in rows[i]["topic"]
                  else rows[i]["topic"] for i in ac[:2]]
        print(f"  {a_label:<25} {b_label:<25} {best_j:>6.2f}  "
              f"{', '.join(topics)[:50]}")


def main():
    rows = load_decisions()
    texts = [r["message"] for r in rows]
    print(f"# {len(rows)} decisions\n")

    E_mech = embed_e5(texts, "mechanism")
    E_dom = embed_e5(texts, "domain")
    print()

    D_mech = cosine_dist(E_mech)
    D_dom = cosine_dist(E_dom)

    print(f"# E5/mechanism: distance min={D_mech[D_mech>0].min():.3f}  "
          f"median={np.median(D_mech[np.triu_indices(D_mech.shape[0],1)]):.3f}  "
          f"max={D_mech.max():.3f}")
    print(f"# E5/domain   : distance min={D_dom[D_dom>0].min():.3f}  "
          f"median={np.median(D_dom[np.triu_indices(D_dom.shape[0],1)]):.3f}  "
          f"max={D_dom.max():.3f}")

    s_mech, comps_mech = find_richness_scale(D_mech)
    s_dom, comps_dom = find_richness_scale(D_dom)
    print(f"\n# auto-scale: mechanism σ={s_mech:.4f}  domain σ={s_dom:.4f}")

    render_components(comps_mech, rows, "MECHANISM instruction")
    render_components(comps_dom, rows, "DOMAIN instruction")
    compare_clusterings(comps_mech, comps_dom, rows, "mechanism", "domain")
    compare_clusterings(comps_dom, comps_mech, rows, "domain", "mechanism")


if __name__ == "__main__":
    main()
