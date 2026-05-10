"""Query, QueryResult, run().

A Query is a value: corpus + embedder + kernel + readouts. `run(q)` executes
the pipeline and returns a QueryResult. New experiments should be a single
~10-line Query value plus rendering.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from .corpus import Corpus, load
from .embedder import Embedder
from .kernel import Kernel, cosine_dist


@dataclass(frozen=True)
class Readout:
    name: str
    params: Any  # one of *Params dataclasses from readouts/


@dataclass
class QueryResult:
    rows: list[dict]
    E: np.ndarray
    D: np.ndarray
    sigma: float
    components: list[list[int]]
    readout_outputs: dict[str, Any]


@dataclass
class RunContext:
    """Side-data containers passed to readouts that need them.

    triage uses sqlite_conn + repo_path; antipodes uses llm_client + embedder
    for re-embedding synthesized text under the same instruction.
    """
    sqlite_conn: Any = None
    repo_path: Any = None
    llm_client: Any = None
    embedder: Any = None  # for re-embedding (e.g. antipodes)
    extra: dict = field(default_factory=dict)


def run(query: "Query",
        rows: Optional[list[dict]] = None,
        E: Optional[np.ndarray] = None,
        ctx: Optional[RunContext] = None) -> QueryResult:
    """Execute the pipeline.

    Parameters `rows` and `E` allow injecting precomputed corpus/embeddings
    (used by verification anchors and runs pinned to fixture state). When
    None, the corpus is loaded from sqlite and the embedder is invoked.
    """
    from readouts import REGISTRY  # late import; sibling package

    if rows is None:
        rows = load(query.corpus)
    if E is None:
        texts = [r["message"] for r in rows]
        E = query.embedder.embed(texts)
    if E.shape[0] != len(rows):
        raise ValueError(
            f"embedding count {E.shape[0]} != row count {len(rows)}"
        )

    D = cosine_dist(E)
    sigma, comps = query.kernel.resolve(D)

    ctx = ctx or RunContext()
    readout_outputs = {}
    for ro in query.readouts:
        if ro.name not in REGISTRY:
            raise KeyError(f"unknown readout: {ro.name!r}")
        params_cls, fn = REGISTRY[ro.name]
        params = ro.params if isinstance(ro.params, params_cls) else params_cls(**(ro.params or {}))
        readout_outputs[ro.name] = fn(rows, comps, ctx, params, E=E, D=D, sigma=sigma)

    return QueryResult(
        rows=rows, E=E, D=D, sigma=sigma or 0.0,
        components=comps, readout_outputs=readout_outputs,
    )


@dataclass(frozen=True)
class Query:
    corpus: Corpus
    embedder: Embedder
    kernel: Kernel
    readouts: tuple[Readout, ...] = ()
