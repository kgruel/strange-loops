"""DoG-coupling kernel and component helpers (verbatim from temporal.py).

These four helpers are byte-identical across all six demonstrators
(real_sweep, e5_sweep, antipode, bridge, triage, temporal). Verification
gate 1 asserts equality against the fixture embedding `proj_e5_allkinds_concern.npz`.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Union

import numpy as np


def cosine_dist(E):
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    return 1.0 - (norm @ norm.T)


def dog_kernel(D, sigma_e, ratio=2.0):
    sigma_i = ratio * sigma_e
    return (np.exp(-(D**2) / (2 * sigma_e**2))
            - (sigma_e / sigma_i) * np.exp(-(D**2) / (2 * sigma_i**2)))


def positive_components(K):
    n = K.shape[0]
    K = K.copy()
    np.fill_diagonal(K, 0)
    visited = [False] * n
    comps = []
    for start in range(n):
        if visited[start]:
            continue
        stack, comp = [start], []
        while stack:
            v = stack.pop()
            if visited[v]:
                continue
            visited[v] = True
            comp.append(v)
            for u in range(n):
                if not visited[u] and K[v, u] > 0:
                    stack.append(u)
        comps.append(sorted(comp))
    return comps


def find_richness_scale(D, ratio: float = 2.0):
    """Search percentile-derived sigmas for the one maximizing non-trivial
    component count under dog_kernel(D, s, ratio).

    The ratio parameter (default 2.0 to preserve existing callers) is
    passed through to dog_kernel — without it, the search is silently
    ratio=2.0 regardless of the calling Kernel's ratio. See hypothesis
    'find-richness-scale-drops-ratio' (coupling-kernels vertex) for the
    bug history.
    """
    if D.shape[0] < 5:
        return 0.0, []
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5]
    best_s, best_richness, best_comps = None, -1, None
    for p in pcts:
        s = float(np.percentile(off, p))
        if s == 0:
            continue
        K = dog_kernel(D, s, ratio=ratio)
        comps = positive_components(K)
        non_trivial = [c for c in comps if len(c) >= 3]
        if len(non_trivial) > best_richness:
            best_richness = len(non_trivial)
            best_s = s
            best_comps = comps
    return best_s, best_comps if best_comps else []


@dataclass(frozen=True)
class Kernel:
    """DoG kernel spec. `sigma="auto-richness"` triggers find_richness_scale."""
    kind: str = "dog"
    sigma: Union[float, str] = "auto-richness"
    ratio: float = 2.0
    scale_finder: Union[str, Callable] = "auto-richness"

    def resolve(self, D):
        """Return (sigma, comps) from a distance matrix."""
        if isinstance(self.sigma, (int, float)) and not isinstance(self.sigma, bool):
            s = float(self.sigma)
            K = dog_kernel(D, s, ratio=self.ratio)
            return s, positive_components(K)
        if callable(self.scale_finder):
            return self.scale_finder(D)
        return find_richness_scale(D, ratio=self.ratio)
