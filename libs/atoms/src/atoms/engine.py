"""Fold engine: build executable fold functions from fold descriptors.

Each fold op becomes a closure (state: dict, payload: dict) -> None
that mutates state in place. Spec.apply() uses these to produce new
state from old state + payload.

Typed fold classes: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max, Avg, Window
"""

from __future__ import annotations

import time
from typing import Callable

from .fold import (
    Avg,
    Collect,
    Count,
    FoldOp,
    Latest,
    Max,
    Min,
    Sum,
    TopN,
    Upsert,
    Window,
)


# =============================================================================
# Primitive fold implementations
# =============================================================================


def _make_latest(target: str) -> Callable[[dict, dict], None]:
    """state[target] = event timestamp."""
    def fold(state: dict, payload: dict) -> None:
        state[target] = payload.get("_ts", time.time())
    return fold


def _make_count(target: str) -> Callable[[dict, dict], None]:
    """Increment state[target]."""
    def fold(state: dict, payload: dict) -> None:
        state[target] = state.get(target, 0) + 1
    return fold


def _make_sum(target: str, value_field: str) -> Callable[[dict, dict], None]:
    """Add payload[value_field] to state[target]."""
    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field, 0)
        state[target] = state.get(target, 0) + value
    return fold


def _make_collect(target: str, max_size: int) -> Callable[[dict, dict], None]:
    """Append payload to state[target] list, bounded by max_size."""
    def fold(state: dict, payload: dict) -> None:
        items = state[target]
        # Convert to dict in case payload is MappingProxyType
        items.append(dict(payload))
        if max_size and len(items) > max_size:
            state[target] = items[-max_size:]
    return fold


def _make_upsert(target: str, key_field: str) -> Callable[[dict, dict], None]:
    """Insert/update in dict keyed by key_field, tracking observation count and refs."""
    def fold(state: dict, payload: dict) -> None:
        key_value = payload.get(key_field)
        if key_value is not None:
            existing = state[target].get(key_value)
            n = (existing.get("_n", 0) if existing else 0) + 1
            # Accumulate refs across upserts
            prev_refs = set(existing.get("_refs", ())) if existing else set()
            new_ref = payload.get("ref", "")
            if new_ref:
                for r in new_ref.split(","):
                    r = r.strip()
                    if r:
                        prev_refs.add(r)
            entry = dict(payload)
            entry["_n"] = n
            if prev_refs:
                entry["_refs"] = sorted(prev_refs)
            state[target][key_value] = entry
    return fold


# =============================================================================
# Convenience fold implementations
# =============================================================================


def _make_top_n(
    target: str, key_field: str, by_field: str, n: int, desc: bool
) -> Callable[[dict, dict], None]:
    """Keep top N items by by_field, keyed by key_field."""
    def fold(state: dict, payload: dict) -> None:
        key_value = payload.get(key_field)
        by_value = payload.get(by_field)
        if key_value is None or by_value is None:
            return

        items = state[target]
        # Convert to dict in case payload is MappingProxyType
        items[key_value] = dict(payload)

        # Sort and trim to N items
        if len(items) > n:
            sorted_keys = sorted(
                items.keys(),
                key=lambda k: items[k].get(by_field, 0),
                reverse=desc,
            )
            # Keep only top N
            keep = set(sorted_keys[:n])
            state[target] = {k: v for k, v in items.items() if k in keep}

    return fold


def _make_min(target: str, value_field: str) -> Callable[[dict, dict], None]:
    """Track minimum value of payload[value_field]."""
    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field)
        if value is None:
            return
        current = state.get(target)
        if current is None or value < current:
            state[target] = value
    return fold


def _make_max(target: str, value_field: str) -> Callable[[dict, dict], None]:
    """Track maximum value of payload[value_field]."""
    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field)
        if value is None:
            return
        current = state.get(target)
        if current is None or value > current:
            state[target] = value
    return fold


def _make_avg(target: str, value_field: str) -> Callable[[dict, dict], None]:
    """Incremental running average of payload[value_field].

    Maintains hidden state: {target}_sum and {target}_count.
    """
    sum_key = f"{target}_sum"
    count_key = f"{target}_count"

    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field)
        if value is None:
            return
        state[sum_key] = state.get(sum_key, 0.0) + value
        state[count_key] = state.get(count_key, 0) + 1
        state[target] = state[sum_key] / state[count_key]

    return fold


def _make_window(target: str, value_field: str, size: int) -> Callable[[dict, dict], None]:
    """Sliding window: append field value and drop oldest when full."""
    def fold(state: dict, payload: dict) -> None:
        value = payload.get(value_field)
        if value is None:
            return
        items = state.get(target, [])
        items.append(value)
        if len(items) > size:
            items = items[-size:]
        state[target] = items

    return fold


# =============================================================================
# Build functions
# =============================================================================


def build_fold_fn(fold: FoldOp) -> Callable[[dict, dict], None]:
    """Build a callable (state, payload) -> None from a fold descriptor.

    Supports both typed classes and legacy Fold.
    """
    # Typed classes (preferred)
    if isinstance(fold, Latest):
        return _make_latest(fold.target)
    elif isinstance(fold, Count):
        return _make_count(fold.target)
    elif isinstance(fold, Sum):
        return _make_sum(fold.target, fold.field)
    elif isinstance(fold, Collect):
        return _make_collect(fold.target, fold.max)
    elif isinstance(fold, Upsert):
        return _make_upsert(fold.target, fold.key)
    elif isinstance(fold, TopN):
        return _make_top_n(fold.target, fold.key, fold.by, fold.n, fold.desc)
    elif isinstance(fold, Min):
        return _make_min(fold.target, fold.field)
    elif isinstance(fold, Max):
        return _make_max(fold.target, fold.field)
    elif isinstance(fold, Avg):
        return _make_avg(fold.target, fold.field)
    elif isinstance(fold, Window):
        return _make_window(fold.target, fold.field, fold.size)

    else:
        raise ValueError(f"Unknown fold type: {type(fold)}")


def build_fold_fns(folds: tuple[FoldOp, ...]) -> tuple[Callable[[dict, dict], None], ...]:
    """Build all fold functions for a sequence of folds."""
    return tuple(build_fold_fn(f) for f in folds)
