"""Re-embed perspectives via Gemini for cross-embedder comparison.

Test: does the K=3 transitional structure that MiniLM found
(sigma_e ∈ [0.30, 0.40], components {A,C,D,F}, {B}, {E})
survive on a different embedder?

If same structure → rhetorical-density axis is real, embedder-agnostic.
If different structure → kernel finds per-embedder artifacts.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

import numpy as np

from perspectives import PERSPECTIVES


def get_key() -> str:
    if k := os.environ.get("GEMINI_API_KEY"):
        return k
    env_path = Path.home() / "Code" / "discord-scraper" / ".env"
    for line in env_path.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no GEMINI_API_KEY found")


MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-embedding-001")


def embed_all(texts: list[str]) -> np.ndarray:
    from google import genai
    client = genai.Client(api_key=get_key())
    out = []
    # Gemini embedding API takes one input at a time for stability;
    # batch is supported but error-prone across SDK versions.
    for t in texts:
        r = client.models.embed_content(model=MODEL_NAME, contents=t)
        # Response shape varies by SDK version; handle both.
        if hasattr(r, "embeddings"):
            vec = r.embeddings[0].values
        elif hasattr(r, "embedding"):
            vec = r.embedding.values if hasattr(r.embedding, "values") else r.embedding
        else:
            raise RuntimeError(f"unknown response shape: {type(r)}")
        out.append(vec)
    return np.array(out)


def main() -> None:
    ids = [p[0] for p in PERSPECTIVES]
    substance = {p[0]: p[1] for p in PERSPECTIVES}
    style = {p[0]: p[2] for p in PERSPECTIVES}
    texts = [p[3] for p in PERSPECTIVES]

    print(f"# embeddings: {MODEL_NAME}")
    E = embed_all(texts)
    print(f"  shape: {E.shape}")

    np.savez("/tmp/coupling_test/embeddings_gemini.npz",
             E=E, ids=np.array(ids),
             substance=np.array([substance[i] for i in ids]),
             style=np.array([style[i] for i in ids]),
             model=np.array([MODEL_NAME]))
    print(f"  saved → /tmp/coupling_test/embeddings_gemini.npz")


if __name__ == "__main__":
    main()
