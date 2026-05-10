"""Embedder ABC + three adapters + per-item content-hashed cache.

Adapter behavior is preserved verbatim from the original demonstrators:
  STEmbedder       — real_sweep.py:42–45 (MiniLM batch encode)
  E5InstructEmbedder — e5_sweep.py:75–95 (instruction prefix + ST batch)
  GeminiEmbedder   — real_sweep.py:48–96 (429-backoff + checkpointing)

Cache key is per-item content-hash (NOT batch-hash). Append-only correctness:
adding a new item invalidates only that item's cache entry, not the corpus.
Cross-corpus overlap: two corpora sharing 80% of items pay only the 20% delta.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np


def _content_hash(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=16).hexdigest()


class Embedder(ABC):
    """Abstract base. Subclasses set `name` + `spec_hash` and implement embed_raw()."""
    name: str = "abstract"

    @property
    def spec_hash(self) -> str:
        """Stable hash of the embedder configuration (model + instruction etc).

        Combined with per-text content hashes to form cache keys. Two embedders
        with the same spec_hash + text content share a cache entry.
        """
        return _content_hash(self.name)

    @abstractmethod
    def embed_raw(self, texts: list[str]) -> np.ndarray:
        """Compute embeddings for ALL given texts (no cache)."""
        ...

    def embed(self, texts: list[str]) -> np.ndarray:
        """Default uncached entry. Wrap with CachedEmbedder for cache."""
        return self.embed_raw(texts)


class STEmbedder(Embedder):
    """Sentence-Transformers embedder (MiniLM family). Verbatim from
    real_sweep.py:embed_minilm — normalize_embeddings=False, no progress."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.name = f"st:{model_name}"
        self._model = None

    @property
    def spec_hash(self) -> str:
        return _content_hash(f"st:{self.model_name}")

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)

    def embed_raw(self, texts: list[str]) -> np.ndarray:
        self._ensure_model()
        return np.array(self._model.encode(
            texts, normalize_embeddings=False, show_progress_bar=False,
        ))


class E5InstructEmbedder(Embedder):
    """E5-Instruct embedder with instruction prefix. Verbatim from
    e5_sweep.py:embed_e5 — normalize_embeddings=True, batch_size=8,
    progress bar shown."""

    def __init__(self, instruction: str,
                 model_name: str = "intfloat/multilingual-e5-large-instruct"):
        self.instruction = instruction
        self.model_name = model_name
        self.name = f"e5:{model_name}:{_content_hash(instruction)[:8]}"
        self._model = None

    @property
    def spec_hash(self) -> str:
        return _content_hash(f"e5:{self.model_name}:{self.instruction}")

    @staticmethod
    def format(task: str, text: str) -> str:
        return f"Instruct: {task}\nQuery: {text}"

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            print(f"  loading {self.model_name}...", flush=True)
            self._model = SentenceTransformer(self.model_name)

    def embed_raw(self, texts: list[str]) -> np.ndarray:
        self._ensure_model()
        inputs = [self.format(self.instruction, t) for t in texts]
        print(f"  encoding {len(inputs)} items...", flush=True)
        return np.array(self._model.encode(
            inputs, normalize_embeddings=True, show_progress_bar=True,
            batch_size=8,
        ))


class GeminiEmbedder(Embedder):
    """Gemini embedder with 429-backoff and checkpointing. Verbatim from
    real_sweep.py:embed_gemini."""

    def __init__(self, model_name: str = "gemini-embedding-001",
                 progress_path: Optional[Path] = None,
                 api_key: Optional[str] = None,
                 env_path: Optional[Path] = None):
        self.model_name = model_name
        self.name = f"gemini:{model_name}"
        self._progress_path = progress_path
        self._api_key = api_key
        self._env_path = env_path or (Path.home() / "Code" / "discord-scraper" / ".env")

    @property
    def spec_hash(self) -> str:
        return _content_hash(f"gemini:{self.model_name}")

    def _resolve_key(self) -> str:
        if self._api_key:
            return self._api_key
        if not self._env_path.exists():
            raise RuntimeError(f"GEMINI_API_KEY: env file not found at {self._env_path}")
        for line in self._env_path.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        raise RuntimeError("GEMINI_API_KEY not in env file")

    def embed_raw(self, texts: list[str]) -> np.ndarray:
        from google import genai
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self._resolve_key())
        progress_path = self._progress_path
        if progress_path and progress_path.exists():
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
                    model=self.model_name, contents=texts[i]
                )
                vec = r.embeddings[0].values if hasattr(r, "embeddings") else r.embedding.values
                out.append(vec)
                i += 1
                if progress_path and i % 25 == 0:
                    np.save(progress_path, np.array(out))
                time.sleep(0.4)
            except genai_errors.ClientError as e:
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    wait = 60
                    print(f"    429 at item {i}, sleeping {wait}s...", flush=True)
                    time.sleep(wait)
                else:
                    raise
        if progress_path:
            np.save(progress_path, np.array(out))
        return np.array(out)


class CachedEmbedder(Embedder):
    """Wraps any Embedder with per-item content-hashed cache.

    Cache layout: a single .npz per (spec_hash) containing one entry per
    content-hash. Lookups are per-item; misses are batched to inner.embed_raw().

    Instrumentation: `last_invocation_count` records how many texts went to
    the model on the most recent embed() call (used by verification gate 3).
    """

    def __init__(self, inner: Embedder, cache_dir: Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.name = f"cached:{inner.name}"
        self.last_invocation_count = 0

    @property
    def spec_hash(self) -> str:
        return self.inner.spec_hash

    def embed_raw(self, texts: list[str]) -> np.ndarray:
        return self.embed(texts)

    def _cache_path(self) -> Path:
        return self.cache_dir / f"{self.spec_hash}.npz"

    def _load_cache(self) -> dict[str, np.ndarray]:
        p = self._cache_path()
        if not p.exists():
            return {}
        with np.load(p, allow_pickle=False) as data:
            return {k: data[k] for k in data.files}

    def _save_cache(self, cache: dict[str, np.ndarray]) -> None:
        np.savez(self._cache_path(), **cache)

    def embed(self, texts: list[str]) -> np.ndarray:
        cache = self._load_cache()
        keys = [_content_hash(t) for t in texts]
        miss_idx = [i for i, k in enumerate(keys) if k not in cache]
        miss_texts = [texts[i] for i in miss_idx]
        self.last_invocation_count = len(miss_texts)
        if miss_texts:
            new_E = self.inner.embed_raw(miss_texts)
            for j, i in enumerate(miss_idx):
                cache[keys[i]] = new_E[j]
            self._save_cache(cache)
        # Stack in input order
        return np.stack([cache[k] for k in keys])
