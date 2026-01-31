"""Fold engine: build executable fold functions from fold descriptors.

Each fold op becomes a closure (state: dict, payload: dict) -> None
that mutates state in place. Spec.apply() uses these to produce new
state from old state + payload.

Typed fold classes: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max
"""

from __future__ import annotations

import time
from typing import Callable

from .fold import (
    Collect,
    Count,
    FoldOp,
    Latest,
    Max,
    Min,
    Sum,
    TopN,
    Upsert,
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
        items.append(payload)
        if max_size and len(items) > max_size:
            state[target] = items[-max_size:]
    return fold


def _make_upsert(target: str, key_field: str) -> Callable[[dict, dict], None]:
    """Insert/update in dict keyed by key_field."""
    def fold(state: dict, payload: dict) -> None:
        key_value = payload.get(key_field)
        if key_value is not None:
            state[target][key_value] = payload
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
        items[key_value] = payload

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

    else:
        raise ValueError(f"Unknown fold type: {type(fold)}")


def build_fold_fns(folds: tuple[FoldOp, ...]) -> tuple[Callable[[dict, dict], None], ...]:
    """Build all fold functions for a sequence of folds."""
    return tuple(build_fold_fn(f) for f in folds)
