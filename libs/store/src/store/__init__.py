"""store — Operations on vertex store databases.

Slice, merge, receive, compact, transport, and rebirth for the
facts/ticks schema. engine.SqliteStore writes facts at runtime.
This library maintains them.
"""

# `derived_log_merge` is deliberately NOT re-exported here. It is a git
# merge driver — tooling over store artifacts, not part of this lib's
# runtime API — and its interface is `python -m store.derived_log_merge`.
# Importing it here would also make that invocation load the module twice
# (once through this package, once as __main__), which runpy reports as a
# RuntimeWarning on the driver's stderr, where git shows it to the user on
# every merge. Reach it as `store.derived_log_merge.merge_derived_log`.
from ._transport_local import LocalTransport
from .compact import CompactResult, compact_store
from .merge import MergeResult, merge_store
from .rebirth import (
    FactRow,
    RebirthResult,
    RebirthVerification,
    Transform,
    filtered,
    identity,
    rebirth_store,
    ulid_migration,
    verify_rebirth,
)
from .receive import ReceiveResult, receive_store
from .slice import SliceResult, slice_store
from .transport import PullResult, PushResult, Transport, pull_store, push_store

__all__ = [
    "CompactResult",
    "compact_store",
    "FactRow",
    "filtered",
    "identity",
    "LocalTransport",
    "MergeResult",
    "merge_store",
    "PullResult",
    "pull_store",
    "PushResult",
    "push_store",
    "RebirthResult",
    "rebirth_store",
    "RebirthVerification",
    "ReceiveResult",
    "receive_store",
    "SliceResult",
    "slice_store",
    "Transform",
    "Transport",
    "ulid_migration",
    "verify_rebirth",
]
