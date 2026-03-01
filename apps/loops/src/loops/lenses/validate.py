"""Validate lens — zoom-aware rendering for validation results."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from painted import Block, Style, Zoom, join_vertical


def validate_view(data: dict[str, Any], zoom: Zoom, width: int) -> Block:
    """Render validation results at the given zoom level.

    data: {results: [{path, valid, error}], checked: int, errors: int}

    Zoom levels:
    - MINIMAL: N valid, M errors
    - SUMMARY: per-file checkmark/cross with short error
    - DETAILED: + full error messages
    - FULL: + resolved absolute path per file
    """
    results = data.get("results", [])
    checked = data.get("checked", 0)
    errors = data.get("errors", 0)

    if not results:
        return Block.text(
            "No .loop or .vertex files found", Style(dim=True), width=width,
        )

    if zoom == Zoom.MINIMAL:
        return Block.text(
            f"{checked} valid, {errors} errors", Style(), width=width,
        )

    rows: list[Block] = []
    dim_style = Style(dim=True)

    for r in results:
        path = r["path"]
        if r["valid"]:
            rows.append(Block.text(f"\u2713 {path}", Style(), width=width))
            if zoom == Zoom.FULL:
                resolved = str(Path(path).resolve())
                if resolved != path:
                    rows.append(Block.text(f"    {resolved}", dim_style, width=width))
        else:
            err = r.get("error", "")
            if zoom >= Zoom.DETAILED and err:
                rows.append(Block.text(f"\u2717 {path}:", Style(), width=width))
                if zoom == Zoom.FULL:
                    resolved = str(Path(path).resolve())
                    if resolved != path:
                        rows.append(Block.text(f"    {resolved}", dim_style, width=width))
                rows.append(Block.text(f"    {err}", dim_style, width=width))
            else:
                short = err.split("\n")[0][:60] if err else ""
                msg = f"\u2717 {path}: {short}" if short else f"\u2717 {path}"
                rows.append(Block.text(msg, Style(), width=width))

    return join_vertical(*rows)
