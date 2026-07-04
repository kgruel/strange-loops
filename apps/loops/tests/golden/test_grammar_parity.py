"""Cross-command grammar golden (spine G6).

Renders every read surface — read (fold), stream, store ticks, store ticks
--chain, and ls (root + kind-descent) — over ONE shared fixture, on BOTH
channels (TTY + piped), at all four zooms, into a single golden tree. Its job
is to make cross-command grammar DRIFT visible in one review surface (the
missing cross-command golden the render-surface drift analysis identified):
when the rail, the card, the time vocabulary, or a register split changes on
one command but not its siblings, exactly one diff lands here.

This golden is EXPECTED to churn on grammar changes — regold it deliberately
(``--update-goldens``) and read the diff as the drift report.

Determinism: the fixture store is byte-stable (fixed fact timestamps, real
ticks — see ``builders.write_grammar_fixture``); the only clock read at render
time is ``recency()``, pinned here to ``FIXED_NOW``. Widths are forced.
"""
from __future__ import annotations

import dataclasses
import re

import pytest
from painted import Zoom

from lang import parse_vertex_file

from ..builders import GRAMMAR_T0
from .helpers import block_to_text

# A fixed "now" a couple of days after the newest fixture fact, so relative
# ages render as stable, positive spans ("2d", "1d 1h", ...).
FIXED_NOW = GRAMMAR_T0 + 90500 + 3 * 86400

_TTY_WIDTH = 80

COMMANDS = [
    "read", "stream", "ticks", "ticks-chain", "ls-root", "ls-kind",
    "confluence", "graph", "horizon",
]
CHANNELS = ["tty", "piped"]


@pytest.fixture(autouse=True)
def _pin_recency(monkeypatch):
    """Pin the render-time clock so ``recency()`` is deterministic."""
    monkeypatch.setattr("loops.lenses._grammar.time.time", lambda: FIXED_NOW)


def _ticks_data(vp, *, chain: bool) -> dict:
    """Reassemble the ``store ticks`` fetch dict (mirrors commands/store.py)."""
    from loops.commands.fetch import fetch_tick_windows, stamp_window_stats

    ast = parse_vertex_file(vp)
    windows = fetch_tick_windows(vp, since=None, all_names=chain)
    chain_d = {
        "ticks": len(windows),
        "chained": sum(1 for w in windows if w.chained),
        "signed": sum(1 for w in windows if w.signed),
        "legacy": sum(1 for w in windows if not w.chained),
    }
    window_dicts = [dataclasses.asdict(w) for w in windows]
    if not chain:
        stamp_window_stats(vp, window_dicts)
    return {
        "vertex": ast.name,
        "chain_mode": chain,
        "chain": chain_d,
        "since": None,
        "windows": window_dicts,
    }


def _root_data(vp) -> dict:
    """Build the ``sl ls`` root data dict for one fixture vertex."""
    from loops.commands.vertices import _enrich_with_stats, _extract_vertex_info

    ast = parse_vertex_file(vp)
    info = _extract_vertex_info(vp, ast)
    _enrich_with_stats(info)
    return {"vertices": [info], "expand_config": True, "terse": False}


def _render(command: str, vp, zoom: Zoom, *, piped: bool):
    """Render one command over the fixture on one channel — the real fetch+lens
    path each CLI verb uses, minus the run_cli plumbing."""
    width = None if piped else _TTY_WIDTH

    if command == "read":
        from loops.commands.fetch import fetch_fold
        from loops.lenses.fold import fold_view
        from loops.surface import project

        return fold_view(project(fetch_fold(vp)), zoom, width, piped=piped)

    if command == "stream":
        from loops.commands.fetch import fetch_stream
        from loops.lenses.stream import stream_view

        return stream_view(fetch_stream(vp, since="3650d"), zoom, width, piped=piped)

    if command in ("ticks", "ticks-chain"):
        from loops.lenses.store import tick_chain_view

        data = _ticks_data(vp, chain=command == "ticks-chain")
        return tick_chain_view(data, zoom, width, piped=piped)

    if command == "ls-root":
        from loops.lenses.vertices import vertices_view

        return vertices_view(_root_data(vp), zoom, width, piped=piped)

    if command == "confluence":
        from loops.commands.fetch import fetch_confluence
        from loops.lenses.confluence import confluence_view

        return confluence_view(fetch_confluence(vp), zoom, width, piped=piped)

    if command == "graph":
        from loops.commands.fetch import fetch_graph
        from loops.lenses.graph import graph_view

        return graph_view(fetch_graph(vp), zoom, width, piped=piped)

    if command == "horizon":
        from loops.commands.fetch import fetch_horizon
        from loops.lenses.horizon import horizon_view

        return horizon_view(fetch_horizon(vp), zoom, width, piped=piped)

    if command == "ls-kind":
        from loops.commands.ls import fetch_kind_stat
        from loops.lenses.declarations import kind_stat_view

        data = fetch_kind_stat(str(vp), "decision")
        return kind_stat_view(data, zoom, width, piped=piped)

    raise AssertionError(f"unknown command {command}")


# The store lives under a per-run tmp dir and its facts carry freshly-minted
# ULIDs (program.receive assigns them) — both non-deterministic (the ULID's
# random suffix never repeats, and its time prefix tracks wall clock). Scrub
# both the full ULID and the truncated ``id:`` display prefix to stable
# placeholders so the golden captures GRAMMAR, not run-specific ids.
_ULID = re.compile(r"[0-9A-HJKMNP-TV-Z]{26}")
# The truncated ``id:`` display prefix renders with (stream) or without (fold)
# a space; normalise both to one placeholder.
_ID_PREFIX = re.compile(r"id:\s*[0-9A-HJKMNP-TV-Z]{6,}")
# The FULL ls-root shows the store's absolute path — machine-specific and
# clipped at the TTY width; scrub the whole cell so the golden is portable.
_STORE_PATH = re.compile(r"store: \S+")


def _scrub(text: str, vp) -> str:
    text = text.replace(str(vp.parent), "<TMP>")
    text = _ULID.sub("<ULID>", text)
    text = _ID_PREFIX.sub("id: <ID>", text)
    return _STORE_PATH.sub("store: <STORE>", text)


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
@pytest.mark.parametrize("channel", CHANNELS)
def test_grammar_parity(golden, grammar_store, command, zoom, channel):
    block = _render(command, grammar_store, zoom, piped=channel == "piped")
    text = _scrub(block_to_text(block, use_ansi=False), grammar_store)
    golden.assert_match(text, "output")
