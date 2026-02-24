"""Internal sparkline implementation shared across view-layer APIs."""

from __future__ import annotations

from typing import Literal, Sequence

SamplingStrategy = Literal["tail", "uniform"]
RangeSource = Literal["all", "sampled"]


def sparkline_text(
    values: Sequence[float],
    width: int,
    *,
    chars: Sequence[str],
    sampling: SamplingStrategy,
    range_source: RangeSource = "sampled",
    lo: float | None = None,
    hi: float | None = None,
    clamp: bool = False,
    pad_left: bool = False,
    pad_char: str = " ",
) -> str:
    """Render a sparkline string of exactly ``width`` characters.

    This is an internal helper used by both:
    - ``fidelis._components.sparkline`` (tail semantics + left padding)
    - ``fidelis._lens.chart_lens`` at ``zoom=1`` (uniform sampling + right padding)
    """
    if width <= 0:
        return ""

    if not values:
        return pad_char * width

    sampled = _sample(values, width, sampling)

    if lo is None or hi is None:
        src = values if range_source == "all" else sampled
        # sampled/src are non-empty when values is non-empty, but keep this safe.
        lo = min(src) if src else 0.0
        hi = max(src) if src else lo

    text = _map_to_chars(sampled, chars, lo=lo, hi=hi, clamp=clamp)

    if pad_left:
        return text.rjust(width, pad_char)
    return text.ljust(width, pad_char)


def _sample(values: Sequence[float], width: int, sampling: SamplingStrategy) -> list[float]:
    if len(values) <= width:
        return list(values)

    if sampling == "tail":
        return list(values[-width:])

    if sampling == "uniform":
        step = len(values) / width
        return [float(values[int(i * step)]) for i in range(width)]

    raise ValueError(f"Unknown sampling strategy: {sampling}")


def _map_to_chars(values: Sequence[float], chars: Sequence[str], *, lo: float, hi: float, clamp: bool) -> str:
    if not values:
        return ""

    span = hi - lo if hi > lo else 1.0
    num_levels = len(chars)
    if num_levels <= 0:
        return ""

    out: list[str] = []
    for v in values:
        v_use = min(hi, max(lo, v)) if clamp else v
        ratio = (v_use - lo) / span
        idx = int(ratio * (num_levels - 1))
        idx = max(0, min(num_levels - 1, idx))
        out.append(chars[idx])

    return "".join(out)
