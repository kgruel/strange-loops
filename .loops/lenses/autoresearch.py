"""Autoresearch lens — experiment dashboard for optimization loops.

Renders experiment history with baseline/progress tracking, metric deltas,
and keep/discard status. Designed to match the pi-autoresearch display:

  Runs: 6  3 kept  3 discarded
  Baseline: ★ avg_top1: 0.77 #1
  Progress: ★ avg_top1: 0.81 #6 (+4.8%)

  #  commit   ★ avg_top1  avg_score  status    description
  1  eb479a1  0.77        0.74       keep      Baseline: current ...

Zoom levels:
- MINIMAL: "autoresearch: 6 runs, 3 kept, best emit_ms=1.3 (+87%)"
- SUMMARY: header (runs, baseline, progress with deltas)
- DETAILED: header + experiment table
- FULL: header + table with untruncated descriptions
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldItem, FoldSection, FoldState


# ---------------------------------------------------------------------------
# Config extraction
# ---------------------------------------------------------------------------

def _get_config(data: FoldState) -> dict[str, str]:
    """Extract config key-value pairs from the config section."""
    config: dict[str, str] = {}
    for section in data.sections:
        if section.kind == "config":
            for item in section.items:
                key = item.payload.get("key", "")
                value = item.payload.get("value", "")
                if key:
                    config[key] = value
    return config


def _get_experiments(data: FoldState) -> list[dict]:
    """Extract experiment list from the experiment section."""
    experiments = []
    for section in data.sections:
        if section.kind == "experiment":
            for item in section.items:
                experiments.append(dict(item.payload))
    return experiments


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _is_better(value: float, best: float, direction: str) -> bool:
    """Check if value is better than best given direction."""
    if direction == "higher":
        return value > best
    return value < best


def _format_delta(baseline: float, current: float) -> str:
    """Format percentage delta with sign."""
    if baseline == 0:
        return ""
    pct = ((current - baseline) / abs(baseline)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _format_metric(value: float) -> str:
    """Format a metric value — auto-detect precision."""
    if value == int(value):
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _find_metric_columns(experiments: list[dict]) -> list[str]:
    """Find payload keys that look like metrics (numeric values)."""
    skip = {"commit", "status", "description", "name", "message"}
    candidates: dict[str, int] = {}
    for exp in experiments:
        for key, val in exp.items():
            if key in skip:
                continue
            try:
                float(val)
                candidates[key] = candidates.get(key, 0) + 1
            except (ValueError, TypeError):
                pass
    # Return keys present in at least half the experiments, preserving order
    threshold = max(1, len(experiments) // 2)
    seen: list[str] = []
    for exp in experiments:
        for key in exp:
            if key not in seen and key in candidates and candidates[key] >= threshold:
                seen.append(key)
    return seen


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def fold_view(data: FoldState, zoom: Zoom, width: int | None) -> Block:
    """Render autoresearch dashboard."""
    config = _get_config(data)
    experiments = _get_experiments(data)
    plain = Style()
    muted = Style(dim=True)
    green = Style(fg="green")
    red = Style(fg="red")
    bold = Style(bold=True)

    objective = config.get("objective", "autoresearch")
    primary_metric = config.get("primary_metric", "")
    direction = config.get("direction", "lower")

    if not experiments:
        return Block.text(f"autoresearch: {objective} — no experiments yet", muted)

    # Compute stats
    total = len(experiments)
    kept = sum(1 for e in experiments if e.get("status") == "keep")
    discarded = total - kept
    metric_cols = _find_metric_columns(experiments)

    # If no primary metric configured, use first metric column
    if not primary_metric and metric_cols:
        primary_metric = metric_cols[0]

    # Find baseline and best values for primary metric
    baseline_val = None
    best_val = None
    best_idx = 0
    for i, exp in enumerate(experiments):
        try:
            val = float(exp.get(primary_metric, ""))
        except (ValueError, TypeError):
            continue
        if baseline_val is None:
            baseline_val = val
        if best_val is None or _is_better(val, best_val, direction):
            best_val = val
            best_idx = i

    # --- MINIMAL ---
    if zoom == Zoom.MINIMAL:
        parts = [f"autoresearch: {total} runs, {kept} kept"]
        if best_val is not None and baseline_val is not None:
            delta = _format_delta(baseline_val, best_val)
            parts.append(f"best {primary_metric}={_format_metric(best_val)} ({delta})")
        return Block.text(", ".join(parts), plain)

    # --- SUMMARY and above ---
    rows: list[Block] = []

    # Header: runs line
    runs_text = f"Runs: {total}  "
    runs_text += f"{kept} kept  {discarded} discarded"
    rows.append(Block.text(runs_text, bold))

    # Baseline
    if baseline_val is not None:
        bl_text = f"Baseline: ★ {primary_metric}: {_format_metric(baseline_val)} #1"
        rows.append(Block.text(bl_text, muted))

    # Progress
    if best_val is not None and baseline_val is not None:
        delta = _format_delta(baseline_val, best_val)
        prog_text = f"Progress: ★ {primary_metric}: {_format_metric(best_val)} #{best_idx + 1} ({delta})"
        rows.append(Block.text(prog_text, green if delta.startswith("+") == (direction == "higher") else red))

        # Secondary metrics
        secondary = [m for m in metric_cols if m != primary_metric]
        if secondary:
            sec_parts = []
            for m in secondary:
                bl = None
                best = None
                for exp in experiments:
                    try:
                        v = float(exp.get(m, ""))
                    except (ValueError, TypeError):
                        continue
                    if bl is None:
                        bl = v
                    if best is None or _is_better(v, best, direction):
                        best = v
                if bl is not None and best is not None:
                    sec_parts.append(f"{m}: {_format_metric(best)} {_format_delta(bl, best)}")
            if sec_parts:
                rows.append(Block.text("         " + "  ".join(sec_parts), muted))

    if zoom == Zoom.SUMMARY:
        return join_vertical(*rows)

    # --- DETAILED / FULL: experiment table ---
    rows.append(Block.text("", plain))  # spacer

    # Table header
    hdr_parts = [f"{'#':>3}  {'commit':<8}"]
    for m in metric_cols:
        marker = "★ " if m == primary_metric else "  "
        hdr_parts.append(f"{marker}{m:<10}")
    hdr_parts.append(f"{'status':<10}")
    hdr_parts.append("description")
    rows.append(Block.text("  ".join(hdr_parts), muted))

    # Table rows
    max_desc = 50 if zoom != Zoom.FULL else 200
    if width is not None:
        # Compute available space for description
        fixed = 3 + 2 + 8 + 2 + len(metric_cols) * 14 + 12
        max_desc = max(20, (width or 80) - fixed)

    for i, exp in enumerate(experiments):
        commit = str(exp.get("commit", "?"))[:7]
        status = str(exp.get("status", "?"))
        desc = str(exp.get("description", ""))
        if len(desc) > max_desc:
            desc = desc[:max_desc - 1] + "…"

        parts = [f"{i + 1:>3}  {commit:<8}"]
        for m in metric_cols:
            try:
                val = _format_metric(float(exp[m]))
            except (KeyError, ValueError, TypeError):
                val = "-"
            marker = "  " if m != primary_metric else "  "
            # Bold the primary metric value
            parts.append(f"{marker}{val:<10}")
        parts.append(f"{status:<10}")
        parts.append(desc)

        line = "  ".join(parts)
        if status == "keep":
            rows.append(Block.text(line, plain))
        else:
            rows.append(Block.text(line, muted))

    return join_vertical(*rows)
