"""Test: does text-embedding-3-small organize council perspectives by
substance or by style?

Decisive comparison:
  avg cosine sim across (same-substance, different-style) pairs
  vs
  avg cosine sim across (different-substance, same-style) pairs

If substance > style: kernel-as-math is viable.
If style > substance: kernel collapses to half-metaphor on real text.
"""

from __future__ import annotations
import os, sys
from itertools import combinations

import numpy as np

from perspectives import PERSPECTIVES


MODEL_NAME = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")


def embed_all(texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    return np.array(model.encode(texts, normalize_embeddings=False))


def cosine_matrix(M: np.ndarray) -> np.ndarray:
    norm = M / np.linalg.norm(M, axis=1, keepdims=True)
    return norm @ norm.T


def main() -> None:
    ids = [p[0] for p in PERSPECTIVES]
    substance = {p[0]: p[1] for p in PERSPECTIVES}
    style = {p[0]: p[2] for p in PERSPECTIVES}
    texts = [p[3] for p in PERSPECTIVES]

    print(f"# embeddings: {MODEL_NAME}")
    E = embed_all(texts)
    print(f"  shape: {E.shape}\n")
    np.savez("/tmp/coupling_test/embeddings.npz",
             E=E, ids=np.array(ids),
             substance=np.array([substance[i] for i in ids]),
             style=np.array([style[i] for i in ids]),
             model=np.array([MODEL_NAME]))
    print(f"  saved → /tmp/coupling_test/embeddings.npz\n")

    S = cosine_matrix(E)

    # full matrix
    print("# pairwise cosine similarity")
    print("    " + "      ".join(ids))
    for i, row in enumerate(S):
        print(f"  {ids[i]} " + " ".join(f"{v:+.3f}" for v in row))
    print()

    # cell decomposition
    cells: dict[tuple[bool, bool], list[float]] = {
        (True, True): [],   # same-substance, same-style (= 0 by design)
        (True, False): [],  # same-substance, diff-style — substance signal
        (False, True): [],  # diff-substance, same-style — style signal
        (False, False): [], # diff both — baseline
    }
    pair_labels: list[tuple[str, str, str, str, float]] = []
    for i, j in combinations(range(len(ids)), 2):
        s_match = substance[ids[i]] == substance[ids[j]]
        t_match = style[ids[i]] == style[ids[j]]
        cells[(s_match, t_match)].append(float(S[i, j]))
        pair_labels.append((
            ids[i], ids[j],
            "s+" if s_match else "s-",
            "t+" if t_match else "t-",
            float(S[i, j]),
        ))

    print("# cell averages (mean cosine similarity per pair-type)")
    for key, vals in cells.items():
        s_lab = "same-sub" if key[0] else "diff-sub"
        t_lab = "same-sty" if key[1] else "diff-sty"
        if vals:
            print(f"  {s_lab}, {t_lab}  n={len(vals)}  "
                  f"mean={sum(vals)/len(vals):+.4f}  "
                  f"min={min(vals):+.4f}  max={max(vals):+.4f}")
        else:
            print(f"  {s_lab}, {t_lab}  n=0  (empty by design)")
    print()

    # decisive comparison
    sub_signal = sum(cells[(True, False)]) / len(cells[(True, False)])
    sty_signal = sum(cells[(False, True)]) / len(cells[(False, True)])
    print("# decisive comparison")
    print(f"  substance signal (same-sub, diff-sty): {sub_signal:+.4f}")
    print(f"  style signal     (diff-sub, same-sty): {sty_signal:+.4f}")
    print(f"  delta (substance - style):             {sub_signal - sty_signal:+.4f}")
    if sub_signal > sty_signal:
        print(f"  → SUBSTANCE WINS by {sub_signal - sty_signal:+.4f}")
    else:
        print(f"  → STYLE WINS by {sty_signal - sub_signal:+.4f}")
    print()

    # spectral clustering: does k=2 recover substance, does k=3 recover style?
    print("# spectral clustering on cosine affinity")
    try:
        from sklearn.cluster import SpectralClustering

        # k=2 (substance has 2 classes)
        sc2 = SpectralClustering(
            n_clusters=2, affinity="precomputed",
            assign_labels="kmeans", random_state=0,
        )
        # ensure non-negative for spectral
        A = np.clip(S, 0.0, 1.0)
        labels2 = sc2.fit_predict(A)
        print(f"  k=2 labels: {dict(zip(ids, labels2.tolist()))}")
        # check alignment with substance
        truth_sub = [substance[i] for i in ids]
        # cluster-truth agreement under best label permutation
        def best_agreement(labels, truth):
            uniq_t = sorted(set(truth))
            uniq_l = sorted(set(labels))
            from itertools import permutations
            best = 0
            for perm in permutations(uniq_t, len(uniq_l)):
                mapping = dict(zip(uniq_l, perm))
                hits = sum(1 for l, t in zip(labels, truth) if mapping[l] == t)
                best = max(best, hits)
            return best
        sub_hits = best_agreement(labels2, truth_sub)
        print(f"  k=2 vs substance: {sub_hits}/6")

        # k=3 (style has 3 classes)
        sc3 = SpectralClustering(
            n_clusters=3, affinity="precomputed",
            assign_labels="kmeans", random_state=0,
        )
        labels3 = sc3.fit_predict(A)
        print(f"  k=3 labels: {dict(zip(ids, labels3.tolist()))}")
        truth_sty = [style[i] for i in ids]
        sty_hits = best_agreement(labels3, truth_sty)
        print(f"  k=3 vs style:    {sty_hits}/6")
    except Exception as e:
        print(f"  (spectral clustering skipped: {e})")


if __name__ == "__main__":
    main()
