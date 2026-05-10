"""Antipode investigation — negative-space mapping (schema demonstration).

Mechanical antipode (-c̄ in embedding space) + LLM-synthesized antipodes
re-embedded under the same E5/mechanism instruction. The Query asks the
`antipodes` readout to do both at each crystallized cluster.

Schema demo. Requires sentence-transformers + google-genai.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (                                                      # noqa: E402
    Corpus, E5InstructEmbedder, CachedEmbedder,
    Kernel, Query, Readout, run,
)
from core.query import RunContext                                       # noqa: E402

CACHE = ROOT / "cache" / "embeddings"

INSTRUCTION = ("Group these architectural decisions by the underlying "
               "mechanism or primitive they describe.")


def gemini_key():
    env = Path.home() / "Code" / "discord-scraper" / ".env"
    for line in env.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY not found")


def main():
    decisions = Corpus(vertex="project", kinds=("decision",), min_chars=50)
    embedder = CachedEmbedder(E5InstructEmbedder(INSTRUCTION), CACHE)
    q = Query(
        corpus=decisions, embedder=embedder, kernel=Kernel(),
        readouts=(Readout("antipodes", {"top_k": 3, "n_synth": 3}),),
    )

    from google import genai
    client = genai.Client(api_key=gemini_key())
    ctx = RunContext(llm_client=client, embedder=embedder)
    qr = run(q, ctx=ctx)

    out = qr.readout_outputs["antipodes"]
    rows = qr.rows
    for cluster in out["clusters"]:
        comp = cluster["members"]
        print(f"\n## Cluster {cluster['id']} (size={cluster['size']})")
        print(f"  namespaces: {cluster['namespaces']}")
        for t in [rows[i].get('topic', rows[i].get('key', '')) for i in comp[:6]]:
            print(f"    • {t}")
        if len(comp) > 6:
            print(f"    ... and {len(comp)-6} more")
        print(f"\n  ▸ Mechanical antipode (-c̄):")
        for idx, dist in cluster["mechanical_nearest"]:
            t = rows[idx].get("topic", rows[idx].get("key", ""))
            print(f"    nearest fact: {t:<55}  d={dist:.3f}")
        for ai, synth in enumerate(cluster["synthesized"], 1):
            if "error" in synth:
                print(f"  (synthesis failed: {synth['error']})")
                continue
            print(f"\n  ▸ Synthesized antipode {ai}: {synth['description'][:120]}")
            for idx, dist in synth["nearest"]:
                t = rows[idx].get("topic", rows[idx].get("key", ""))
                print(f"    nearest fact: {t:<55}  d={dist:.3f}")


if __name__ == "__main__":
    main()
