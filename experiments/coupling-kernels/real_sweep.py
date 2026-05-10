"""Apply the structure-revealer to actual project decisions.

Pipeline:
1. Load project_decisions.json (309 decisions from project store)
2. Filter to non-empty messages
3. Embed with both MiniLM and Gemini
4. Sweep Mexican-hat scale with percentile-based scales
5. Report component structure at each scale
6. For interesting (multi-component) scales: sample topics per component
   to see whether the kernel finds namespace boundaries OR cross-namespace
   latent structure

The genuinely informative outcome is the second — the kernel finding
organizations that the human-imposed namespace taxonomy missed.
"""

from __future__ import annotations
import os, json
from pathlib import Path
from itertools import combinations
from collections import Counter

import numpy as np


def load_decisions():
    d = json.load(open("experiments/coupling-kernels/cache/project_decisions.json"))
    items = []
    for sec in d["sections"]:
        if sec["kind"] == "decision":
            items.extend(sec["items"])
    rows = []
    for i in items:
        msg = i["payload"].get("message", "")
        topic = i["payload"].get("topic", "")
        if len(msg) < 50:  # skip stubs
            continue
        rows.append({"topic": topic, "message": msg, "id": i["id"]})
    return rows


def embed_minilm(texts):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("all-MiniLM-L6-v2")
    return np.array(m.encode(texts, normalize_embeddings=False, show_progress_bar=False))


def embed_gemini(texts):
    """Embed with checkpointing and 429 backoff.

    Saves progress to experiments/coupling-kernels/cache/proj_gemini_progress.npy after every 25
    successful embeds, so a 429 mid-run only loses the current batch.
    """
    import time
    from google import genai
    from google.genai import errors as genai_errors

    env_path = Path.home() / "Code" / "discord-scraper" / ".env"
    key = None
    for line in env_path.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
    client = genai.Client(api_key=key)

    progress_path = Path("experiments/coupling-kernels/cache/proj_gemini_progress.npy")
    if progress_path.exists():
        out = list(np.load(progress_path))
        print(f"    resuming from checkpoint: {len(out)}/{len(texts)}", flush=True)
    else:
        out = []

    i = len(out)
    while i < len(texts):
        if i % 25 == 0:
            print(f"    gemini {i}/{len(texts)}", flush=True)
        try:
            r = client.models.embed_content(
                model="gemini-embedding-001", contents=texts[i]
            )
            vec = r.embeddings[0].values if hasattr(r, "embeddings") else r.embedding.values
            out.append(vec)
            i += 1
            # checkpoint every 25
            if i % 25 == 0:
                np.save(progress_path, np.array(out))
            # gentle pacing — stay under per-minute quota
            time.sleep(0.4)
        except genai_errors.ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait = 60
                print(f"    429 at item {i}, sleeping {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    np.save(progress_path, np.array(out))
    return np.array(out)


def cosine_dist(E):
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    S = norm @ norm.T
    return 1.0 - S


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


def sweep_and_report(D, label, rows, n_scales=8):
    print(f"\n## {label}")
    # off-diagonal distances
    off = D[np.triu_indices(D.shape[0], k=1)]
    print(f"  N={D.shape[0]}  distance: min={off.min():.3f}  "
          f"median={np.median(off):.3f}  max={off.max():.3f}")

    # transition band sits near the minimum-distance percentiles, not median
    # (kernel collapses to unity well before P50 for large N)
    pcts = [0.1, 0.3, 0.5, 1, 2, 4, 8, 16]
    scales = [float(np.percentile(off, p)) for p in pcts]

    print(f"  {'pct':>4}  {'σ_e':>5}  {'#comp':>5}  {'sing':>5}  "
          f"{'biggest comps (size, top namespace)':<60}")
    print(f"  {'-'*4}  {'-'*5}  {'-'*5}  {'-'*5}  {'-'*60}")
    for pct, s in zip(pcts, scales):
        K = dog_kernel(D, s)
        comps = positive_components(K)
        sizes = sorted([len(c) for c in comps], reverse=True)
        singletons = sum(1 for x in sizes if x == 1)
        non_trivial = [c for c in comps if len(c) >= 3]

        # report: size + dominant namespace for top 4 non-trivial components
        summary = []
        for c in sorted(non_trivial, key=len, reverse=True)[:4]:
            ns = Counter(rows[i]["topic"].split("/", 1)[0] for i in c)
            top_ns, top_n = ns.most_common(1)[0]
            purity = top_n / len(c)
            summary.append(f"({len(c)},{top_ns}:{purity:.0%})")
        print(f"  {int(pct):>3}%  {s:>5.3f}  {len(comps):>5}  "
              f"{singletons:>5}  {' '.join(summary):<60}")

    # detail report at the most interesting scale (where #comp is moderate)
    print(f"\n  ## detail at scale where structure is richest")
    best_scale = None
    best_richness = -1
    for s in scales:
        K = dog_kernel(D, s)
        comps = positive_components(K)
        non_trivial = [c for c in comps if len(c) >= 3]
        # richness: number of non-trivial components
        if len(non_trivial) > best_richness:
            best_richness = len(non_trivial)
            best_scale = s
    print(f"  scale σ_e = {best_scale:.3f}, "
          f"{best_richness} non-trivial components ≥3")
    K = dog_kernel(D, best_scale)
    comps = positive_components(K)
    non_trivial = sorted([c for c in comps if len(c) >= 3], key=len, reverse=True)
    for ci, comp in enumerate(non_trivial[:6]):
        ns = Counter(rows[i]["topic"].split("/", 1)[0] for i in comp)
        top_ns_list = ns.most_common(3)
        print(f"\n  Component {ci+1}  size={len(comp)}  namespaces: "
              + ", ".join(f"{k}:{v}" for k, v in top_ns_list))
        # 4 sample topics
        sample_idx = sorted(comp,
            key=lambda i: -len(rows[i]["message"]))[:4]
        for i in sample_idx:
            t = rows[i]["topic"]
            print(f"    • {t}")


def main():
    rows = load_decisions()
    texts = [r["message"] for r in rows]
    print(f"# {len(rows)} decisions (filtered to msg ≥ 50 chars)")

    # MiniLM
    minilm_path = Path("experiments/coupling-kernels/cache/proj_minilm.npz")
    if minilm_path.exists():
        E_mini = np.load(minilm_path)["E"]
        print(f"  loaded cached MiniLM embeddings: {E_mini.shape}")
    else:
        print("  embedding with MiniLM...")
        E_mini = embed_minilm(texts)
        np.savez(minilm_path, E=E_mini)

    # Gemini
    gemini_path = Path("experiments/coupling-kernels/cache/proj_gemini.npz")
    if gemini_path.exists():
        E_gem = np.load(gemini_path)["E"]
        print(f"  loaded cached Gemini embeddings: {E_gem.shape}")
    else:
        print(f"  embedding with Gemini ({len(texts)} calls)...")
        E_gem = embed_gemini(texts)
        np.savez(gemini_path, E=E_gem)

    # Sweep both
    D_mini = cosine_dist(E_mini)
    D_gem = cosine_dist(E_gem)
    sweep_and_report(D_mini, "MiniLM (all-MiniLM-L6-v2, 384d)", rows)
    sweep_and_report(D_gem, "Gemini (gemini-embedding-001, 3072d)", rows)


if __name__ == "__main__":
    main()
