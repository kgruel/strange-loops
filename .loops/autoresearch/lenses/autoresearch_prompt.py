"""Autoresearch prompt lens — XML-structured experiment state for agent consumption.

Renders the dynamic user prompt for a one-shot autoresearch agent.
The system prompt (system-prompt.md) provides the cached protocol;
this lens provides the changing experiment state.

Output is XML-structured for clear parsing by the agent:
  <experiment>
    <config/>        — objective, metric, direction, scope
    <state/>         — runs, baseline, best, delta
    <findings/>      — knowledge map (by target, all shown)
    <history/>       — experiment results (total/showing windowed)
    <logs/>          — sequential narrative (total/showing windowed)
    <hypotheses/>    — testable predictions (all shown)
    <ideas/>         — things to try (all shown)
  </experiment>

Longform data at top, per Anthropic prompting best practices.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom

if TYPE_CHECKING:
    from atoms import FoldState, FoldItem

# How many collected items to show inline (rest available via --facts)
HISTORY_WINDOW = 5
LOG_WINDOW = 5


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _get_section(data: "FoldState", kind: str) -> list["FoldItem"]:
    """Get items for a kind from fold state."""
    for section in data.sections:
        if section.kind == kind:
            return list(section.items)
    return []


def _get_config(data: "FoldState") -> dict[str, str]:
    """Extract config key-value pairs."""
    config: dict[str, str] = {}
    for item in _get_section(data, "config"):
        key = item.payload.get("key", "")
        value = item.payload.get("value", "")
        if key:
            config[key] = value
    return config


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------

def _format_metric(value: float) -> str:
    if value == int(value):
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


def _is_better(value: float, best: float, direction: str) -> bool:
    return value > best if direction == "higher" else value < best


def _format_delta(baseline: float, current: float) -> str:
    if baseline == 0:
        return ""
    pct = ((current - baseline) / abs(baseline)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _find_metric_columns(experiments: list[dict]) -> list[str]:
    """Auto-detect numeric metric columns from experiment payloads."""
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


# ---------------------------------------------------------------------------
# XML rendering
# ---------------------------------------------------------------------------

def _xml_escape(text: str) -> str:
    """Minimal XML escaping for attribute values."""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def _render_config(config: dict[str, str], vertex: str) -> list[str]:
    """Render <config> section."""
    lines = ["<config>"]
    lines.append(f'  <objective>{_xml_escape(config.get("objective", "not set"))}</objective>')
    pm = config.get("primary_metric", "")
    direction = config.get("direction", "lower")
    lines.append(f'  <metric name="{_xml_escape(pm)}" direction="{direction}"/>')
    scope = config.get("scope", "")
    if scope:
        lines.append(f'  <scope>{_xml_escape(scope)}</scope>')
    lines.append(f'  <benchmark>{_xml_escape(config.get("benchmark", "./autoresearch.sh"))}</benchmark>')
    lines.append(f'  <checks>{_xml_escape(config.get("checks", "./autoresearch.checks.sh"))}</checks>')
    lines.append(f'  <vertex>{_xml_escape(vertex)}</vertex>')
    lines.append("</config>")
    return lines


def _render_state(experiments: list[dict], primary_metric: str, direction: str) -> list[str]:
    """Render <state> section with summary stats."""
    if not experiments:
        return ['<state runs="0"/>', ""]

    total = len(experiments)
    kept = sum(1 for e in experiments if e.get("status") == "keep")
    discarded = total - kept

    baseline_val = None
    best_val = None
    best_run = 0

    for i, exp in enumerate(experiments):
        try:
            val = float(exp.get(primary_metric, ""))
        except (ValueError, TypeError):
            continue
        if baseline_val is None:
            baseline_val = val
        if best_val is None or _is_better(val, best_val, direction):
            best_val = val
            best_run = i + 1

    lines = [f'<state runs="{total}" kept="{kept}" discarded="{discarded}">']
    if baseline_val is not None:
        lines.append(f'  <baseline metric="{primary_metric}" value="{_format_metric(baseline_val)}" run="1"/>')
    if best_val is not None and baseline_val is not None:
        delta = _format_delta(baseline_val, best_val)
        lines.append(f'  <best metric="{primary_metric}" value="{_format_metric(best_val)}" run="{best_run}" delta="{delta}"/>')
    lines.append("</state>")
    return lines


def _render_findings(items: list["FoldItem"]) -> list[str]:
    """Render <findings> — knowledge map, all items shown (folded by target)."""
    if not items:
        return []
    lines = [f'<findings total="{len(items)}">']
    for item in items:
        target = _xml_escape(str(item.payload.get("target", "?")))
        message = _xml_escape(str(item.payload.get("message", "")))
        lines.append(f'  <finding target="{target}">{message}</finding>')
    lines.append("</findings>")
    return lines


def _render_history(
    experiments: list[dict], metric_cols: list[str], window: int,
) -> list[str]:
    """Render <history> — experiment results with total/showing windowing."""
    total = len(experiments)
    if total == 0:
        return ['<history total="0"/>']

    show = experiments[-window:] if total > window else experiments
    offset = total - len(show)

    lines = [f'<history total="{total}" showing="{len(show)}">']
    for i, exp in enumerate(show):
        run = offset + i + 1
        commit = str(exp.get("commit", "?"))[:7]
        status = str(exp.get("status", "?"))
        desc = _xml_escape(str(exp.get("description", "")))

        # Build metric attributes
        metric_attrs = ""
        for m in metric_cols:
            try:
                metric_attrs += f' {m}="{_format_metric(float(exp[m]))}"'
            except (KeyError, ValueError, TypeError):
                pass

        lines.append(f'  <run n="{run}" commit="{commit}" status="{status}"{metric_attrs}>{desc}</run>')
    lines.append("</history>")
    return lines


def _render_logs(items: list["FoldItem"], window: int) -> list[str]:
    """Render <logs> — sequential narrative with total/showing windowing."""
    total = len(items)
    if total == 0:
        return []

    show = items[-window:] if total > window else items
    lines = [f'<logs total="{total}" showing="{len(show)}">']
    for item in show:
        log_type = _xml_escape(str(item.payload.get("type", "")))
        message = _xml_escape(str(item.payload.get("message", "")))
        files = item.payload.get("files", "")
        ref = item.payload.get("ref", "")

        attrs = f' type="{log_type}"' if log_type else ""
        if files:
            attrs += f' files="{_xml_escape(str(files))}"'
        if ref:
            attrs += f' ref="{_xml_escape(str(ref))}"'
        lines.append(f"  <log{attrs}>{message}</log>")
    lines.append("</logs>")
    return lines


def _render_hypotheses(items: list["FoldItem"]) -> list[str]:
    """Render <hypotheses> — all shown (folded by name)."""
    if not items:
        return []
    lines = [f'<hypotheses total="{len(items)}">']
    for item in items:
        name = _xml_escape(str(item.payload.get("name", "?")))
        status = _xml_escape(str(item.payload.get("status", "proposed")))
        prediction = item.payload.get("prediction", "")
        evidence = item.payload.get("evidence", "")

        attrs = f'name="{name}" status="{status}"'
        content = _xml_escape(str(prediction)) if prediction else _xml_escape(str(evidence))
        lines.append(f"  <hypothesis {attrs}>{content}</hypothesis>")
    lines.append("</hypotheses>")
    return lines


def _render_ideas(items: list["FoldItem"]) -> list[str]:
    """Render <ideas> — all shown (folded by name)."""
    if not items:
        return []
    lines = [f'<ideas total="{len(items)}">']
    for item in items:
        name = _xml_escape(str(item.payload.get("name", "?")))
        status = _xml_escape(str(item.payload.get("status", "untried")))
        desc = _xml_escape(str(item.payload.get("description", "")))
        files = item.payload.get("files", "")

        attrs = f'name="{name}" status="{status}"'
        if files:
            attrs += f' files="{_xml_escape(str(files))}"'
        lines.append(f"  <idea {attrs}>{desc}</idea>")
    lines.append("</ideas>")
    return lines


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def fold_view(
    data: "FoldState", zoom: Zoom, width: int | None, *, vertex_name: str | None = None, **kwargs,
) -> Block:
    """Render XML-structured experiment state for agent consumption."""
    config = _get_config(data)
    vertex = vertex_name or data.vertex or "VERTEX"
    primary_metric = config.get("primary_metric", "")
    direction = config.get("direction", "lower")

    experiments = [dict(item.payload) for item in _get_section(data, "experiment")]
    findings = _get_section(data, "finding")
    logs = _get_section(data, "log")
    hypotheses = _get_section(data, "hypothesis")
    ideas = _get_section(data, "idea")

    metric_cols = _find_metric_columns(experiments)
    if not primary_metric and metric_cols:
        primary_metric = metric_cols[0]

    # Assemble XML — longform data at top, per Anthropic guidance
    lines: list[str] = []
    lines.append(f'<experiment vertex="{_xml_escape(vertex)}">')
    lines.append("")

    lines.extend(_render_config(config, vertex))
    lines.append("")

    lines.extend(_render_state(experiments, primary_metric, direction))
    lines.append("")

    # Knowledge map first — durable understanding
    if findings:
        lines.extend(_render_findings(findings))
        lines.append("")

    # Experiment history — windowed
    lines.extend(_render_history(experiments, metric_cols, HISTORY_WINDOW))
    lines.append("")

    # Logs — windowed sequential narrative
    if logs:
        lines.extend(_render_logs(logs, LOG_WINDOW))
        lines.append("")

    # Hypotheses — all shown (keyed, usually few)
    if hypotheses:
        lines.extend(_render_hypotheses(hypotheses))
        lines.append("")

    # Ideas — all shown (keyed, usually few)
    if ideas:
        lines.extend(_render_ideas(ideas))
        lines.append("")

    lines.append("</experiment>")

    return Block.text("\n".join(lines), Style())
