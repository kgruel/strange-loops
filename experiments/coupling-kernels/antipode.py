"""Antipode investigation — negative space mapping.

For each crystallized cluster C in the project's E5/mechanism projection:
  1. Compute centroid c̄ of the cluster's embeddings.
  2. Mechanical antipode: -c̄. Find nearest corpus facts to -c̄.
     (What's most-cosine-distant? Often unrelated topics — useful as a
     baseline.)
  3. LLM-synthesized antipodes: feed cluster items to a model with
     instruction to produce "conceptually opposite" descriptions.
     Embed those under the same E5/mechanism instruction. Find nearest
     corpus facts.
     (What does the conceptual negation look like, and does the corpus
     have anything near it?)

The two flavors answer different questions:
  - Mechanical: "what's the most-different content under this vocabulary?"
  - Synthesized: "what's the conceptual inverse, and have we explored it?"

Output table reads:
    cluster → antipode description → nearest corpus fact → distance
    {large distance, no fact} → unexplored design space
    {small distance} → both sides explored, the dichotomy is real
"""
from __future__ import annotations
import json
from pathlib import Path
from collections import Counter

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "experiments" / "coupling-kernels" / "cache"
DECISIONS = CACHE / "project_decisions.json"
INSTRUCTION = ("Group these architectural decisions by the underlying "
               "mechanism or primitive they describe.")


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
        if visited[start]: continue
        stack, comp = [start], []
        while stack:
            v = stack.pop()
            if visited[v]: continue
            visited[v] = True
            comp.append(v)
            for u in range(n):
                if not visited[u] and K[v, u] > 0:
                    stack.append(u)
        comps.append(sorted(comp))
    return comps


def find_richness_scale(D):
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
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


def gemini_key():
    env_path = Path.home() / "Code" / "discord-scraper" / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not found")


def synthesize_antipodes(client, cluster_topics: list[str],
                          cluster_messages: list[str], n: int = 3) -> list[str]:
    """Ask Gemini to produce n conceptually-opposite descriptions of the
    given cluster. Returns short descriptions (1-2 sentences each).
    """
    sample = "\n".join(
        f"  • {t}: {m[:200]}" for t, m in
        zip(cluster_topics[:5], cluster_messages[:5])
    )
    prompt = f"""You are mapping the negative space of a project's design decisions.

Below is a cluster of decisions that share an underlying mechanism or primitive.
Your task: describe {n} concepts that are CONCEPTUALLY OPPOSITE to this cluster.
Each opposite should:
  - Address the same problem domain (so it's a real alternative, not unrelated)
  - Invert the underlying mechanism (different primitive, different shape)
  - Be a coherent design choice someone could plausibly have made

Do not describe the cluster's flaws or critique it. Describe the *positive content*
of the inverse design — what someone choosing the opposite path would build.

CLUSTER:
{sample}

Output exactly {n} antipode descriptions, one per line, no numbering, no
preamble. Each line should be a single sentence (under 200 chars) describing
the opposite concept's core.
"""
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    text = r.text.strip()
    lines = [l.strip("- •*").strip() for l in text.split("\n") if l.strip()]
    # filter out lines that look like preamble/numbering
    out = []
    for l in lines:
        if l and not l.lower().startswith(("here", "antipode", "concept ", "opposite ")):
            out.append(l[:280])
        if len(out) >= n:
            break
    return out


def embed_under_instruction(model, texts: list[str]) -> np.ndarray:
    inputs = [format_e5(INSTRUCTION, t) for t in texts]
    return np.array(model.encode(
        inputs, normalize_embeddings=True, show_progress_bar=False, batch_size=8,
    ))


def nearest(corpus_E: np.ndarray, query_v: np.ndarray, exclude: set[int],
            top_k: int = 3) -> list[tuple[int, float]]:
    qn = query_v / np.linalg.norm(query_v)
    cn = corpus_E / np.linalg.norm(corpus_E, axis=1, keepdims=True)
    sims = cn @ qn
    order = np.argsort(-sims)
    out = []
    for idx in order:
        if int(idx) in exclude: continue
        out.append((int(idx), float(1.0 - sims[idx])))
        if len(out) >= top_k: break
    return out


def render(rows, cluster_idx: int, comp: list[int], antipodes_mech: list[tuple[int, float]],
           synth_pairs: list[tuple[str, list[tuple[int, float]]]]):
    cluster_topics = [rows[i]["topic"] for i in comp]
    ns = Counter(t.split("/", 1)[0] for t in cluster_topics)
    print(f"\n## Cluster {cluster_idx} (size={len(comp)})")
    print(f"  namespaces: {dict(ns.most_common(3))}")
    print(f"  members:")
    for t in cluster_topics[:6]:
        print(f"    • {t}")
    if len(cluster_topics) > 6:
        print(f"    ... and {len(cluster_topics)-6} more")

    print(f"\n  ▸ Mechanical antipode (-c̄, embedding-space inverse):")
    for idx, dist in antipodes_mech:
        print(f"    nearest fact: {rows[idx]['topic']:<55}  d={dist:.3f}")

    for ai, (desc, near) in enumerate(synth_pairs, 1):
        print(f"\n  ▸ Synthesized antipode {ai}: {desc[:120]}")
        for idx, dist in near:
            print(f"    nearest fact: {rows[idx]['topic']:<55}  d={dist:.3f}")


def main():
    rows = load_decisions()
    print(f"# {len(rows)} decisions loaded\n")

    # Load cached E5/mechanism embeddings
    E_path = CACHE / "proj_e5_mechanism.npz"
    if not E_path.exists():
        raise RuntimeError("Run e5_sweep.py first to populate E5 embeddings.")
    E = np.load(E_path)["E"]
    print(f"# E5/mechanism embeddings: shape={E.shape}")

    # Find clusters
    D = cosine_dist(E)
    s, comps = find_richness_scale(D)
    non_trivial = sorted([c for c in comps if 3 <= len(c) <= 12], key=len, reverse=True)
    print(f"# auto-scale σ={s:.4f}, {len(non_trivial)} well-defined clusters (3≤size≤12)")

    # Set up embedder for synthesized antipodes
    print("# loading E5 model for antipode embedding...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("intfloat/multilingual-e5-large-instruct")

    # Set up Gemini for synthesis
    print("# wiring Gemini for antipode synthesis...")
    from google import genai
    client = genai.Client(api_key=gemini_key())

    # Process each cluster
    for ci, comp in enumerate(non_trivial, 1):
        excl = set(comp)
        cluster_E = E[comp]
        centroid = cluster_E.mean(axis=0)
        mech_anti = -centroid
        nearest_mech = nearest(E, mech_anti, excl, top_k=3)

        topics = [rows[i]["topic"] for i in comp]
        messages = [rows[i]["message"] for i in comp]
        try:
            descs = synthesize_antipodes(client, topics, messages, n=3)
        except Exception as e:
            print(f"  (synthesis failed for cluster {ci}: {e})")
            descs = []

        synth_pairs = []
        if descs:
            anti_E = embed_under_instruction(model, descs)
            for desc, vec in zip(descs, anti_E):
                near = nearest(E, vec, excl, top_k=3)
                synth_pairs.append((desc, near))

        render(rows, ci, comp, nearest_mech, synth_pairs)


if __name__ == "__main__":
    main()
