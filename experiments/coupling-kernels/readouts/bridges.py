"""Bridges readout — cross-kind clusters (≥min_kinds × ≥min_per_kind)."""
from __future__ import annotations
from dataclasses import dataclass
from collections import Counter

import numpy as np


@dataclass(frozen=True)
class BridgesParams:
    min_size: int = 3
    min_kinds: int = 2
    min_per_kind: int = 2
    top_n: int = 6  # number of strongest bridges to return


def _kind_distribution(comp, rows):
    return Counter(rows[i]["kind"] for i in comp)


def _kind_purity(comp, rows):
    kd = _kind_distribution(comp, rows)
    return kd.most_common(1)[0][1] / len(comp)


def _is_cross_kind(comp, rows, min_kinds, min_per_kind):
    kd = _kind_distribution(comp, rows)
    return sum(1 for c in kd.values() if c >= min_per_kind) >= min_kinds


def bridges_readout(rows, comps, ctx, params: BridgesParams, *,
                    E=None, D=None, sigma=None):
    non_trivial = [c for c in comps if len(c) >= params.min_size]
    purities = [_kind_purity(c, rows) for c in non_trivial]
    cross = [c for c in non_trivial
             if _is_cross_kind(c, rows, params.min_kinds, params.min_per_kind)]
    bridges_sorted = sorted(cross, key=lambda c: _kind_purity(c, rows))
    out_bridges = []
    for ci, comp in enumerate(bridges_sorted[:params.top_n], 1):
        kd = _kind_distribution(comp, rows)
        out_bridges.append({
            "id": f"B{ci}",
            "size": len(comp),
            "purity": float(_kind_purity(comp, rows)),
            "kinds": dict(kd.most_common()),
            "members": comp,
        })
    return {
        "n_non_trivial": len(non_trivial),
        "n_cross_kind": len(cross),
        "mean_purity": float(np.mean(purities)) if purities else 0.0,
        "median_purity": float(np.median(purities)) if purities else 0.0,
        "purity_distribution": {
            "pure_ge_0.9": sum(1 for p in purities if p >= 0.9),
            "dominant_0.7_to_0.9": sum(1 for p in purities if 0.7 <= p < 0.9),
            "mixed_lt_0.7": sum(1 for p in purities if p < 0.7),
        },
        "bridges": out_bridges,
    }
