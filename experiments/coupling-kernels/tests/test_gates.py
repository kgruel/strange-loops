"""Verification gates 1, 2, 3, 3b.

Run with:
    .venv-experiment/bin/python experiments/coupling-kernels/tests/test_gates.py
"""
from __future__ import annotations
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core.kernel import (
    cosine_dist, dog_kernel, positive_components, find_richness_scale,
)
from core.embedder import Embedder, CachedEmbedder
from core.corpus import Corpus, load, load_manifest

FIXTURES = ROOT / "fixtures"


# --- Gate 1: helper byte-equivalence -----------------------------------------

def test_gate_1_helper_byte_equivalence():
    """cosine_dist + dog_kernel + positive_components + find_richness_scale
    on fixture embedding produce stable values consistent with what the
    demonstrators report on the same fixture (σ=0.0234, 23 non-trivial)."""
    E = np.load(FIXTURES / "proj_e5_allkinds_concern.npz")["E"]
    D = cosine_dist(E)
    # Self-distances near zero, off-diagonal in [0, 2]
    # Self-distance ≈ 0 within float16-level rounding (E5 is fp16-derived)
    assert np.allclose(np.diag(D), 0.0, atol=1e-3)
    off = D[np.triu_indices(D.shape[0], k=1)]
    assert off.min() > -1e-9 and off.max() < 2.0 + 1e-9

    # find_richness_scale should resolve to σ=0.0234 (matches fixture log)
    s, comps = find_richness_scale(D)
    assert s is not None
    assert abs(s - 0.0234) < 5e-4, f"σ={s:.4f}, expected ~0.0234"
    non_trivial = [c for c in comps if len(c) >= 3]
    assert len(non_trivial) == 23, (
        f"non_trivial={len(non_trivial)}, expected 23 (per "
        f"results_temporal.txt T5 line)"
    )

    # dog_kernel direct sanity: K diagonal at sigma>0 is 1 - 0.5 = 0.5
    K = dog_kernel(D, s)
    # K diagonal at sigma>0, D=0 is exactly 0.5; on real fixture D≈0±1e-3
    assert abs(K[0, 0] - 0.5) < 1e-2

    # positive_components on a tiny synthetic K matches expectation
    K_small = np.array([
        [0, 1, 0, 0],
        [1, 0, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 1, 0],
    ], dtype=float)
    cs = positive_components(K_small)
    assert sorted([sorted(c) for c in cs]) == [[0, 1], [2, 3]]
    print("gate 1: helper byte-equivalence PASS")


# --- Gate 2: loader equivalence ---------------------------------------------

def test_gate_2_loader_equivalence():
    """The loader produces the same field schema as the manifest fixture, and
    when run against a populated DB, (kind, key) tuples are a superset of
    the manifest (append-only correctness; ts has drifted since fixture).

    If `STRUCTURE_REVEAL_DB` is set, runs the full overlap check against
    that DB; otherwise verifies schema + a synthetic-DB roundtrip only.
    """
    import os
    manifest_rows = load_manifest(FIXTURES / "project_all_kinds_manifest.json")
    expected_fields = {"kind", "key", "topic", "message", "status", "ts"}
    assert expected_fields.issubset(manifest_rows[0].keys()), (
        f"manifest schema missing fields: {expected_fields - set(manifest_rows[0].keys())}"
    )

    db_override = os.environ.get("STRUCTURE_REVEAL_DB")
    if db_override and Path(db_override).exists():
        rows_loader = load(Corpus(
            kinds=("decision", "thread", "task", "plan", "observation",
                   "hypothesis", "cite", "handoff"),
            min_chars=50, db_path=Path(db_override),
        ))
        upsert_kinds = {"decision", "thread", "task", "plan", "observation",
                        "hypothesis"}
        loader_keys = {(r["kind"], r["key"]) for r in rows_loader
                       if r["kind"] in upsert_kinds}
        manifest_keys = {(r["kind"], r["key"]) for r in manifest_rows
                         if r["kind"] in upsert_kinds}
        missing = manifest_keys - loader_keys
        assert not missing, (
            f"manifest items missing from current loader: {len(missing)} — "
            f"DB regression. examples: {list(missing)[:3]}"
        )
        print(f"gate 2 (live DB): {len(manifest_keys & loader_keys)}/"
              f"{len(manifest_keys)} manifest upsert-keys present "
              f"({100*len(manifest_keys & loader_keys)/len(manifest_keys):.1f}%)")
        print(f"          new since fixture: "
              f"{len(loader_keys - manifest_keys)} items")

    # Synthetic-DB roundtrip
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "synth.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE facts (id TEXT, kind TEXT, ts REAL, payload TEXT)")
        # Two upsert kinds with one dup, two collect kinds
        conn.executemany(
            "INSERT INTO facts VALUES (?,?,?,?)",
            [
                ("a1", "decision", 100.0, json.dumps({"topic": "x/y", "message": "x" * 60})),
                ("a2", "decision", 200.0, json.dumps({"topic": "x/y", "message": "y" * 60})),
                ("a3", "thread", 150.0, json.dumps({"name": "t1", "message": "t" * 60})),
                ("a4", "cite", 300.0, json.dumps({"ref": "x/y", "message": "c" * 60})),
                ("a5", "decision", 250.0, json.dumps({"topic": "stub", "message": "x" * 10})),  # too short
            ],
        )
        conn.commit()
        conn.close()

        rows = load(Corpus(
            kinds=("decision", "thread", "cite"), min_chars=50,
            db_path=db_path,
        ))
        # Decision dup folded → 1 (latest, ts=200.0); thread → 1; cite → 1
        # Stub-message decision filtered out by min_chars
        kinds = sorted([r["kind"] for r in rows])
        assert kinds == ["cite", "decision", "thread"], f"got {kinds}"
        decision = [r for r in rows if r["kind"] == "decision"][0]
        # Latest payload kept
        assert decision["ts"] == 200.0 and decision["message"].startswith("y")
        print("gate 2: loader equivalence PASS (schema + synthetic-DB roundtrip)")
    print(f"  manifest n={len(manifest_rows)}; live worktree DB has insufficient")
    print(f"  fact-history to roundtrip the full manifest. Synthetic-DB shape verified.")


# --- Gate 3 + 3b: cache key correctness -------------------------------------

class CountingEmbedder(Embedder):
    """Deterministic in-memory embedder that counts model invocations.

    Embedding is a stable function of the text (so a re-embed of the same text
    gives the same vector — required for cache reuse to be observable).
    """
    name = "counting"

    def __init__(self):
        self.invocation_count = 0
        self.invocation_history: list[int] = []

    def embed_raw(self, texts):
        self.invocation_count += len(texts)
        self.invocation_history.append(len(texts))
        # Deterministic vec from byte sum
        out = np.zeros((len(texts), 4), dtype=np.float32)
        for i, t in enumerate(texts):
            b = t.encode("utf-8")
            out[i, 0] = sum(b) / 100.0
            out[i, 1] = len(b) / 10.0
            out[i, 2] = (b[0] if b else 0) / 256.0
            out[i, 3] = (b[-1] if b else 0) / 256.0
        return out


def test_gate_3_append_only():
    """First call embeds N items; second call appends 1 item, embeds only 1."""
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        inner = CountingEmbedder()
        cached = CachedEmbedder(inner, cache_dir)
        items_a = [f"item-{i}" for i in range(10)]
        E1 = cached.embed(items_a)
        n_first = cached.last_invocation_count
        assert n_first == 10, f"first call: expected 10, got {n_first}"

        items_b = items_a + ["new-item"]
        E2 = cached.embed(items_b)
        n_second = cached.last_invocation_count
        assert n_second == 1, f"second call: expected 1, got {n_second}"

        # Cached embeddings byte-identical
        assert np.array_equal(E1, E2[:10]), "cached entries drifted"
        print(f"gate 3: append-only PASS (first={n_first}, second={n_second})")


def test_gate_3b_overlap_sharing():
    """Two corpora sharing 80% items: second call embeds only the 20% delta."""
    with tempfile.TemporaryDirectory() as td:
        cache_dir = Path(td)
        inner = CountingEmbedder()
        cached = CachedEmbedder(inner, cache_dir)
        items_a = [f"shared-{i}" for i in range(8)] + [f"only-a-{i}" for i in range(2)]
        items_b = [f"shared-{i}" for i in range(8)] + [f"only-b-{i}" for i in range(2)]

        cached.embed(items_a)
        n_a = cached.last_invocation_count
        assert n_a == 10, f"first call expected 10, got {n_a}"

        E_b = cached.embed(items_b)
        n_b = cached.last_invocation_count
        assert n_b == 2, f"overlap call expected 2, got {n_b}"
        # Order preservation
        E_a = cached.embed(items_a)
        assert cached.last_invocation_count == 0, "third call should be all hits"
        # Same-text positions in the two corpora yield same vectors
        for i in range(8):
            assert np.array_equal(E_b[i], E_a[i]), (
                f"shared-{i} differs between corpora"
            )
        print(f"gate 3b: overlap sharing PASS (first={n_a}, second={n_b})")


def main():
    test_gate_1_helper_byte_equivalence()
    test_gate_2_loader_equivalence()
    test_gate_3_append_only()
    test_gate_3b_overlap_sharing()
    print("\nALL UNIT GATES PASS (1, 2, 3, 3b)")


if __name__ == "__main__":
    main()
