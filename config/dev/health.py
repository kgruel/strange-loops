"""Health checks — feedback handler + lens for project dev checks.

The feedback handler runs configured check commands sequentially, emits
``{name}.result`` facts (e.g. ``lint.result``, ``test.result``) with payload::

    {status: "passed"|"failed", output: "...", duration_s: float}

Exit-on-failure gate: if a check fails, subsequent checks don't run.

Two runners:
- ``run_checks``: synchronous, takes CheckStep list (fallback when no vertex)
- ``run_sequential_checks``: async, takes a compiled SequentialSource from a vertex
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from painted import Block, Style, Zoom, join_vertical
from painted.compose import join_horizontal
from painted.palette import current_palette
from painted.views import gutter_pass_fail, record_line_composed

if TYPE_CHECKING:
    from atoms.sequential import SequentialSource


@dataclass(frozen=True)
class CheckStep:
    """A single check to run."""

    name: str
    command: str


# Default checks for a Python project managed by uv.
DEFAULT_STEPS: list[CheckStep] = [
    CheckStep("lint", "uv run ty check src/ && uv run ruff format --check src/ tests/"),
    CheckStep("test", "uv run pytest tests/ -q --tb=line"),
]


def run_checks(
    store_path: Path,
    steps: list[CheckStep],
    *,
    observer: str = "dev-check",
    cwd: Path | None = None,
) -> list[dict[str, Any]]:
    """Run check steps sequentially, emit facts, stop on first failure.

    Returns the list of emitted fact dicts (for rendering).
    """
    from atoms import Fact
    from engine import SqliteStore

    results: list[dict[str, Any]] = []

    store_path.parent.mkdir(parents=True, exist_ok=True)

    for step in steps:
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                step.command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=str(cwd) if cwd else None,
            )
            status = "passed" if proc.returncode == 0 else "failed"
            output = (proc.stdout + proc.stderr).strip()
        except Exception as exc:
            status = "failed"
            output = str(exc)
        duration_s = round(time.monotonic() - t0, 2)

        fact = Fact.of(
            f"{step.name}.result",
            observer,
            status=status,
            output=output,
            duration_s=duration_s,
        )

        with SqliteStore(
            path=store_path,
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        ) as store:
            store.append(fact)

        results.append(fact.to_dict())

        if status == "failed":
            break

    return results


def run_sequential_checks(
    seq_source: SequentialSource,
    store_path: Path,
    *,
    observer: str = "dev-check",
) -> list[dict[str, Any]]:
    """Run each source individually and collect results in health_view format.

    Runs sources from the sequential block one at a time, catching SourceError
    to detect failures. Each result is stored as a fact in the vertex store.

    Returns the list of result dicts (for rendering via health_view).
    """
    from atoms import Fact, SourceError
    from engine import SqliteStore

    store_path.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    async def _run_all():
        for source in seq_source.sources:
            start = time.monotonic()
            lines: list[str] = []
            status = "passed"
            stderr_text = ""

            try:
                async for fact in source.collect():
                    line = fact.payload.get("line", "")
                    if line:
                        lines.append(line)
            except SourceError as e:
                status = "failed"
                stderr_text = e.stderr

            if stderr_text:
                lines.append(stderr_text)

            duration_s = round(time.monotonic() - start, 2)
            output = "\n".join(lines)

            result_fact = Fact.of(
                source.kind,
                observer,
                status=status,
                output=output,
                duration_s=duration_s,
            )

            with SqliteStore(
                path=store_path,
                serialize=Fact.to_dict,
                deserialize=Fact.from_dict,
            ) as store:
                store.append(result_fact)

            results.append(result_fact.to_dict())

            if status == "failed":
                break

    asyncio.run(_run_all())
    return results


# ---------------------------------------------------------------------------
# PayloadLens for *.result facts
# ---------------------------------------------------------------------------


def health_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
    """Render a check result payload.

    Follows PayloadLens protocol: (kind, payload, zoom) -> str | Block.
    """
    if not kind.endswith(".result"):
        return ""

    name = kind.removesuffix(".result")
    status = payload.get("status", "")
    duration = payload.get("duration_s", "")
    output = payload.get("output", "")

    if zoom <= Zoom.MINIMAL:
        return f"{name} {status}"

    # Return a string summary — record_line handles continuation lines
    # for 'output' (it's in the well-known secondary field keys).
    p = current_palette()
    status_style = p.success if status == "passed" else p.error

    parts: list[Block] = [
        Block.text(f"{name} ", Style()),
        Block.text(status, status_style),
    ]
    if duration:
        parts.append(Block.text(f" ({duration}s)", p.muted))

    return join_horizontal(*parts)


# ---------------------------------------------------------------------------
# Health view — renders check results with gutter
# ---------------------------------------------------------------------------


def health_view(results: list[dict[str, Any]], zoom: Zoom, width: int) -> Block:
    """Render check results using record_line_composed + gutter_pass_fail."""
    if not results:
        return Block.text("No check results.", Style(dim=True), width=width)

    if zoom == Zoom.MINIMAL:
        parts = []
        for r in results:
            name = r["kind"].removesuffix(".result")
            status = r.get("payload", {}).get("status", "")
            parts.append(f"{name} {status}")
        return Block.text("  ".join(parts), Style(), width=width)

    rows: list[Block] = []
    for r in results:
        ts_val = r["ts"]
        if isinstance(ts_val, (int, float)):
            ts = datetime.fromtimestamp(ts_val, tz=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        row = record_line_composed(
            ts,
            r["kind"],
            r.get("payload", {}),
            zoom,
            width,
            payload_lens=health_lens,
            gutter_fn=gutter_pass_fail,
        )
        rows.append(row)

    return join_vertical(*rows)
