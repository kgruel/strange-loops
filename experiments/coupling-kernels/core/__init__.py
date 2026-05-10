"""structure-reveal harness: composable corpus → embed → kernel → readout pipeline.

Public API:
    Query, QueryResult, run, compare
    Corpus, Embedder, STEmbedder, E5InstructEmbedder, GeminiEmbedder
    Kernel
    Readout
"""
from .corpus import Corpus, load
from .embedder import (
    Embedder,
    STEmbedder,
    E5InstructEmbedder,
    GeminiEmbedder,
    CachedEmbedder,
)
from .kernel import (
    Kernel,
    cosine_dist,
    dog_kernel,
    positive_components,
    find_richness_scale,
)
from .query import Query, QueryResult, run
from .compare import compare, ComparisonResult

__all__ = [
    "Query",
    "QueryResult",
    "run",
    "compare",
    "ComparisonResult",
    "Corpus",
    "load",
    "Embedder",
    "STEmbedder",
    "E5InstructEmbedder",
    "GeminiEmbedder",
    "CachedEmbedder",
    "Kernel",
    "cosine_dist",
    "dog_kernel",
    "positive_components",
    "find_richness_scale",
    "Readout",
]

from .query import Readout  # re-export
