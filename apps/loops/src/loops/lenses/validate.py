"""Validate lens — zoom-aware rendering for validation results."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def _block(text: str, style: Style, width: int | None) -> Block:
    """Create a Block, respecting width=None (no truncation)."""
    if width is not None:
        return Block.text(text, style, width=width)
    return Block.text(text, style)


def _warn_line(w: dict[str, Any]) -> str:
    """One non-fatal WARN row (S5 folded-state lifecycle scan)."""
    if w.get("kind") == "active-targets-inactive":
        return (
            f"⚠ active-targets-inactive: {w['source']} → {w['target']} "
            f"[{w.get('path', '')}]"
        )
    if w.get("kind") == "missing-status":
        return (
            f"⚠ missing-status: {w['source']} has no '{w['field']}' field "
            f"(lifecycle-declared kind, shown fail-open) [{w.get('path', '')}]"
        )
    return f"⚠ {w}"


def validate_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render validation results at the given zoom level.

    data: {results: [{path, valid, error}], checked: int, errors: int,
           warnings: [{kind, source, target|field, path}]}

    Zoom levels:
    - MINIMAL: N valid, M errors (+ W warnings when any)
    - SUMMARY: per-file checkmark/cross with error (never truncated) + WARN rows
    - DETAILED: + full error messages
    - FULL: + resolved absolute path per file

    Warnings are a distinct NON-FATAL tier (folded-state lifecycle scan, S5) —
    rendered below the syntax pass/fail rows, never changing the exit code.
    """
    results = data.get("results", [])
    checked = data.get("checked", 0)
    errors = data.get("errors", 0)
    warnings = data.get("warnings", []) or []

    if not results:
        return _block("No .loop or .vertex files found", Style(dim=True), width)

    if zoom == Zoom.MINIMAL:
        tail = f", {len(warnings)} warnings" if warnings else ""
        return _block(f"{checked} valid, {errors} errors{tail}", Style(), width)

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for r in results:
        path = r["path"]
        if r["valid"]:
            rows.append(_block(f"\u2713 {path}", Style(), width))
            if zoom == Zoom.FULL:
                resolved = str(Path(path).resolve())
                if resolved != path:
                    rows.append(_block(f"    {resolved}", dim_style, width))
        else:
            err = r.get("error", "")
            if zoom >= Zoom.DETAILED and err:
                rows.append(_block(f"\u2717 {path}:", Style(), width))
                if zoom == Zoom.FULL:
                    resolved = str(Path(path).resolve())
                    if resolved != path:
                        rows.append(_block(f"    {resolved}", dim_style, width))
                rows.append(_block(f"    {err}", dim_style, width))
            else:
                # Show first line of error — never truncate error content
                short = err.split("\n")[0] if err else ""
                msg = f"\u2717 {path}: {short}" if short else f"\u2717 {path}"
                rows.append(_block(msg, Style(), width))

    # Non-fatal WARN tier \u2014 folded-state lifecycle scan (S5). Distinct from the
    # syntax pass/fail rows above; exit code is unaffected.
    if warnings:
        warn_style = Style(fg=208)  # orange \u2014 a heads-up, not a failure
        rows.append(_block("", Style(), width))
        for w in warnings:
            rows.append(_block(_warn_line(w), warn_style, width))

    return join_vertical(*rows)
