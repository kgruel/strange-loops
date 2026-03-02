"""store — Operations on vertex store databases.

Slice, merge, search, and transport for the facts/ticks schema.
engine.SqliteStore writes facts at runtime. This library maintains them.

Phase 1: slice_store, merge_store.
"""

from .merge import MergeResult, merge_store
from .slice import SliceResult, slice_store

__all__ = [
    "SliceResult",
    "slice_store",
    "MergeResult",
    "merge_store",
]
