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


def validate_view(data: dict[str, Any], zoom: Zoom, width: int | None) -> Block:
    """Render validation results at the given zoom level.

    data: {results: [{path, valid, error}], checked: int, errors: int}

    Zoom levels:
    - MINIMAL: N valid, M errors
    - SUMMARY: per-file checkmark/cross with error (never truncated)
    - DETAILED: + full error messages
    - FULL: + resolved absolute path per file
    """
    results = data.get("results", [])
    checked = data.get("checked", 0)
    errors = data.get("errors", 0)

    if not results:
        return _block("No .loop or .vertex files found", Style(dim=True), width)

    if zoom == Zoom.MINIMAL:
        return _block(f"{checked} valid, {errors} errors", Style(), width)

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

    return join_vertical(*rows)
