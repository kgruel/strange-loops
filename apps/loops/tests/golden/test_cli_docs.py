"""Generate CLI.md from the same golden fixtures.

Running this test with --update-goldens regenerates apps/loops/docs/CLI.md.
In normal mode it verifies the doc is up to date.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from unittest.mock import patch

from painted import Zoom

from loops.lenses.validate import validate_view
from loops.lenses.test import test_view as _test_view
from loops.lenses.run import run_facts_view, run_ticks_view
from loops.lenses.compile import compile_view
from loops.lenses.start import start_view
from loops.lenses.store import store_view
from loops.lenses.pop import pop_view
from loops.lenses.status import status_view
from loops.lenses.log import log_view

from .fixtures import (
    SAMPLE_STATUS,
    SAMPLE_LOG,
    SAMPLE_STORE,
    SAMPLE_START,
    SAMPLE_COMPILE_LOOP,
    SAMPLE_COMPILE_VERTEX,
    SAMPLE_VALIDATE,
    SAMPLE_TEST,
    SAMPLE_LS,
    SAMPLE_FACTS,
    SAMPLE_TICKS,
    REF_DT,
)
from .test_store import _frozen_relative_time
from .helpers import block_to_text

import pytest

CLI_MD = Path(__file__).resolve().parents[2] / "docs" / "CLI.md"
ZOOM = Zoom.SUMMARY
WIDTH = 80


_COMMANDS: list[tuple[str, str, str]] = []


def _render_all() -> list[tuple[str, str, str]]:
    """Return (command_name, description, rendered_output) for each command."""
    if _COMMANDS:
        return _COMMANDS

    entries: list[tuple[str, str, str]] = []

    entries.append((
        "status",
        "Session status — decisions, threads, tasks, changes.",
        block_to_text(status_view(SAMPLE_STATUS, ZOOM, WIDTH)),
    ))
    entries.append((
        "log",
        "Session log — chronological facts.",
        block_to_text(log_view(SAMPLE_LOG, ZOOM, WIDTH)),
    ))

    with patch("loops.lenses.store._relative_time", _frozen_relative_time):
        entries.append((
            "store",
            "Store inspection — ticks, facts, freshness.",
            block_to_text(store_view(SAMPLE_STORE, ZOOM, WIDTH)),
        ))

    entries.append((
        "start",
        "Run vertex and display tick results.",
        block_to_text(start_view(SAMPLE_START, ZOOM, WIDTH)),
    ))
    entries.append((
        "compile (loop)",
        "Compiled .loop source structure.",
        block_to_text(compile_view(SAMPLE_COMPILE_LOOP, ZOOM, WIDTH)),
    ))
    entries.append((
        "compile (vertex)",
        "Compiled .vertex structure.",
        block_to_text(compile_view(SAMPLE_COMPILE_VERTEX, ZOOM, WIDTH)),
    ))
    entries.append((
        "validate",
        "Validate .loop and .vertex files.",
        block_to_text(validate_view(SAMPLE_VALIDATE, ZOOM, WIDTH)),
    ))
    entries.append((
        "test",
        "Test parse pipeline with sample input.",
        block_to_text(_test_view(SAMPLE_TEST, ZOOM, WIDTH)),
    ))
    entries.append((
        "ls",
        "List population entries.",
        block_to_text(pop_view(SAMPLE_LS, ZOOM, WIDTH)),
    ))
    entries.append((
        "run (facts)",
        "Stream facts from a running loop.",
        block_to_text(run_facts_view(SAMPLE_FACTS, ZOOM, WIDTH)),
    ))
    entries.append((
        "run (ticks)",
        "Stream ticks from a running vertex.",
        block_to_text(run_ticks_view(SAMPLE_TICKS, ZOOM, WIDTH)),
    ))

    _COMMANDS.extend(entries)
    return entries


def _build_doc() -> str:
    """Build CLI.md content from rendered command output."""
    lines = [
        "# Loops CLI Reference",
        "",
        "> Auto-generated from golden test fixtures. Do not edit by hand.",
        f"> Rendered at zoom level: **{ZOOM.name}**, width: {WIDTH}",
        "",
    ]

    for name, desc, output in _render_all():
        lines.append(f"## `{name}`")
        lines.append("")
        lines.append(desc)
        lines.append("")
        lines.append("```")
        lines.append(output.rstrip())
        lines.append("```")
        lines.append("")

    return "\n".join(lines) + "\n"


def test_cli_docs(request):
    update = request.config.getoption("--update-goldens")
    content = _build_doc()

    if update or not CLI_MD.exists():
        CLI_MD.parent.mkdir(parents=True, exist_ok=True)
        CLI_MD.write_text(content)
        return

    expected = CLI_MD.read_text()
    if content != expected:
        diff = difflib.unified_diff(
            expected.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=str(CLI_MD),
            tofile="generated",
        )
        pytest.fail(f"CLI.md is out of date. Run with --update-goldens.\n{''.join(diff)}")
