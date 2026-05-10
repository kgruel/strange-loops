"""Compare operator over QueryResults.

`jaccard` and `lineage_match` extracted from temporal.py. `intersect_components`
is a stub for the future multi-instruction-intersection hypothesis.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ComparisonResult:
    op: str
    payload: Any


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / max(len(a | b), 1)


def lineage_match(comps_now, comps_prev):
    """For each cluster in comps_now, find best-matching prev cluster.
    Returns list of (now_idx, prev_idx_or_-1, jaccard)."""
    out = []
    for ni, nc in enumerate(comps_now):
        if not comps_prev:
            out.append((ni, -1, 0.0))
            continue
        best_p, best_j = -1, -1.0
        for pi, pc in enumerate(comps_prev):
            j = jaccard(nc, pc)
            if j > best_j:
                best_j = j
                best_p = pi
        out.append((ni, best_p, best_j))
    return out


def intersect_components(comps_a, comps_b, min_size: int = 2):
    """Pairwise intersection of clusters across two query results.

    Stub for the multi-instruction-intersection hypothesis: items that
    co-cluster under TWO different instructions are doubly-justified
    members.
    """
    out = []
    for a in comps_a:
        sa = set(a)
        for b in comps_b:
            inter = sa & set(b)
            if len(inter) >= min_size:
                out.append(sorted(inter))
    return out


def compare(qa, qb, op: str = "jaccard") -> ComparisonResult:
    """Compare two QueryResults.

    op="jaccard"     — jaccard between best-matched clusters (size-sorted)
    op="lineage"     — lineage_match (qa = now, qb = prev)
    op="intersect"   — pairwise component intersection
    """
    comps_a = qa.components
    comps_b = qb.components
    big_a = sorted([c for c in comps_a if len(c) >= 3], key=len, reverse=True)
    big_b = sorted([c for c in comps_b if len(c) >= 3], key=len, reverse=True)
    if op == "jaccard":
        # symmetric pairing, best match per A
        out = []
        for ai, ac in enumerate(big_a):
            best_b, best_j = -1, -1.0
            for bi, bc in enumerate(big_b):
                j = jaccard(ac, bc)
                if j > best_j:
                    best_j = j
                    best_b = bi
            out.append((ai, best_b, best_j))
        return ComparisonResult(op=op, payload=out)
    if op == "lineage":
        return ComparisonResult(op=op, payload=lineage_match(big_a, big_b))
    if op == "intersect":
        return ComparisonResult(op=op, payload=intersect_components(big_a, big_b))
    raise ValueError(f"unknown compare op: {op!r}")
