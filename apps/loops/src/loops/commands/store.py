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


def _run_store(argv: list[str], *, vertex_path: Path | None = None) -> int:
    """Run store command via painted CLI harness."""
    import argparse
    from painted import run_cli, OutputMode
    from painted.cli import HelpArg
    from .resolve import loops_home

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("file", nargs="?", default=None)
    known, rest = pre.parse_known_args(argv)
    file_arg = getattr(known, "file", None)

    def _resolve_store_target() -> Path:
        if vertex_path is not None:
            return vertex_path
        if file_arg is not None:
            p = Path(file_arg)
            if p.suffix or file_arg.startswith("./") or file_arg.startswith("/"):
                return p
            from lang.population import resolve_vertex

            return resolve_vertex(file_arg, loops_home())
        home = loops_home()
        root = home / ".vertex"
        if root.exists():
            return root
        raise FileNotFoundError(f"{root} not found. Run 'loops init' first.")

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
        help_args=[
            HelpArg("file", "Store file, vertex name, or path", positional=True),
        ],
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
