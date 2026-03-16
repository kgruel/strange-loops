"""Autoresearch prompt lens — full operating context for the agent.

Renders everything the agent needs to run the autoresearch loop:
- Objective, metric, direction, scope (from config facts)
- Current state: runs, kept/discarded, baseline, best (computed from experiments)
- Experiment history (what was tried, what worked)
- Operating protocol (how to run the loop)

The agent reads this once at the start (or on resume) and has full context.
No separate .md or .jsonl files needed — the vertex IS the state.

Declared in autoresearch.vertex:
  lens { fold "autoresearch_prompt" }
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, join_vertical

if TYPE_CHECKING:
    from atoms import FoldState


def _get_config(data: "FoldState") -> dict[str, str]:
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


def _get_experiments(data: "FoldState") -> list[dict]:
    """Extract experiment list from the experiment section."""
    experiments = []
    for section in data.sections:
        if section.kind == "experiment":
            for item in section.items:
                experiments.append(dict(item.payload))
    return experiments


def _get_ideas(data: "FoldState") -> list[dict]:
    """Extract ideas from the idea section."""
    ideas = []
    for section in data.sections:
        if section.kind == "idea":
            for item in section.items:
                ideas.append(dict(item.payload))
    return ideas


def _format_metric(value: float) -> str:
    if value == int(value):
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _is_better(value: float, best: float, direction: str) -> bool:
    if direction == "higher":
        return value > best
    return value < best


def _format_delta(baseline: float, current: float) -> str:
    if baseline == 0:
        return ""
    pct = ((current - baseline) / abs(baseline)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _find_metric_columns(experiments: list[dict]) -> list[str]:
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
    threshold = max(1, len(experiments) // 2)
    seen: list[str] = []
    for exp in experiments:
        for key in exp:
            if key not in seen and key in candidates and candidates[key] >= threshold:
                seen.append(key)
    return seen


def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render autoresearch operating context for agent consumption."""
    config = _get_config(data)
    experiments = _get_experiments(data)
    ideas = _get_ideas(data)
    plain = Style()

    lines: list[str] = []

    # --- Header ---
    objective = config.get("objective", "optimization target not set")
    primary_metric = config.get("primary_metric", "")
    direction = config.get("direction", "lower")
    scope = config.get("scope", "")
    benchmark = config.get("benchmark", "./autoresearch.sh")
    checks = config.get("checks", "./autoresearch.checks.sh")

    lines.append(f"# Autoresearch: {objective}")
    lines.append("")

    # --- Config ---
    lines.append("## Configuration")
    lines.append(f"- **Primary metric**: `{primary_metric}` ({direction} is better)")
    if scope:
        lines.append(f"- **Scope**: `{scope}`")
    lines.append(f"- **Benchmark**: `{benchmark}`")
    lines.append(f"- **Checks**: `{checks}`")
    lines.append("")

    # --- Current state ---
    if experiments:
        metric_cols = _find_metric_columns(experiments)
        if not primary_metric and metric_cols:
            primary_metric = metric_cols[0]

        total = len(experiments)
        kept = sum(1 for e in experiments if e.get("status") == "keep")
        discarded = total - kept

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

        lines.append("## Current State")
        lines.append(f"Runs: {total} ({kept} kept, {discarded} discarded)")
        if baseline_val is not None and best_val is not None:
            delta = _format_delta(baseline_val, best_val)
            lines.append(f"Baseline: {primary_metric}={_format_metric(baseline_val)} (experiment #1)")
            lines.append(f"Best: {primary_metric}={_format_metric(best_val)} (experiment #{best_idx + 1}, {delta})")
        lines.append("")

        # Experiment history
        lines.append("## Experiment History")
        for i, exp in enumerate(experiments):
            commit = str(exp.get("commit", "?"))[:7]
            status = str(exp.get("status", "?"))
            desc = str(exp.get("description", ""))
            metric_parts = []
            for m in metric_cols:
                try:
                    metric_parts.append(f"{m}={_format_metric(float(exp[m]))}")
                except (KeyError, ValueError, TypeError):
                    pass
            metrics_str = ", ".join(metric_parts)
            lines.append(f"{i + 1}. [{status}] {commit} — {metrics_str} — {desc}")
        lines.append("")
    else:
        lines.append("## Current State")
        lines.append("No experiments yet. You are starting fresh.")
        lines.append("")

    # --- Ideas ---
    untried = [i for i in ideas if i.get("status", "untried") == "untried"]
    if untried:
        lines.append("## Untried Ideas")
        for idea in untried:
            name = idea.get("name", "?")
            desc = idea.get("description", "")
            lines.append(f"- {name}: {desc}" if desc else f"- {name}")
        lines.append("")

    # --- Protocol ---
    lines.append("## Protocol")
    lines.append("")
    lines.append("Follow this loop:")
    lines.append("")
    lines.append("1. **Review** the experiment history above. Understand what worked,")
    lines.append("   what didn't, and why. Don't retry approaches that already failed")
    lines.append("   unless you have a meaningfully different angle.")
    lines.append("")
    lines.append("2. **Choose** your next approach. If there are untried ideas above,")
    lines.append("   consider those. Otherwise, use what the history tells you about")
    lines.append("   where the remaining cost lives.")
    lines.append("")
    lines.append("3. **Implement** the change. Stay within the scope files.")
    lines.append("")
    lines.append(f"4. **Benchmark**: run `{benchmark}`.")
    lines.append(f"   Look for lines matching `METRIC {primary_metric}=<number>`.")
    lines.append("")
    lines.append(f"5. **Check**: run `{checks}`.")
    lines.append("   All tests must pass. If checks fail, revert and try something else.")
    lines.append("")
    lines.append(f"6. **If {primary_metric} improved AND checks pass**:")
    lines.append("   ```")
    lines.append("   git add <changed files>")
    lines.append("   git commit -m \"Description of what you changed\"")
    lines.append(f"   loops emit autoresearch experiment \\")
    lines.append(f"     commit=$(git rev-parse --short HEAD) status=keep \\")
    lines.append(f"     {primary_metric}=<value> description=\"what you did\"")
    lines.append("   ```")
    lines.append("")
    lines.append(f"7. **If {primary_metric} did NOT improve OR checks failed**:")
    lines.append("   ```")
    lines.append("   git checkout -- .")
    lines.append(f"   loops emit autoresearch experiment \\")
    lines.append(f"     commit=$(git rev-parse --short HEAD) status=discard \\")
    lines.append(f"     {primary_metric}=<value> description=\"what you tried\"")
    lines.append("   ```")
    lines.append("")
    lines.append("8. **Repeat** from step 1.")

    return Block.text("\n".join(lines), plain)
