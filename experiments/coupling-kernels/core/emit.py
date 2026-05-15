"""Emit query-run, query-comparison, and hypothesis facts to coupling-kernels.vertex.

Receipts are auto-emitted by run scripts AFTER run() / compare() returns.
The harness's run() and compare() stay pure — they don't emit. This keeps
verification anchors and schema demos out of the receipt stream.

Design references (project store):
  - design/coupling-kernels-emission-shape (umbrella)
  - design/query-run-fact (query-run shape)
  - design/query-comparison-fact (query-comparison shape)

Shape decisions encoded here:
  - run_id derived deterministically from spec_hash + ts_ms — refable without
    exposing fact ULIDs.
  - spec_hash hashes the recipe only (corpus decl + embedder spec_hash +
    kernel class + readouts). Binding (vertex name, embedder name + spec)
    is separate.
  - embeddings_ref present iff the embedder is CachedEmbedder. Absent =
    ephemeral run, honest about partiality.
  - readout_summary keeps counts/keys, not full payloads (those live in
    qr.readout_outputs in memory only).
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

from .compare import ComparisonResult
from .query import Query, QueryResult


VERTEX_NAME = "coupling-kernels"
HERE = Path(__file__).resolve().parent
VERTEX_PATH = HERE.parent / "coupling-kernels.vertex"
DEFAULT_OBSERVER = "loops-claude"


# --- Spec hash + binding extraction -------------------------------------------------

def spec_hash(query: Query) -> str:
    """Recipe-only hash. Same recipe ⇒ same hash regardless of binding.

    Includes: corpus declaration, embedder spec (already content-addressed),
    kernel class name + params, readout declarations.
    Excludes: corpus snapshot state, embedder cache state, run-time bindings.
    """
    parts = {
        "corpus_kinds": list(query.corpus.kinds),
        "corpus_min_chars": query.corpus.min_chars,
        "corpus_vertex": query.corpus.vertex,
        "embedder_spec": getattr(query.embedder, "spec_hash", None) or query.embedder.name,
        "kernel_class": type(query.kernel).__name__,
        "kernel_params": _kernel_params(query.kernel),
        "readouts": [(r.name, _params_repr(r.params)) for r in query.readouts],
    }
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:12]


def _kernel_params(kernel: Any) -> dict:
    """Extract parameters from a Kernel instance — frozen dataclass fields."""
    if is_dataclass(kernel):
        return asdict(kernel)
    return {}


def _params_repr(params: Any) -> Any:
    if params is None:
        return None
    if is_dataclass(params):
        return asdict(params)
    if isinstance(params, dict):
        return params
    return str(params)


def _binding(query: Query) -> dict:
    return {
        "vertex": query.corpus.vertex,
        "embedder_name": query.embedder.name,
        "embedder_spec_hash": getattr(query.embedder, "spec_hash", None),
    }


def _embeddings_ref(query: Query) -> Optional[str]:
    """Return cache path if embedder is CachedEmbedder, else None.

    Absent embeddings_ref on a query-run fact = ephemeral run with no
    persisted artifacts. Honest about partiality; do not fabricate a path.
    """
    cache_path = getattr(query.embedder, "_cache_path", None)
    if cache_path is None:
        return None
    try:
        path = cache_path() if callable(cache_path) else cache_path
        return str(path)
    except Exception:
        return None


def _readout_summary(qr: QueryResult) -> dict:
    """Per-readout summary — counts, top-k, not full payloads."""
    out: dict[str, Any] = {}
    for name, payload in qr.readout_outputs.items():
        if isinstance(payload, list):
            out[name] = {"n": len(payload)}
        elif isinstance(payload, dict):
            out[name] = {"keys": list(payload.keys())[:10], "n": len(payload)}
        else:
            out[name] = {"type": type(payload).__name__}
    return out


# --- ID derivation ------------------------------------------------------------------

def make_run_id(query: Query, ts: float) -> str:
    """run_<short_spec_hash>_<ts_ms> — deterministic, unique per execution."""
    sh = spec_hash(query)
    return f"run_{sh}_{int(ts * 1000)}"


def make_comparison_id(run_a_id: str, run_b_id: str, op: str) -> str:
    """cmp_<run_a_id>_<run_b_id>_<op> — unique per (pair, op)."""
    return f"cmp_{run_a_id}_{run_b_id}_{op}"


# --- Emit ---------------------------------------------------------------------------

def emit_hypothesis(name: str, message: str, *,
                    status: str = "proposed",
                    recipe_id: Optional[str] = None,
                    params: Optional[dict] = None,
                    observer: str = DEFAULT_OBSERVER,
                    vertex_path: Path = VERTEX_PATH) -> str:
    """Emit a hypothesis fact (upsert by name). Returns the name.

    On status update (e.g., proposed → confirmed), call again with same name
    and new status/message — the by-name fold upserts.
    """
    payload = {
        "name": name,
        "message": message,
        "status": status,
    }
    if recipe_id:
        payload["recipe_id"] = recipe_id
    if params:
        payload["params"] = json.dumps(params)
    _emit("hypothesis", payload, observer=observer, vertex_path=vertex_path)
    return name


def emit_run(qr: QueryResult, query: Query, *,
             hypothesis_name: Optional[str] = None,
             observer: str = DEFAULT_OBSERVER,
             vertex_path: Path = VERTEX_PATH,
             ts: Optional[float] = None) -> str:
    """Emit a query-run receipt. Returns the run_id."""
    if ts is None:
        ts = time.time()
    sh = spec_hash(query)
    run_id = make_run_id(query, ts)
    payload = {
        "run_id": run_id,
        "spec_hash": sh,
        "binding": json.dumps(_binding(query)),
        "sigma": float(qr.sigma),
        "n_components": len(qr.components),
        "n_items": len(qr.rows),
        "components": json.dumps(qr.components),
        "readout_summary": json.dumps(_readout_summary(qr)),
    }
    embeddings_ref = _embeddings_ref(query)
    if embeddings_ref:
        payload["embeddings_ref"] = embeddings_ref
    if hypothesis_name:
        payload["ref"] = f"hypothesis:{hypothesis_name}"
    _emit("query-run", payload, observer=observer, vertex_path=vertex_path, ts=ts)
    return run_id


def emit_comparison(cr: ComparisonResult, run_a_id: str, run_b_id: str, *,
                    observer: str = DEFAULT_OBSERVER,
                    vertex_path: Path = VERTEX_PATH) -> str:
    """Emit a query-comparison receipt. Returns the comparison_id.

    Refs both runs via existing ref machinery — cluster lineage queryable
    via the ref graph without a separate index.
    """
    cmp_id = make_comparison_id(run_a_id, run_b_id, cr.op)
    payload = {
        "comparison_id": cmp_id,
        "op": cr.op,
        "ref": f"query-run:{run_a_id},query-run:{run_b_id}",
        "payload": json.dumps(_serialize_payload(cr.payload)),
    }
    _emit("query-comparison", payload, observer=observer, vertex_path=vertex_path)
    return cmp_id


def _serialize_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_serialize_payload(x) for x in payload]
    if isinstance(payload, tuple):
        return list(payload)
    return payload


# --- Direct engine emit -------------------------------------------------------------

def _emit(kind: str, payload: dict, *,
          observer: str,
          vertex_path: Path,
          ts: Optional[float] = None) -> None:
    """Route a fact through the vertex runtime via the engine directly.

    No shell-out — avoids per-call uv install/sync overhead and keeps the
    emit path under Python control. The vertex's loops are loaded, the
    fact is routed through fold + boundary, the store appends.
    """
    from atoms import Fact
    from engine import load_vertex_program

    if ts is None:
        ts = time.time()

    fact = Fact(
        kind=kind,
        ts=ts,
        payload=payload,
        observer=observer,
        origin="",
    )
    program = load_vertex_program(vertex_path, validate_ast=False)
    try:
        program.receive(fact)
    finally:
        if program.has_store:
            program.vertex._store.close()
