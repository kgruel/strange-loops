"""Store command — fetch store data for inspection.

Pure data fetch, no rendering knowledge.
"""
from __future__ import annotations

from pathlib import Path

_SPARK_CHARS = " ▁▂▃▄▅▆▇█"


def _bucket_timestamps(timestamps: list[float], width: int) -> list[float]:
    """Bucket timestamps into equal-width time bins, return counts per bin.

    *timestamps* should be sorted newest-first (as returned by
    ``StoreReader.tick_timestamps``).  Returns *width* floats — one
    count per bin, ordered oldest→newest so the visual reads left-to-right.
    """
    if not timestamps or width <= 0:
        return []
    lo, hi = min(timestamps), max(timestamps)
    if lo == hi:
        # All ticks at same instant — single spike in the middle
        buckets = [0.0] * width
        buckets[width // 2] = float(len(timestamps))
        return buckets
    span = hi - lo
    buckets = [0.0] * width
    for ts in timestamps:
        idx = int((ts - lo) / span * (width - 1))
        idx = max(0, min(idx, width - 1))
        buckets[idx] += 1.0
    return buckets


def _sparkline_str(values: list[float]) -> str:
    """Map bucket counts to sparkline characters."""
    if not values:
        return ""
    mx = max(values)
    if mx == 0:
        return " " * len(values)
    return "".join(
        _SPARK_CHARS[int(v / mx * (len(_SPARK_CHARS) - 1))]
        for v in values
    )


def resolve_store_path(file_path: Path) -> Path:
    """Resolve a .vertex or .db file to the actual store .db path."""
    if file_path.suffix == ".vertex":
        from lang import parse_vertex_file

        ast = parse_vertex_file(file_path)
        if ast.store is None:
            raise ValueError(f"No store configured in {file_path}")
        return (file_path.parent / ast.store).resolve()
    elif file_path.suffix == ".db":
        return file_path.resolve()
    else:
        raise ValueError(f"Expected .vertex or .db file, got {file_path.suffix}")


def make_fetcher(path: Path, zoom: int):
    """Create a zero-arg fetcher for store data.

    zoom controls enrichment depth:
      0:   summary only (counts + stats)
      1:   + sparkline + payload_keys per tick
      2:   + latest tick payloads
      3:   + recent fact payloads
    """
    def fetch() -> dict:
        from engine.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            data = reader.summary()
            data["freshness"] = reader.freshness
            if zoom >= 1:
                # Sparkline + payload keys per tick name
                for name, info in data["ticks"]["names"].items():
                    ts_list = reader.tick_timestamps(name, 50)
                    buckets = _bucket_timestamps(ts_list, 8)
                    info["sparkline"] = _sparkline_str(buckets)
                    # Extract payload key names from latest tick
                    recent = reader.recent_ticks(name, 1)
                    info["payload_keys"] = (
                        list(recent[0].payload.keys()) if recent else []
                    )
                # Keep sample payload per fact kind for SUMMARY gist
                for kind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(kind, 1)
                    if recent:
                        info["sample_payload"] = recent[0]["payload"]
            if zoom >= 2:
                for name, info in data["ticks"]["names"].items():
                    recent = reader.recent_ticks(name, 3)
                    if recent:
                        info["latest_payload"] = recent[0].payload
                        info["latest_since"] = recent[0].since.timestamp() if recent[0].since else None
                        info["latest_ts"] = recent[0].ts.timestamp()
            if zoom >= 3:
                for kind, info in data["facts"]["kinds"].items():
                    recent = reader.recent_facts(kind, 5)
                    info["recent"] = [f["payload"] for f in recent]
            return data
    return fetch


def _resolve_target(file_arg: str | None, vertex_path: Path | None) -> Path:
    """Resolve the store target: explicit vertex_path > file/name arg > local root."""
    from .resolve import loops_home

    if vertex_path is not None:
        return vertex_path
    if file_arg is not None:
        p = Path(file_arg)
        if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
            return p
        # Local-first — same resolution the verbs use
        # (thread:global-local-walk-broken).
        from .resolve import _resolve_vertex_for_dispatch

        resolved = _resolve_vertex_for_dispatch(file_arg)
        if resolved is not None:
            return resolved
        from lang.population import resolve_vertex

        return resolve_vertex(file_arg, loops_home())
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    raise FileNotFoundError(f"{root} not found. Run 'loops init' first.")


def _run_verify(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Verify the tick hash chain of a store. Exit 0 = intact, 1 = broken.

    Read-only — never migrates schema. Pre-chain stores report all ticks
    as legacy and pass (nothing to verify yet).
    """
    import argparse
    import sys as _sys

    p = argparse.ArgumentParser(
        prog="loops store verify",
        description="Verify tick hash chain and fact-window commitments.",
    )
    if vertex_path is None:
        p.add_argument("file", nargs="?", help="Store .db or .vertex file, or vertex name")
    p.add_argument("--json", action="store_true", help="JSON report")
    if "-h" in argv or "--help" in argv:
        p.print_help(_sys.stdout)
        return 0
    args = p.parse_args(argv)

    db_path = resolve_store_path(_resolve_target(getattr(args, "file", None), vertex_path).resolve())
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} does not exist")

    from atoms import Fact
    from engine.sqlite_store import SqliteStore

    store = SqliteStore(path=db_path, serialize=lambda f: f.to_dict(), deserialize=Fact.from_dict)
    try:
        report = store.verify_chain()
    finally:
        store.close()

    if args.json:
        import json as _json
        print(_json.dumps(report, indent=2))  # noqa: T201 — machine output path
        return 0 if report["ok"] else 1

    from painted import Block, Style, show

    verdict = "chain intact" if report["ok"] else "CHAIN BROKEN"
    lines = [
        f"{'✓' if report['ok'] else '✗'} {db_path.name}: {verdict}",
        f"  ticks: {report['ticks']} ({report['chained']} chained, {report['legacy']} legacy)",
        f"  facts: {report['covered_facts']} covered, {report['uncovered_facts']} uncovered (live edge)",
    ]
    for b in report["breaks"]:
        lines.append(f"  ✗ {b['name']} ({b['tick']}): {b['reason']}")
    if report["truncated"]:
        lines.append(f"  … stopped after {len(report['breaks'])} breaks")
    show(Block.text("\n".join(lines), Style(dim=False)))
    return 0 if report["ok"] else 1


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    import argparse
    from painted import run_cli, OutputMode

    if argv and argv[0] == "verify":
        return _run_verify(argv[1:], vertex_path=vertex_path)

    if "-h" in argv or "--help" in argv:
        import sys as _sys
        p = argparse.ArgumentParser(
            prog="loops store",
            description="Inspect store contents. Subcommand: "
                        "'loops store verify [target]' checks the tick hash chain.",
        )
        if vertex_path is None:
            p.add_argument("file", nargs="?", help="Store .db or .vertex file, or vertex name")
        p.add_argument("-i", "--interactive", action="store_true", help="Interactive TUI explorer")
        p.add_argument("-q", "--quiet", action="store_true", help="Minimal output")
        p.add_argument("-v", "--verbose", action="store_true", help="Detailed output")
        p.add_argument("--json", action="store_true", help="JSON output")
        p.add_argument("--plain", action="store_true", help="Plain text, no ANSI codes")
        p.print_help(_sys.stdout)
        return 0

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    def _resolve_store_target() -> Path:
        return _resolve_target(file_arg, vertex_path)

    def fetch():
        path = _resolve_store_target().resolve()
        if not path.exists():
            raise FileNotFoundError(f"{path} does not exist")
        return make_fetcher(path, zoom=3)()

    def render(ctx, data):
        from ..lenses.store import store_view

        return store_view(data, ctx.zoom, ctx.width)

    async def fetch_stream():
        import asyncio

        while True:
            try:
                yield fetch()
            except FileNotFoundError:
                pass
            await asyncio.sleep(2.0)

    def handle_interactive(ctx):
        import asyncio as _asyncio
        from ..tui import StoreExplorerApp

        path = _resolve_store_target().resolve()
        app = StoreExplorerApp(path)
        _asyncio.run(app.run())
        return 0

    return run_cli(
        rest,
        fetch=fetch,
        fetch_stream=fetch_stream,
        render=render,
        handlers={OutputMode.INTERACTIVE: handle_interactive},
        default_mode=OutputMode.STATIC,
        prog="loops store",
        description="Inspect store contents",
    )


def make_fidelity_fetcher(path: Path):
    """Create a fetcher for fidelity drill data.

    Returns a callable (since_ts, until_ts, kind?) -> list[dict].
    Each call opens and closes its own StoreReader — the TUI calls this
    on-demand when the user presses 'f', not on every frame.
    """
    def fetch(since_ts: float, until_ts: float, kind: str | None = None) -> list[dict]:
        from engine.store_reader import StoreReader

        store_path = resolve_store_path(path)
        with StoreReader(store_path) as reader:
            return reader.facts_between(since_ts, until_ts, kind=kind)
    return fetch
