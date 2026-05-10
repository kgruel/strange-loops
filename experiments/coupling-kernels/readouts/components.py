"""Components readout — basic cluster listing with kind/namespace mix."""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import Counter


@dataclass(frozen=True)
class ComponentsParams:
    min_size: int = 3
    top_n: int = 10
    sample_per_cluster: int = 6


def components_readout(rows, comps, ctx, params: ComponentsParams, *,
                       E=None, D=None, sigma=None):
    non_trivial = sorted(
        [c for c in comps if len(c) >= params.min_size],
        key=len, reverse=True,
    )[:params.top_n]
    out = []
    for ci, comp in enumerate(non_trivial, 1):
        kinds = Counter(rows[i].get("kind", "") for i in comp)
        namespaces = Counter(
            (rows[i].get("topic") or rows[i].get("key", "")).split("/", 1)[0]
            for i in comp
        )
        sample = sorted(comp, key=lambda i: -len(rows[i].get("message", "")))
        sample = sample[:params.sample_per_cluster]
        out.append({
            "id": f"C{ci}",
            "size": len(comp),
            "members": comp,
            "kinds": dict(kinds.most_common()),
            "namespaces": dict(namespaces.most_common(3)),
            "sample": [
                {"kind": rows[i].get("kind", ""),
                 "topic": rows[i].get("topic", rows[i].get("key", "")),
                 "status": rows[i].get("status", "")}
                for i in sample
            ],
        })
    return out
