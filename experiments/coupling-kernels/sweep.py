"""Mexican-hat scale sweep on saved embeddings.

Tests the article's claim: kernel scale determines emergent K.
- Tight scale: many competing clusters (Mexican-hat surfaces multiple positions)
- Loose scale: collapse to unity (everything positively coupled)

Method:
- Load embeddings from run.py
- Distance d_ij = 1 - cosine_sim
- DoG kernel: K_ij = exp(-d²/σ_e²) - α · exp(-d²/σ_i²)
  with σ_i = ratio · σ_e, α = 1
- For each scale σ_e:
  - Count connected components in the positive-edge subgraph
    (components reachable via K_ij > 0 edges)
  - Eigengap on Laplacian of the |K| graph: where is the largest gap?
  - Spectral clustering at k=2 → substance accuracy
  - Spectral clustering at k=3 → style accuracy

For comparison, also sweep a pure Gaussian kernel (the centroid baseline).
The Gaussian should show no emergent multi-cluster structure regardless of scale.
"""

from __future__ import annotations
import numpy as np
from itertools import permutations, combinations


def load(path: str = "/tmp/coupling_test/embeddings.npz"):
    z = np.load(path)
    return z["E"], list(z["ids"]), list(z["substance"]), list(z["style"]), str(z["model"][0])


def cosine_sim(E):
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    return norm @ norm.T


def dog_kernel(D, sigma_e, ratio=2.0):
    """Mexican-hat / DoG with proper amplitude weighting.

    K(d) = exp(-d²/(2σ_e²)) - (σ_e/σ_i) · exp(-d²/(2σ_i²))

    Narrow gaussian peaks at 1, wider gaussian peaks at σ_e/σ_i < 1.
    This gives short-range positive, medium-range negative, long-range
    decay — the classical cortical-column kernel.
    """
    sigma_i = ratio * sigma_e
    return (np.exp(-(D**2) / (2 * sigma_e**2))
            - (sigma_e / sigma_i) * np.exp(-(D**2) / (2 * sigma_i**2)))


def gaussian_kernel(D, sigma):
    return np.exp(-(D**2) / sigma**2)


def positive_components(K):
    """Connected components in the graph where edges = (K > 0)."""
    n = K.shape[0]
    np.fill_diagonal(K, 0)  # ignore self-loops
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


def eigengap(K):
    """Largest eigengap location on the normalized Laplacian of |K|."""
    A = np.abs(K)
    np.fill_diagonal(A, 0)
    d = A.sum(axis=1)
    d[d == 0] = 1
    D_inv_sqrt = np.diag(1.0 / np.sqrt(d))
    L = np.eye(A.shape[0]) - D_inv_sqrt @ A @ D_inv_sqrt
    eigs = np.sort(np.linalg.eigvalsh(L))
    gaps = np.diff(eigs)
    k_star = int(np.argmax(gaps)) + 1  # eigengap heuristic: k = argmax of gaps
    return k_star, eigs.tolist(), gaps.tolist()


def best_agreement(labels, truth):
    uniq_t = sorted(set(truth))
    uniq_l = sorted(set(labels))
    best = 0
    for perm in permutations(uniq_t, len(uniq_l)):
        mapping = dict(zip(uniq_l, perm))
        hits = sum(1 for l, t in zip(labels, truth) if mapping[l] == t)
        best = max(best, hits)
    return best


def spectral_label(K, k):
    from sklearn.cluster import SpectralClustering
    A = np.clip(np.abs(K), 0, None)
    np.fill_diagonal(A, 1.0)
    sc = SpectralClustering(
        n_clusters=k, affinity="precomputed",
        assign_labels="kmeans", random_state=0,
    )
    return sc.fit_predict(A).tolist()


def main():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/coupling_test/embeddings.npz"
    E, ids, substance, style, model = load(path)
    print(f"# loaded {len(ids)} embeddings from {model}")
    S = cosine_sim(E)
    D = 1.0 - S  # cosine distance ∈ [0, 2]
    np.fill_diagonal(D, 0.0)
    print(f"  distance range: [{D[D>0].min():.3f}, {D.max():.3f}]\n")

    # Sweep scales — chosen to span the distance range.
    # Most pairs have d ∈ [0.3, 0.8] given the cosine sims we saw.
    scales = [0.10, 0.20, 0.30, 0.40, 0.50, 0.65, 0.80, 1.00, 1.50]

    print("# DoG (Mexican-hat) sweep — σ_e varies, σ_i = 2σ_e, α=1")
    print(f"  {'σ_e':>5}  {'#pos+':>5}  {'#comps':>6}  {'eigen-k':>7}  "
          f"{'k=2/sub':>7}  {'k=3/sty':>7}  components")
    print(f"  {'-'*5}  {'-'*5}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*7}  {'-'*30}")
    for s in scales:
        K = dog_kernel(D, s)
        K_off = K.copy()
        np.fill_diagonal(K_off, 0)
        n_pos = int((K_off > 0).sum() // 2)  # undirected
        comps = positive_components(K.copy())
        comp_ids = [tuple(ids[i] for i in c) for c in comps]
        try:
            k_eig, _, _ = eigengap(K)
        except Exception:
            k_eig = -1
        try:
            l2 = spectral_label(K, 2)
            sub_hits = best_agreement(l2, substance)
        except Exception:
            sub_hits = -1
        try:
            l3 = spectral_label(K, 3)
            sty_hits = best_agreement(l3, style)
        except Exception:
            sty_hits = -1
        print(f"  {s:>5.2f}  {n_pos:>5}  {len(comps):>6}  {k_eig:>7}  "
              f"{sub_hits:>5}/6  {sty_hits:>5}/6  {comp_ids}")
    print()

    print("# Gaussian (uniform-positive baseline) sweep — same scales")
    print(f"  {'σ':>5}  {'eigen-k':>7}  {'k=2/sub':>7}  {'k=3/sty':>7}")
    print(f"  {'-'*5}  {'-'*7}  {'-'*7}  {'-'*7}")
    for s in scales:
        K = gaussian_kernel(D, s)
        try:
            k_eig, _, _ = eigengap(K)
        except Exception:
            k_eig = -1
        try:
            l2 = spectral_label(K, 2)
            sub_hits = best_agreement(l2, substance)
        except Exception:
            sub_hits = -1
        try:
            l3 = spectral_label(K, 3)
            sty_hits = best_agreement(l3, style)
        except Exception:
            sty_hits = -1
        print(f"  {s:>5.2f}  {k_eig:>7}  {sub_hits:>5}/6  {sty_hits:>5}/6")


if __name__ == "__main__":
    main()
