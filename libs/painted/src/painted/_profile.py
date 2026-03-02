"""Profile bridge: cProfile and collapsed-stacks → flame_lens dicts."""

from __future__ import annotations

import cProfile
import pstats
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

__all__ = ["ProfileResult", "profile", "parse_collapsed"]


@dataclass(frozen=True)
class ProfileResult:
    """Converted profiling data, ready for flame_lens."""

    flame_dict: dict[str, Any]
    total_time: float
    call_count: int


@contextmanager
def profile(*, top_n: int = 20, module: str | None = None):
    """Profile a code block via cProfile, yield a ProfileResult.

    Result is appended to the yielded list on exit (not available until
    the with-block completes).  Access via ``result[0]`` after the block.

    Args:
        top_n: Keep only the N most expensive call paths (by cumulative time).
        module: If set, only include functions whose filename contains this
                string (e.g. "painted" filters to painted sources only).
    """
    pr = cProfile.Profile()
    result_box: list[ProfileResult] = []
    pr.enable()
    try:
        yield result_box
    finally:
        pr.disable()
        stats = pstats.Stats(pr)
        flame_dict = _stats_to_flame_dict(stats.stats, top_n=top_n, module=module)
        total = sum(ct for _, _, _, ct, _ in stats.stats.values())
        calls = sum(nc for _, nc, _, _, _ in stats.stats.values())
        result_box.append(ProfileResult(flame_dict=flame_dict, total_time=total, call_count=calls))


def parse_collapsed(text: str) -> dict[str, Any]:
    """Parse Brendan Gregg collapsed-stack format into flame_lens dict.

    Format: one line per unique stack, semicolon-separated frames, space + count.
        main;handle_request;parse_json 150
        main;render_response;serialize 42
    """
    root: dict[str, Any] = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        stack_str, _, count_str = line.rpartition(" ")
        if not stack_str:
            continue
        try:
            count = int(count_str)
        except ValueError:
            continue
        frames = stack_str.split(";")
        node = root
        for frame in frames[:-1]:
            existing = node.get(frame)
            if existing is None:
                node[frame] = {}
            elif not isinstance(existing, dict):
                node[frame] = {"[self]": existing}
            node = node[frame]
        leaf = frames[-1]
        if isinstance(node.get(leaf), dict):
            node[leaf]["[self]"] = node[leaf].get("[self]", 0) + count
        else:
            node[leaf] = node.get(leaf, 0) + count
    return root


# ---------------------------------------------------------------------------
# Internal: cProfile stats → flame dict
# ---------------------------------------------------------------------------


def _stats_to_flame_dict(
    raw_stats: dict,
    *,
    top_n: int = 20,
    module: str | None = None,
) -> dict[str, Any]:
    """Convert cProfile stats dict to flame_lens-compatible nested dict.

    Walks the caller graph from roots to leaves:
    1. Invert callers → children
    2. Find roots (uncalled functions)
    3. DFS with cycle guard, using self-time (tt) for leaf values
    4. Branch functions with self-time get a ``[self]`` entry
    """
    if not raw_stats:
        return {}

    # Filter by module prefix (substring match on filename)
    if module:
        filtered = {k: v for k, v in raw_stats.items() if module in k[0]}
    else:
        filtered = dict(raw_stats)

    if not filtered:
        return {}

    # Keep top_n by cumulative time (index 3 = ct)
    ranked = sorted(filtered, key=lambda k: filtered[k][3], reverse=True)
    keep = set(ranked[:top_n])

    # Invert callers → children
    children: dict[tuple, list[tuple]] = {}
    called: set[tuple] = set()

    for func_key in keep:
        _cc, _nc, _tt, _ct, callers = filtered[func_key]
        for caller_key in callers:
            if caller_key in keep:
                children.setdefault(caller_key, []).append(func_key)
                called.add(func_key)

    # Roots: in keep but not called by anyone in keep
    roots = sorted(
        [k for k in keep if k not in called],
        key=lambda k: filtered[k][3],
        reverse=True,
    )
    if not roots:
        roots = [ranked[0]]

    # Label disambiguation: short name unless collisions exist
    name_counts: dict[str, int] = {}
    for k in keep:
        name_counts[k[2]] = name_counts.get(k[2], 0) + 1

    def _label(key: tuple) -> str:
        name = key[2]
        if name_counts.get(name, 0) > 1:
            basename = key[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            return f"{basename}:{name}"
        return name

    # DFS with cycle guard (visited is never cleared — each func appears once)
    visited: set[tuple] = set()

    def _build(key: tuple) -> dict[str, Any] | float | None:
        if key in visited:
            return None
        visited.add(key)

        _cc, _nc, tt, _ct, _ = filtered[key]
        kids = sorted(
            [k for k in children.get(key, []) if k in keep],
            key=lambda k: filtered[k][3],
            reverse=True,
        )

        if not kids:
            return float(tt)

        result: dict[str, Any] = {}
        for child in kids:
            child_val = _build(child)
            if child_val is not None:
                result[_label(child)] = child_val

        if tt > 0:
            result["[self]"] = float(tt)

        return result if result else float(tt)

    flame: dict[str, Any] = {}
    for root in roots:
        val = _build(root)
        if val is not None:
            flame[_label(root)] = val

    return flame
