"""Autoresearch dashboard lens — full optimization state at a glance.

Two-panel header (status + config), experiment table, knowledge sections.
At SUMMARY: findings + ideas side by side as compact lists.
At DETAILED+: two-column layout with word-wrapped descriptions and row spacing.

Zoom levels:
- MINIMAL: one-line progress summary
- SUMMARY: header panels + experiments + findings|ideas side-by-side + logs
- DETAILED: findings/ideas break out with descriptions, row spacing, logs expanded
- FULL: everything + fact IDs
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from painted import Block, Style, Zoom, Wrap
from painted import join_vertical, join_horizontal, border, pad

if TYPE_CHECKING:
    from atoms import FoldItem, FoldState


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

def _get_section(data: "FoldState", kind: str) -> list["FoldItem"]:
    for section in data.sections:
        if section.kind == kind:
            return list(section.items)
    return []


def _get_config(data: "FoldState") -> dict[str, str]:
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

def _is_better(value: float, best: float, direction: str) -> bool:
    return value > best if direction == "higher" else value < best


def _format_delta(baseline: float, current: float) -> str:
    if baseline == 0:
        return ""
    pct = ((current - baseline) / abs(baseline)) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _format_metric(value: float) -> str:
    if value == int(value):
        return str(int(value))
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 1:
        return f"{value:.2f}"
    return f"{value:.3f}"


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


def _compute_progress(
    experiments: list[dict], primary_metric: str, direction: str,
) -> tuple[float | None, float | None, int]:
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
    return baseline_val, best_val, best_idx + 1


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _section_header(title: str, count: int | None, w: int) -> Block:
    """── Title (N) ─────────"""
    muted = Style(dim=True)
    label = title
    if count is not None:
        label += f" ({count})"
    prefix = "\u2500\u2500 "
    suffix_len = max(0, w - len(prefix) - len(label) - 1)
    rule = f"{prefix}{label} " + "\u2500" * suffix_len
    return Block.text(rule, muted)


def _spacer() -> Block:
    return Block.text("", Style())


# ---------------------------------------------------------------------------
# Header panels
# ---------------------------------------------------------------------------

def _detect_in_progress(
    experiment_items: list["FoldItem"],
    supporting_items: list["FoldItem"],
) -> bool:
    """Detect if an iteration is in-flight.

    True when there are supporting facts (logs, findings, ideas) newer
    than the most recent experiment. This means the agent is emitting
    but the wrapper hasn't finished benchmarking yet.
    """
    if not supporting_items:
        return False
    last_exp_ts = max((item.ts or 0) for item in experiment_items) if experiment_items else 0
    last_support_ts = max((item.ts or 0) for item in supporting_items)
    return last_support_ts > last_exp_ts


def _render_header_panels(
    config: dict[str, str],
    experiments: list[dict],
    primary_metric: str,
    direction: str,
    baseline_val: float | None,
    best_val: float | None,
    best_run: int,
    w: int,
    in_progress: bool = False,
) -> Block:
    """Two bordered panels: status (left) + config (right)."""
    muted = Style(dim=True)
    border_style = Style(dim=True)

    total = len(experiments)
    kept = sum(1 for e in experiments if e.get("status") == "keep")
    discarded = total - kept

    # Border adds 2, pad adds 2 = 4 per panel, 1 gap between
    gap = 1
    inner_total = w - gap - 8

    status_texts = [
        (f"Runs: {total}   {kept} kept   {discarded} discarded", Style(bold=True)),
    ]
    if in_progress:
        status_texts.append((f">> iteration #{total + 1} in progress", Style(fg="yellow")))
    if baseline_val is not None:
        bl_s = _format_metric(baseline_val)
        status_texts.append((f"Baseline: * {primary_metric}: {bl_s} #1", muted))
    if best_val is not None and baseline_val is not None:
        delta = _format_delta(baseline_val, best_val)
        best_s = _format_metric(best_val)
        improved = _is_better(best_val, baseline_val, direction)
        color = Style(fg="green", bold=True) if improved else Style(fg="red", bold=True)
        status_texts.append((f"Progress: * {primary_metric}: {best_s} #{best_run} ({delta})", color))

    left_inner = max(len(t) for t, _ in status_texts)
    left_inner = min(left_inner, inner_total * 60 // 100)
    left_inner = max(20, left_inner)
    right_inner = max(15, inner_total - left_inner)

    config_texts: list[tuple[str, Style]] = []
    for key in ["primary_metric", "direction", "scope"]:
        val = config.get(key, "")
        if val:
            config_texts.append((f"{key}: {val}", muted))

    left_content = join_vertical(
        *[Block.text(t, s, width=left_inner) for t, s in status_texts]
    )
    right_content = join_vertical(
        *[Block.text(t, s, width=right_inner, wrap=Wrap.WORD) for t, s in config_texts]
    ) if config_texts else Block.empty(right_inner, 1)

    left_panel = border(
        pad(left_content, left=1, right=1),
        title=config.get("objective", "autoresearch"),
        title_style=Style(bold=True),
        style=border_style,
    )
    right_panel = border(
        pad(right_content, left=1, right=1),
        title="Config",
        title_style=muted,
        style=border_style,
    )

    return join_horizontal(left_panel, right_panel, gap=gap)


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def _render_experiments(
    experiments: list[dict],
    metric_cols: list[str],
    primary_metric: str,
    show_ids: bool,
    window: int | None = None,
) -> list[Block]:
    plain = Style()
    muted = Style(dim=True)
    rows: list[Block] = []

    total = len(experiments)
    show = experiments
    earlier = 0
    if window is not None and total > window:
        show = experiments[-window:]
        earlier = total - window

    hdr_parts = [f"{'#':>3}  {'commit':<8}"]
    for m in metric_cols:
        marker = "* " if m == primary_metric else "  "
        hdr_parts.append(f"{marker}{m:<12}")
    hdr_parts.append(f"{'status':<10}")
    hdr_parts.append("description")
    rows.append(Block.text("  ".join(hdr_parts), muted))

    if earlier > 0:
        rows.append(Block.text(f"  ... {earlier} earlier runs", muted))

    for i, exp in enumerate(show):
        run_num = earlier + i + 1
        commit = str(exp.get("commit", "?"))[:7]
        status = str(exp.get("status", "?"))
        desc = str(exp.get("description", ""))

        parts = [f"{run_num:>3}  {commit:<8}"]
        for m in metric_cols:
            try:
                val = _format_metric(float(exp[m]))
            except (KeyError, ValueError, TypeError):
                val = "-"
            parts.append(f"  {val:<12}")
        parts.append(f"{status:<10}")
        parts.append(desc)

        line = "  ".join(parts)
        style = plain if status == "keep" else muted
        rows.append(Block.text(line, style))

    return rows


# ---------------------------------------------------------------------------
# Findings — compact list (SUMMARY) or two-column detail (DETAILED+)
# ---------------------------------------------------------------------------

def _render_findings_compact(
    items: list["FoldItem"], col_w: int,
) -> Block:
    """Compact list of finding targets for side-by-side display."""
    accent = Style(fg="cyan")
    lines = [
        Block.text(f"  {str(item.payload.get('target', '?'))}", accent, width=col_w)
        for item in items
    ]
    return join_vertical(*lines) if lines else Block.empty(col_w, 1)


def _render_findings_detail(
    items: list["FoldItem"], w: int, show_ids: bool,
) -> list[Block]:
    """Two-column findings with row spacing."""
    plain = Style()
    accent = Style(fg="cyan")
    rows: list[Block] = []

    targets = [str(item.payload.get("target", "?")) for item in items]
    col_w = min(max(len(t) for t in targets) + 2, 30)
    msg_w = max(20, w - col_w - 4)

    for i, (item, target) in enumerate(zip(items, targets)):
        message = str(item.payload.get("message", ""))

        left_lines = [target]
        if show_ids and item.id:
            left_lines.append(f"id:{item.id[:8]}")

        left_block = join_vertical(
            *[Block.text(l, accent, width=col_w) for l in left_lines]
        )

        if message:
            right_block = Block.text(message, plain, width=msg_w, wrap=Wrap.WORD)
            row = pad(join_horizontal(left_block, right_block, gap=2), left=2)
        else:
            row = pad(left_block, left=2)

        rows.append(row)
        # Row spacing between items (not after last)
        if i < len(items) - 1:
            rows.append(_spacer())

    return rows


# ---------------------------------------------------------------------------
# Ideas — compact list (SUMMARY) or two-column detail (DETAILED+)
# ---------------------------------------------------------------------------

def _render_ideas_compact(
    items: list["FoldItem"], col_w: int,
) -> Block:
    """Compact list of ideas for side-by-side display."""
    plain = Style()
    green = Style(fg="green")
    muted = Style(dim=True)

    lines: list[Block] = []
    for item in items:
        name = str(item.payload.get("name", "?"))
        status = str(item.payload.get("status", "untried"))

        if status == "tried":
            indicator, style = "+", green
        elif status == "rejected":
            indicator, style = "x", muted
        else:
            indicator, style = "o", plain

        lines.append(Block.text(f"  {indicator} {name}", style, width=col_w))

    return join_vertical(*lines) if lines else Block.empty(col_w, 1)


def _render_ideas_detail(
    items: list["FoldItem"], w: int, show_ids: bool,
) -> list[Block]:
    """Two-column ideas with descriptions and row spacing."""
    plain = Style()
    muted = Style(dim=True)
    green = Style(fg="green")
    rows: list[Block] = []

    names = [str(item.payload.get("name", "?")) for item in items]
    col_w = min(max(len(n) for n in names) + 4, 35)
    msg_w = max(20, w - col_w - 4)

    for i, (item, name) in enumerate(zip(items, names)):
        status = str(item.payload.get("status", "untried"))
        desc = str(item.payload.get("description", ""))

        if status == "tried":
            indicator, style = "+", green
        elif status == "rejected":
            indicator, style = "x", muted
        else:
            indicator, style = "o", plain

        left_lines = [f"{indicator} {name}"]
        if show_ids and item.id:
            left_lines.append(f"  id:{item.id[:8]}")

        left_block = join_vertical(
            *[Block.text(l, style, width=col_w) for l in left_lines]
        )

        if desc:
            right_block = Block.text(desc, plain, width=msg_w, wrap=Wrap.WORD)
            row = pad(join_horizontal(left_block, right_block, gap=2), left=2)
        else:
            row = pad(left_block, left=2)

        rows.append(row)
        if i < len(items) - 1:
            rows.append(_spacer())

    return rows


# ---------------------------------------------------------------------------
# Hypotheses
# ---------------------------------------------------------------------------

def _render_hypotheses(items: list["FoldItem"], w: int, show_ids: bool) -> list[Block]:
    if not items:
        return []

    plain = Style()
    muted = Style(dim=True)
    green = Style(fg="green")
    red = Style(fg="red")
    rows: list[Block] = []

    for item in items:
        name = str(item.payload.get("name", "?"))
        status = str(item.payload.get("status", "proposed"))
        prediction = str(item.payload.get("prediction", ""))
        evidence = str(item.payload.get("evidence", ""))

        if status == "confirmed":
            style = green
        elif status == "rejected":
            style = red
        else:
            style = plain

        line = f"  [{status}] {name}"
        content = prediction or evidence
        if content:
            line += f"  {content}"
        if show_ids and item.id:
            line += f"  id:{item.id[:8]}"
        rows.append(Block.text(line, style))

    return rows


# ---------------------------------------------------------------------------
# Logs — type tag muted, message plain
# ---------------------------------------------------------------------------

def _render_logs(items: list["FoldItem"], w: int, window: int, show_ids: bool) -> list[Block]:
    if not items:
        return []

    plain = Style()
    muted = Style(dim=True)
    rows: list[Block] = []

    total = len(items)
    show = items[-window:] if total > window else items

    type_col = 12
    msg_w = max(20, w - type_col - 4)

    for i, item in enumerate(show):
        log_type = str(item.payload.get("type", ""))
        message = str(item.payload.get("message", ""))
        files = item.payload.get("files", "")

        type_tag = f"[{log_type}]" if log_type else ""

        left = Block.text(type_tag, muted, width=type_col)

        msg_text = message
        if files:
            msg_text += f"  ({files})"
        if show_ids and item.id:
            msg_text += f"  id:{item.id[:8]}"

        right = Block.text(msg_text, plain, width=msg_w, wrap=Wrap.WORD)

        rows.append(pad(join_horizontal(left, right), left=2))
        # Row spacing between log entries
        if i < len(show) - 1:
            rows.append(_spacer())

    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def fold_view(data: "FoldState", zoom: Zoom, width: int | None, **kwargs) -> Block:
    """Render autoresearch dashboard."""
    config = _get_config(data)
    experiment_items = _get_section(data, "experiment")
    experiments = [dict(item.payload) for item in experiment_items]
    findings = _get_section(data, "finding")
    ideas = _get_section(data, "idea")
    hypotheses = _get_section(data, "hypothesis")
    logs = _get_section(data, "log")

    # Detect in-progress iteration: supporting facts newer than last experiment
    supporting = findings + ideas + logs + hypotheses
    in_progress = _detect_in_progress(experiment_items, supporting)

    primary_metric = config.get("primary_metric", "")
    direction = config.get("direction", "lower")
    metric_cols = _find_metric_columns(experiments)
    if not primary_metric and metric_cols:
        primary_metric = metric_cols[0]

    baseline_val, best_val, best_run = _compute_progress(
        experiments, primary_metric, direction,
    )

    w = width or 80
    show_ids = zoom == Zoom.FULL

    # --- MINIMAL ---
    if zoom == Zoom.MINIMAL:
        total = len(experiments)
        kept = sum(1 for e in experiments if e.get("status") == "keep")
        parts = [f"autoresearch: {total} runs, {kept} kept"]
        if best_val is not None and baseline_val is not None:
            delta = _format_delta(baseline_val, best_val)
            bl_s = _format_metric(baseline_val)
            best_s = _format_metric(best_val)
            parts.append(f"{primary_metric} {bl_s}->{best_s} ({delta})")
        if in_progress:
            parts.append(f">> running #{total + 1}")
        return Block.text(", ".join(parts), Style())

    # --- No experiments yet ---
    if not experiments:
        objective = config.get("objective", "autoresearch")
        muted = Style(dim=True)
        label = f"autoresearch: {objective}"
        if in_progress:
            label += "  >> running #1"
        rows: list[Block] = [Block.text(label, Style(bold=True))]
        if findings:
            rows.append(_section_header("Findings", len(findings), w))
            rows.extend(_render_findings_detail(findings, w, False))
        if ideas:
            rows.append(_section_header("Ideas", len(ideas), w))
            rows.extend(_render_ideas_detail(ideas, w, False))
        if logs:
            rows.append(_section_header("Logs", len(logs), w))
            rows.extend(_render_logs(logs, w, 10, False))
        if not findings and not ideas and not logs:
            rows.append(Block.text("No experiments yet", muted))
        return join_vertical(*rows)

    # --- SUMMARY and above ---
    rows: list[Block] = []

    # Header panels: status + config
    rows.append(_render_header_panels(
        config, experiments, primary_metric, direction,
        baseline_val, best_val, best_run, w,
        in_progress=in_progress,
    ))

    # Experiments
    exp_window = 10 if zoom == Zoom.SUMMARY else None
    rows.append(_spacer())
    rows.append(_section_header("Experiments", len(experiments), w))
    rows.extend(_render_experiments(
        experiments, metric_cols, primary_metric,
        show_ids=show_ids, window=exp_window,
    ))

    if zoom == Zoom.SUMMARY:
        # --- SUMMARY: findings + ideas side by side ---
        if findings or ideas:
            rows.append(_spacer())
            gap = 2
            half_w = (w - gap) // 2

            left_parts: list[Block] = []
            right_parts: list[Block] = []

            if findings:
                left_parts.append(_section_header("Findings", len(findings), half_w))
                left_parts.append(_render_findings_compact(findings, half_w))
            if ideas:
                right_parts.append(_section_header("Ideas", len(ideas), half_w))
                right_parts.append(_render_ideas_compact(ideas, half_w))

            if left_parts and right_parts:
                left_block = join_vertical(*left_parts)
                right_block = join_vertical(*right_parts)
                rows.append(join_horizontal(left_block, right_block, gap=gap))
            elif left_parts:
                rows.extend(left_parts)
            elif right_parts:
                rows.extend(right_parts)

        if hypotheses:
            rows.append(_spacer())
            rows.append(_section_header("Hypotheses", len(hypotheses), w))
            rows.extend(_render_hypotheses(hypotheses, w, show_ids))

        # Logs — always shown, compact at summary
        if logs:
            log_window = 5
            rows.append(_spacer())
            total_logs = len(logs)
            showing = f" showing {log_window}" if total_logs > log_window else ""
            rows.append(_section_header(f"Logs{showing}", total_logs, w))
            rows.extend(_render_logs(logs, w, log_window, show_ids))

        return join_vertical(*rows)

    # --- DETAILED / FULL: findings and ideas broken out with descriptions ---
    if findings:
        rows.append(_spacer())
        rows.append(_section_header("Findings", len(findings), w))
        rows.extend(_render_findings_detail(findings, w, show_ids))

    if ideas:
        rows.append(_spacer())
        rows.append(_section_header("Ideas", len(ideas), w))
        rows.extend(_render_ideas_detail(ideas, w, show_ids))

    if hypotheses:
        rows.append(_spacer())
        rows.append(_section_header("Hypotheses", len(hypotheses), w))
        rows.extend(_render_hypotheses(hypotheses, w, show_ids))

    # Logs — expanded at detail+
    if logs:
        log_window = 20
        rows.append(_spacer())
        total_logs = len(logs)
        showing = f" showing {log_window}" if total_logs > log_window else ""
        rows.append(_section_header(f"Logs{showing}", total_logs, w))
        rows.extend(_render_logs(logs, w, log_window, show_ids))

    return join_vertical(*rows)
