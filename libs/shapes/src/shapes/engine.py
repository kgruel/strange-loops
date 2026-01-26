"""Fold engine: build executable fold functions from Fold descriptors.

Each fold op (latest, count, sum, collect, upsert) becomes a closure
(state: dict, payload: dict) -> None that mutates state in place.
Shape.apply() uses these to produce new state from old state + payload.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .fold import Fold


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


def build_fold_fn(fold: Fold) -> Callable[[dict, dict], None]:
    """Build a callable (state, payload) -> None from a Fold descriptor."""
    target = fold.target
    match fold.op:
        case "latest":
            return _make_latest(target)
        case "count":
            return _make_count(target)
        case "sum":
            value_field = str(fold.props.get("field", target))
            return _make_sum(target, value_field)
        case "collect":
            max_size = int(fold.props.get("max", 0))
            return _make_collect(target, max_size)
        case "upsert":
            key_field = str(fold.props.get("key", ""))
            if not key_field:
                raise ValueError(f"upsert fold requires key= prop (target: {target})")
            return _make_upsert(target, key_field)
        case _:
            raise ValueError(f"Unknown fold op: {fold.op}")


def build_fold_fns(folds: tuple[Fold, ...]) -> tuple[Callable[[dict, dict], None], ...]:
    """Build all fold functions for a sequence of Folds."""
    return tuple(build_fold_fn(f) for f in folds)
