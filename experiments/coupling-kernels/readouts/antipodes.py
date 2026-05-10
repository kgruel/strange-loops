"""Antipodes readout — mechanical (-c̄) + LLM-synthesized.

Side-data via ctx: ctx.llm_client (Gemini) + ctx.embedder (E5 model for
re-embedding synthesized text under the same instruction).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import Counter
from typing import Optional

import numpy as np


_SYNTH_INSTRUCTION = (
    "Group these architectural decisions by the underlying mechanism or "
    "primitive they describe."
)


@dataclass(frozen=True)
class AntipodesParams:
    min_size: int = 3
    max_size: int = 12
    top_k: int = 3
    n_synth: int = 3
    skip_synthesis: bool = False
    synth_model: str = "gemini-2.5-flash"


def _synthesize_antipodes(client, cluster_topics, cluster_messages, n,
                          model_name) -> list[str]:
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
    r = client.models.generate_content(model=model_name, contents=prompt)
    text = r.text.strip()
    lines = [l.strip("- •*").strip() for l in text.split("\n") if l.strip()]
    out = []
    for l in lines:
        if l and not l.lower().startswith(("here", "antipode", "concept ", "opposite ")):
            out.append(l[:280])
        if len(out) >= n:
            break
    return out


def _nearest(corpus_E, query_v, exclude, top_k):
    qn = query_v / np.linalg.norm(query_v)
    cn = corpus_E / np.linalg.norm(corpus_E, axis=1, keepdims=True)
    sims = cn @ qn
    order = np.argsort(-sims)
    out = []
    for idx in order:
        if int(idx) in exclude:
            continue
        out.append((int(idx), float(1.0 - sims[idx])))
        if len(out) >= top_k:
            break
    return out


def antipodes_readout(rows, comps, ctx, params: AntipodesParams, *,
                      E=None, D=None, sigma=None):
    if E is None:
        return {"clusters": [], "note": "E required"}
    non_trivial = sorted(
        [c for c in comps if params.min_size <= len(c) <= params.max_size],
        key=len, reverse=True,
    )
    out_clusters = []
    for ci, comp in enumerate(non_trivial, 1):
        excl = set(comp)
        cluster_E = E[comp]
        centroid = cluster_E.mean(axis=0)
        nearest_mech = _nearest(E, -centroid, excl, params.top_k)

        synth_pairs = []
        if not params.skip_synthesis and ctx and ctx.llm_client and ctx.embedder:
            topics = [rows[i].get("topic", rows[i].get("key", "")) for i in comp]
            messages = [rows[i].get("message", "") for i in comp]
            try:
                descs = _synthesize_antipodes(
                    ctx.llm_client, topics, messages, params.n_synth, params.synth_model,
                )
            except Exception as e:
                descs = []
                synth_pairs.append({"error": str(e)})
            if descs:
                anti_E = ctx.embedder.embed(descs)
                for desc, vec in zip(descs, anti_E):
                    near = _nearest(E, vec, excl, params.top_k)
                    synth_pairs.append({"description": desc, "nearest": near})

        out_clusters.append({
            "id": f"C{ci}",
            "size": len(comp),
            "members": comp,
            "namespaces": dict(Counter(
                rows[i].get("topic", "").split("/", 1)[0] for i in comp
            ).most_common(3)),
            "mechanical_nearest": nearest_mech,
            "synthesized": synth_pairs,
        })
    return {"clusters": out_clusters}
