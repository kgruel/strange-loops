"""Lineage readout — cluster lineage requires a previous QueryResult.

Lineage is a comparison, not a single-result readout. The run script computes
it via core.compare(qa, qb, op="lineage"). This readout exposes the
machinery via params.previous_components for in-pipeline use; if not given,
returns an empty mapping.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from core.compare import lineage_match


@dataclass(frozen=True)
class LineageParams:
    min_size: int = 3
    previous_components: Optional[tuple] = None  # tuple of tuples (global indices)


def lineage_readout(rows, comps, ctx, params: LineageParams, *,
                    E=None, D=None, sigma=None):
    if params.previous_components is None:
        return {"matches": [], "note": "no previous_components supplied"}
    big_now = sorted(
        [c for c in comps if len(c) >= params.min_size], key=len, reverse=True,
    )
    big_prev = sorted(
        [list(c) for c in params.previous_components if len(c) >= params.min_size],
        key=len, reverse=True,
    )
    matches = lineage_match(big_now, big_prev)
    persist = sum(1 for _, _, j in matches if j >= 0.5)
    morph = sum(1 for _, _, j in matches if 0.2 <= j < 0.5)
    emerge = sum(1 for _, _, j in matches if j < 0.2)
    return {
        "matches": matches,
        "persistent": persist,
        "morphing": morph,
        "emerging": emerge,
    }
